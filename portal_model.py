#!/usr/bin/env python3
import datetime as dt
import hashlib
import hmac
import json
from pathlib import Path
import posixpath
import threading
import time
import unicodedata

from portal_core import (
    b64,
    cleanup_cache_dir,
    event_matches_target,
    format_size,
    now_ts,
    rotate_audit_log,
    safe_name,
    unb64,
)
from portal_settings import (
    AUDIT_LOG_PATH,
    CACHE_MAX_BYTES,
    CACHE_RETENTION_DAYS,
    LOGIN_RATE_MAX_FAILURES,
    LOGIN_RATE_WINDOW_SECONDS,
    MAX_AUDIT_DISPLAY,
    PAGE_CACHE_DIR,
    PREVIEW_CACHE_DIR,
)


class Portal:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config = json.loads(config_path.read_text(encoding="utf-8"))
        self.secret = self.config["secret_key"].encode("utf-8")
        self.config_lock = threading.Lock()
        self.login_failures: dict[tuple[str, str], list[float]] = {}
        self.login_lock = threading.Lock()
        self.audit_write_failures = 0
        self.maintenance_summary = self.run_maintenance()

    def run_maintenance(self) -> dict:
        rotated = rotate_audit_log()
        preview = cleanup_cache_dir(PREVIEW_CACHE_DIR, CACHE_RETENTION_DAYS, CACHE_MAX_BYTES)
        pages = cleanup_cache_dir(PAGE_CACHE_DIR, CACHE_RETENTION_DAYS, CACHE_MAX_BYTES)
        audit_size = AUDIT_LOG_PATH.stat().st_size if AUDIT_LOG_PATH.exists() else 0
        summary = {
            "audit_size": audit_size,
            "audit_rotated": str(rotated) if rotated else "",
            "preview_cache": preview,
            "page_cache": pages,
        }
        if rotated:
            print(f"audit log rotated to {rotated}", flush=True)
        removed = int(preview.get("removed", 0)) + int(pages.get("removed", 0))
        if removed:
            reclaimed = int(preview.get("reclaimed", 0)) + int(pages.get("reclaimed", 0))
            print(f"portal cache cleanup removed={removed} reclaimed={format_size(reclaimed)}", flush=True)
        return summary

    def sign(self, payload: dict) -> str:
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        sig = hmac.new(self.secret, raw, hashlib.sha256).digest()
        return f"{b64(raw)}.{b64(sig)}"

    def unsign(self, token: str) -> dict | None:
        try:
            raw_b64, sig_b64 = token.split(".", 1)
            raw = unb64(raw_b64)
            sig = unb64(sig_b64)
        except Exception:
            return None
        expected = hmac.new(self.secret, raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None
        if payload.get("exp", 0) < now_ts():
            return None
        return payload

    def user(self, username: str) -> dict | None:
        data = self.config.get("users", {}).get(username)
        if not data:
            return None
        return {"username": username, **data}

    def login_limited(self, client_ip: str, username: str) -> bool:
        key = (client_ip, username.strip().lower())
        cutoff = time.time() - LOGIN_RATE_WINDOW_SECONDS
        with self.login_lock:
            failures = [stamp for stamp in self.login_failures.get(key, []) if stamp >= cutoff]
            self.login_failures[key] = failures
            return len(failures) >= LOGIN_RATE_MAX_FAILURES

    def record_login_failure(self, client_ip: str, username: str) -> None:
        key = (client_ip, username.strip().lower())
        cutoff = time.time() - LOGIN_RATE_WINDOW_SECONDS
        with self.login_lock:
            failures = [stamp for stamp in self.login_failures.get(key, []) if stamp >= cutoff]
            failures.append(time.time())
            self.login_failures[key] = failures

    def clear_login_failures(self, client_ip: str, username: str) -> None:
        key = (client_ip, username.strip().lower())
        with self.login_lock:
            self.login_failures.pop(key, None)

    def roots_for(self, user: dict) -> list[dict]:
        roots = []
        for root in user.get("roots", []):
            item = dict(root)
            item["path"] = str(Path(item["path"]).resolve())
            roots.append(item)
        return roots

    def all_users(self) -> list[dict]:
        users = [self.user(username) for username in self.config.get("users", {})]
        return [user for user in users if user]

    def log_event(self, event: dict):
        record = {
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            **event,
        }
        try:
            AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError as exc:
            self.audit_write_failures += 1
            print(f"audit log write failed: {exc}", flush=True)

    def recent_events(self, limit: int = MAX_AUDIT_DISPLAY * 4) -> list[dict]:
        try:
            lines = AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        events = []
        for line in reversed(lines[-limit * 4 :]):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(events) >= limit:
                break
        return events

    def events_for_target(self, target: Path, limit: int = 8) -> list[dict]:
        events = []
        for event in self.recent_events(160):
            if event_matches_target(event, target):
                events.append(event)
                if len(events) >= limit:
                    break
        return events

    def root_for(self, user: dict, root_id: str) -> dict | None:
        return next((r for r in self.roots_for(user) if r["id"] == root_id), None)

    def is_personal_shared_path(self, target: Path) -> bool:
        try:
            resolved = target.resolve()
        except OSError:
            resolved = target
        for user_data in self.config.get("users", {}).values():
            for root in user_data.get("roots", []):
                if root.get("id") != "personal":
                    continue
                shared_path = (Path(root.get("path", "")) / "shared").resolve()
                if resolved == shared_path or shared_path in resolved.parents:
                    return True
        return False

    def resolve_path(self, user: dict, root_id: str, rel_path: str) -> tuple[dict, Path] | tuple[None, None]:
        root = self.root_for(user, root_id)
        if not root:
            return None, None
        root_path = Path(root["path"]).resolve()
        normalized = posixpath.normpath("/" + rel_path).lstrip("/")
        target = (root_path / normalized).resolve()
        if not target.exists():
            target = self.resolve_unicode_equivalent_path(root_path, normalized)
        if root_id in {"personal", "all"} and self.is_personal_shared_path(target):
            return None, None
        if root_path != target and root_path not in target.parents:
            return None, None
        if not safe_name(target.relative_to(root_path)):
            return None, None
        return root, target

    def resolve_unicode_equivalent_path(self, root_path: Path, rel_path: str) -> Path:
        current = root_path
        for part in Path(rel_path).parts:
            direct = current / part
            if direct.exists():
                current = direct
                continue
            if not current.is_dir():
                return root_path / rel_path
            wanted = unicodedata.normalize("NFC", part)
            try:
                candidates = sorted(current.iterdir(), key=lambda item: item.name)
            except OSError:
                return root_path / rel_path
            match = next((candidate for candidate in candidates if unicodedata.normalize("NFC", candidate.name) == wanted), None)
            if not match:
                return root_path / rel_path
            current = match
        return current.resolve()
