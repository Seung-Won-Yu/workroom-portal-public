#!/usr/bin/env python3
import datetime as dt
import hashlib
import hmac
import html
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import posixpath
import secrets
import shutil
import time
import unicodedata

from workroom.core.settings import (
    AUDIT_ACTION_LABELS,
    AUDIT_LOG_PATH,
    AUDIT_ROTATE_BYTES,
    BLOCKED_UPLOAD_EXTENSIONS,
    FILE_STATUS_LABELS,
    HIDDEN_DIR_NAMES,
    MAX_SCAN_FILES,
    OPERATIONAL_RECENT_FILES,
    OPERATIONAL_RECENT_PREFIXES,
    PERSONAL_UPLOAD_DIRS,
    PROTECTED_PERSONAL_DIRS,
    SECRET_EXTENSIONS,
    SECRET_NAMES,
    SECRET_SUBSTRINGS,
    SELFTEST_ACTOR_PREFIXES,
    SELFTEST_PATH_MARKERS,
    SHARED_MOVE_TARGETS,
    TEXT_EXTENSIONS,
    WINDOWS_RESERVED_NAMES,
)
from workroom.core.urls import portal_url


def now_ts():
    return int(time.time())


def b64(value: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def unb64(value: str) -> bytes:
    import base64

    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + pad).encode("ascii"))


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 160_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, expected = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    actual = hash_password(password, salt).split("$", 2)[2]
    return hmac.compare_digest(actual, expected)


def is_private_client(ip: str) -> bool:
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return parsed.is_private or parsed.is_loopback


def is_loopback_client(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def first_valid_ip(values: list[str]) -> str:
    for value in values:
        candidate = value.strip().strip('"')
        if not candidate:
            continue
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        return candidate
    return ""


def request_client_ip(headers, peer_ip: str) -> tuple[str, str]:
    if not is_loopback_client(peer_ip):
        return peer_ip, "socket"
    cf_ip = first_valid_ip([headers.get("CF-Connecting-IP", "")])
    if cf_ip:
        return cf_ip, "CF-Connecting-IP"
    xff_values = headers.get("X-Forwarded-For", "")
    xff_ip = first_valid_ip(xff_values.split(","))
    if xff_ip:
        return xff_ip, "X-Forwarded-For"
    real_ip = first_valid_ip([headers.get("X-Real-IP", "")])
    if real_ip:
        return real_ip, "X-Real-IP"
    return peer_ip, "socket"


def safe_name(path: Path) -> bool:
    for part in path.parts:
        lowered = part.lower()
        if lowered in HIDDEN_DIR_NAMES:
            return False
        if lowered in SECRET_NAMES:
            return False
        if lowered.startswith(".") and lowered not in {".archive"}:
            return False
        if Path(lowered).suffix in SECRET_EXTENSIONS:
            return False
        if any(term in lowered for term in SECRET_SUBSTRINGS):
            return False
    return True


def format_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def content_type_for(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    suffix = path.suffix.lower()
    utf8_suffixes = {
        ".css",
        ".csv",
        ".htm",
        ".html",
        ".js",
        ".json",
        ".log",
        ".md",
        ".mjs",
        ".ps1",
        ".py",
        ".sh",
        ".svg",
        ".ts",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
    if "charset=" not in mime and (mime.startswith("text/") or suffix in utf8_suffixes):
        return f"{mime}; charset=utf-8"
    return mime


def format_mtime(path: Path) -> str:
    try:
        timestamp = path.stat().st_mtime
    except OSError:
        return "-"
    return dt.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def normalized_rel_path(rel_path: str) -> str:
    return posixpath.normpath("/" + rel_path).lstrip("/")


def search_key(value) -> str:
    return unicodedata.normalize("NFC", str(value or "")).casefold()


def is_operational_recent_path(root: dict, rel_path: str) -> bool:
    normalized = normalized_rel_path(rel_path)
    if is_selftest_path(normalized):
        return True
    if root.get("id") != "all":
        return False
    if normalized in OPERATIONAL_RECENT_FILES:
        return True
    return any(normalized.startswith(prefix) for prefix in OPERATIONAL_RECENT_PREFIXES)


def is_selftest_path(value) -> bool:
    text = str(value or "").replace("\\", "/").lower()
    if not text:
        return False
    return any(marker in text for marker in SELFTEST_PATH_MARKERS)


def is_selftest_event(event: dict) -> bool:
    actor = str(event.get("actor") or "").lower()
    if any(actor.startswith(prefix) for prefix in SELFTEST_ACTOR_PREFIXES):
        return True
    for key in (
        "path",
        "path_abs",
        "before_path",
        "before_path_abs",
        "after_path",
        "after_path_abs",
        "archive_path",
        "archive_path_abs",
        "reason",
    ):
        if is_selftest_path(event.get(key)):
            return True
    return False


def operational_events(events: list[dict]) -> list[dict]:
    return [event for event in events if not is_selftest_event(event)]


def can_archive_personal_path(root: dict, rel_path: str) -> bool:
    if root.get("id") != "personal":
        return False
    normalized = normalized_rel_path(rel_path)
    if not normalized or normalized == ".":
        return False
    parts = [part for part in normalized.split("/") if part]
    if not parts or parts[0] not in PERSONAL_UPLOAD_DIRS:
        return False
    if len(parts) == 1 and parts[0] in PROTECTED_PERSONAL_DIRS:
        return False
    return True


def safe_entry_name(name: str) -> bool:
    stripped = name.strip()
    if not stripped or stripped in {".", ".."}:
        return False
    if len(stripped.encode("utf-8")) > 255:
        return False
    if "/" in stripped or "\\" in stripped or "\x00" in stripped:
        return False
    if any(ord(char) < 32 for char in stripped):
        return False
    if stripped.endswith((" ", ".")):
        return False
    reserved_base = stripped.split(".", 1)[0].lower()
    if reserved_base in WINDOWS_RESERVED_NAMES:
        return False
    return safe_name(Path(stripped))


def safe_upload_name(name: str) -> bool:
    if not safe_entry_name(name):
        return False
    suffix = Path(name).suffix.lower()
    return suffix not in BLOCKED_UPLOAD_EXTENSIONS


def unique_peer_path(path: Path, is_dir: bool) -> Path:
    if not path.exists():
        return path
    if is_dir:
        stem = path.name
        suffix = ""
    else:
        stem = path.stem
        suffix = path.suffix
    counter = 1
    while True:
        candidate = path.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def default_shared_target(rel_path: str) -> str:
    parts = normalized_rel_path(rel_path).split("/")
    for part in parts[:2]:
        if part in {"dev", "research", "summary"}:
            return part
    return "handoff"


def shared_move_plan(rel_path: str, name: str = "") -> dict[str, str]:
    normalized = normalized_rel_path(rel_path)
    target_key = default_shared_target(normalized)
    target_label = SHARED_MOVE_TARGETS[target_key]
    display_name = name or Path(normalized).name or normalized
    if target_key in PERSONAL_UPLOAD_DIRS:
        reason = f"{PERSONAL_UPLOAD_DIRS[target_key]} 폴더의 산출물이므로 {target_label}를 추천합니다."
    else:
        reason = "개발/리서치/요약 외 산출물은 인수인계 공유를 기본 위치로 추천합니다."
    return {
        "target": target_key,
        "target_label": target_label,
        "reason": reason,
        "destination": f"팀 공유공간 / {target_key} / {display_name}",
    }


def personal_upload_dir_key(rel_path: str) -> str:
    normalized = normalized_rel_path(rel_path)
    if not normalized or normalized == ".":
        return ""
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return ""
    return parts[0] if parts[0] in PERSONAL_UPLOAD_DIRS else ""


def can_upload_to_folder(root: dict, folder: Path, rel_path: str = "") -> bool:
    if root.get("id") != "personal" or not folder.exists() or not folder.is_dir():
        return False
    root_path = Path(root["path"]).resolve()
    try:
        folder_rel = folder.resolve().relative_to(root_path).as_posix()
    except ValueError:
        return False
    return bool(personal_upload_dir_key(folder_rel if folder_rel != "." else rel_path))


def operation_notice_html(msg: str, details: dict[str, str] | None = None) -> str:
    messages = {
        "archived": "보관함으로 이동했습니다. 실제 삭제가 아니며, 복구가 필요하면 관리자에게 파일명과 원래 위치를 알려주세요.",
        "renamed": "이름을 변경했습니다.",
        "restored": "보관함에서 원래 작업공간으로 복구했습니다.",
        "shared": "팀 공유로 이동했습니다. 이제 같은 팀원이 팀 공유공간에서 확인할 수 있으며, 이 파일은 개인 작업공간 목록에는 더 이상 표시되지 않습니다.",
        "status_updated": "파일 상태를 변경했습니다.",
        "upload_scope": "업로드는 개발 산출물, 조사 자료, 요약/보고 자료 폴더에서만 가능합니다.",
        "uploaded": "개인공간에 업로드했습니다. 검토 후 필요한 파일만 팀 공유로 이동하세요.",
    }
    text = messages.get(msg)
    if not text:
        return ""
    if msg == "archived" and details:
        detail_rows = []
        for key, label in (
            ("archived_name", "파일명"),
            ("archived_path", "원래 위치"),
            ("archived_at", "보관한 시간"),
            ("archived_by", "요청자"),
        ):
            value = details.get(key, "")
            if value:
                detail_rows.append(f"<li><strong>{html.escape(label)}</strong><span>{html.escape(value)}</span></li>")
        if detail_rows:
            return f"""<div class="notice success">
              <p>{html.escape(text)}</p>
              <p>복구가 필요하면 아래 정보를 관리자에게 보내주세요.</p>
              <ul class="notice-detail-list">{''.join(detail_rows)}</ul>
            </div>"""
    return f"<div class='notice success'>{html.escape(text)}</div>"


def confirm_onsubmit(message: str) -> str:
    payload = json.dumps(message, ensure_ascii=False)
    return f'onsubmit="return confirm({html.escape(payload, quote=True)});"'


def archive_destination(root_path: Path, rel_path: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    normalized = normalized_rel_path(rel_path)
    destination = root_path / ".archive" / "deleted" / stamp / normalized
    candidate = destination
    counter = 1
    while candidate.exists():
        candidate = destination.with_name(f"{destination.name}-{counter}")
        counter += 1
    return candidate


def archive_root_path(personal_root: Path) -> Path:
    return personal_root / ".archive" / "deleted"


def safe_archive_rel_path(rel_path: str) -> str | None:
    normalized = normalized_rel_path(rel_path)
    parts = [part for part in normalized.split("/") if part]
    if len(parts) < 4 or parts[0] != ".archive" or parts[1] != "deleted":
        return None
    if any(part in {"", ".", ".."} or "/" in part or "\\" in part or "\x00" in part for part in parts):
        return None
    original = Path(*parts[3:])
    if not safe_name(original):
        return None
    return "/".join(parts)


def restore_rel_from_archive_rel(archive_rel: str) -> str:
    parts = [part for part in normalized_rel_path(archive_rel).split("/") if part]
    return "/".join(parts[3:])


def cleanup_empty_archive_dirs(path: Path, archive_root: Path) -> None:
    current = path
    try:
        archive_root = archive_root.resolve()
    except OSError:
        return
    while True:
        try:
            current = current.resolve()
        except OSError:
            return
        if current == archive_root or archive_root not in current.parents:
            return
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def action_label(action: str) -> str:
    return AUDIT_ACTION_LABELS.get(action, action)


def audit_time_label(raw: str) -> str:
    if not raw:
        return "-"
    return raw.replace("T", " ")[:16]


def event_primary_path(event: dict) -> str:
    return str(event.get("after_path") or event.get("path") or event.get("before_path") or "")


def event_matches_target(event: dict, target: Path) -> bool:
    try:
        target_s = str(target.resolve())
    except OSError:
        return False
    for key in ("path_abs", "before_path_abs", "after_path_abs", "archive_path_abs"):
        if event.get(key) == target_s:
            return True
    return False


def file_status_key(root: dict, rel_path: str, events: list[dict]) -> str:
    normalized = normalized_rel_path(rel_path)
    parts = [part for part in normalized.split("/") if part]
    root_id = root.get("id")
    for event in events:
        action = event.get("action")
        if action == "status_update":
            status_key = str(event.get("file_status") or "")
            if status_key in FILE_STATUS_LABELS:
                return status_key
    if root_id == "team_shared" or (root_id == "all" and len(parts) >= 2 and parts[1] == "shared"):
        return "shared"
    for event in events:
        action = event.get("action")
        if action == "upload":
            return "new"
        if action == "rename":
            return "organized"
        if action == "move_to_shared":
            return "shared"
    return "active"


TYPE_FILTERS = [
    ("", "전체"),
    ("folder", "폴더"),
    ("doc", "문서"),
    ("pdf", "PDF"),
    ("sheet", "표"),
    ("slide", "발표"),
    ("code", "코드"),
    ("image", "이미지"),
    ("other", "기타"),
]


SORT_OPTIONS = [
    ("name", "이름순"),
    ("modified", "최신순"),
    ("size", "크기순"),
    ("type", "종류순"),
]

def normalize_date_filter(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""
    try:
        dt.date.fromisoformat(candidate)
    except ValueError:
        return ""
    return candidate


def date_filter_bounds(date_from: str, date_to: str) -> tuple[float | None, float | None]:
    start_ts = None
    end_ts = None
    if date_from:
        start = dt.datetime.combine(dt.date.fromisoformat(date_from), dt.time.min)
        start_ts = start.timestamp()
    if date_to:
        end = dt.datetime.combine(dt.date.fromisoformat(date_to), dt.time.max)
        end_ts = end.timestamp()
    return start_ts, end_ts


def listing_state_params(
    q: str = "",
    type_filter: str = "",
    status_filter: str = "",
    date_from: str = "",
    date_to: str = "",
    sort_key: str = "name",
) -> dict[str, str]:
    params = {
        "q": q,
        "type": type_filter,
        "status": status_filter,
        "date_from": date_from,
        "date_to": date_to,
    }
    if sort_key != "name":
        params["sort"] = sort_key
    return params


def file_type_info(path: Path, is_dir: bool) -> tuple[str, str, str]:
    if is_dir:
        return "folder", "폴더", "DIR"
    suffix = path.suffix.lower()
    if suffix in {".doc", ".docx", ".odt", ".rtf"}:
        return "doc", "문서", "DOC"
    if suffix == ".pdf":
        return "pdf", "PDF", "PDF"
    if suffix in {".xls", ".xlsx", ".ods", ".csv", ".tsv"}:
        return "sheet", "표", "XLS"
    if suffix in {".ppt", ".pptx", ".odp"}:
        return "slide", "발표", "PPT"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico"}:
        return "image", "이미지", "IMG"
    if suffix in {".md", ".markdown", ".txt"}:
        return "doc", "문서", suffix.lstrip(".").upper()[:4] or "TXT"
    if suffix in TEXT_EXTENSIONS or suffix in {".ipynb", ".sql"}:
        return "code", "코드", suffix.lstrip(".").upper()[:4] or "TXT"
    if suffix in {".zip", ".7z", ".rar", ".tar", ".gz"}:
        return "other", "압축", "ZIP"
    return "other", suffix.lstrip(".").upper() or "파일", "FILE"


def root_type_info(root: dict) -> tuple[str, str, str]:
    root_id = str(root.get("id", ""))
    label = str(root.get("label", "")).lower()
    if root_id == "all":
        return "scope-admin", "관리자 전체", "모든 팀과 개인 작업공간을 확인하는 관리자 공간입니다."
    if root_id == "team_shared" or "공유" in label:
        return "scope-shared", "팀 공유", "개인 작업공간에서 공유로 이동한 산출물을 팀원이 함께 확인하는 공간입니다."
    if root_id == "personal" or "개인" in label:
        return "scope-personal", "개인 작업공간", "봇과 사용자가 만든 산출물이 먼저 모이는 개인 작업공간입니다."
    return "scope-default", "작업공간", "파일과 산출물을 확인하는 작업공간입니다."


def root_badge_html(root: dict) -> str:
    class_name, label, description = root_type_info(root)
    return f'<span class="root-badge {class_name}" title="{html.escape(description, quote=True)}">{html.escape(label)}</span>'


def summarize_workspace(path: Path, max_files: int = MAX_SCAN_FILES, exclude_selftests: bool = False) -> dict:
    summary = {
        "exists": path.exists() and path.is_dir(),
        "files": 0,
        "dirs": 0,
        "bytes": 0,
        "last_mtime": 0.0,
        "truncated": False,
    }
    if not summary["exists"]:
        return summary

    scanned = 0
    root_path = path.resolve()
    for current, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if safe_name(Path(d)) and d not in HIDDEN_DIR_NAMES]
        summary["dirs"] += len(dirs)
        for filename in files:
            file_path = Path(current) / filename
            try:
                rel = file_path.relative_to(root_path)
                if exclude_selftests and is_selftest_path(rel.as_posix()):
                    continue
                if not safe_name(rel):
                    continue
                stat = file_path.stat()
            except OSError:
                continue
            scanned += 1
            if scanned > max_files:
                summary["truncated"] = True
                return summary
            summary["files"] += 1
            summary["bytes"] += stat.st_size
            summary["last_mtime"] = max(summary["last_mtime"], stat.st_mtime)
    return summary


def summary_last_activity(summary: dict) -> str:
    if not summary.get("exists"):
        return "폴더 없음"
    last_mtime = float(summary.get("last_mtime", 0) or 0)
    if last_mtime <= 0:
        return "활동 없음"
    return dt.datetime.fromtimestamp(last_mtime).strftime("%Y-%m-%d %H:%M")


def user_team_key(user: dict) -> str:
    for root in user.get("roots", []):
        if root.get("id") == "personal":
            path = Path(root.get("path", ""))
            if len(path.parts) >= 2:
                return path.parent.name
    for root in user.get("roots", []):
        path = Path(root.get("path", ""))
        if len(path.parts) >= 2:
            return path.parent.name
    return "unknown"


def root_by_id(user: dict, root_id: str) -> dict | None:
    return next((root for root in user.get("roots", []) if root.get("id") == root_id), None)


def breadcrumb_html(root: dict, rel_path: str, root_id: str, current_name: str = "") -> str:
    root_url = portal_url("/browse", {"root": root_id})
    pieces = [
        '<a href="/">홈</a>',
        '<span class="crumb-separator">/</span>',
    ]
    clean_rel = "" if rel_path in ("", ".") else rel_path.strip("/")
    parts = [part for part in clean_rel.split("/") if part]
    if not parts and not current_name:
        pieces.append(f'<span class="current">{html.escape(root["label"])}</span>')
    else:
        pieces.append(f'<a href="{html.escape(root_url, quote=True)}">{html.escape(root["label"])}</a>')

    accumulated = []
    for index, part in enumerate(parts):
        accumulated.append(part)
        is_last_folder = index == len(parts) - 1 and not current_name
        pieces.append('<span class="crumb-separator">/</span>')
        if is_last_folder:
            pieces.append(f'<span class="current">{html.escape(part)}</span>')
        else:
            url = portal_url("/browse", {"root": root_id, "path": "/".join(accumulated)})
            pieces.append(f'<a href="{html.escape(url, quote=True)}">{html.escape(part)}</a>')

    if current_name:
        pieces.append('<span class="crumb-separator">/</span>')
        pieces.append(f'<span class="current">{html.escape(current_name)}</span>')

    return '<nav class="breadcrumbs" aria-label="경로">' + "".join(pieces) + "</nav>"

def path_tree_size(path: Path) -> int:
    try:
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0
    total = 0
    for current, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(current) / name).stat().st_size
            except OSError:
                continue
    return total


def cache_dir_summary(path: Path) -> dict:
    files = 0
    dirs = 0
    total = 0
    if not path.exists():
        return {"files": 0, "dirs": 0, "bytes": 0}
    for current, dirnames, filenames in os.walk(path):
        dirs += len(dirnames)
        files += len(filenames)
        for name in filenames:
            try:
                total += (Path(current) / name).stat().st_size
            except OSError:
                continue
    return {"files": files, "dirs": dirs, "bytes": total}


def cleanup_cache_dir(path: Path, retention_days: int, max_bytes: int) -> dict:
    path.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - retention_days * 24 * 60 * 60
    removed = 0
    reclaimed = 0

    for item in list(path.iterdir()):
        try:
            stat = item.stat()
        except OSError:
            continue
        size = path_tree_size(item)
        if stat.st_mtime >= cutoff:
            continue
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            removed += 1
            reclaimed += size
        except OSError:
            continue

    entries = []
    total = 0
    for item in path.iterdir():
        try:
            stat = item.stat()
        except OSError:
            continue
        size = path_tree_size(item)
        total += size
        entries.append((stat.st_mtime, size, item))
    for _mtime, size, item in sorted(entries):
        if total <= max_bytes:
            break
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            removed += 1
            reclaimed += size
            total -= size
        except OSError:
            continue

    summary = cache_dir_summary(path)
    return {"removed": removed, "reclaimed": reclaimed, **summary}


def rotate_audit_log() -> Path | None:
    try:
        if not AUDIT_LOG_PATH.exists() or AUDIT_LOG_PATH.stat().st_size <= AUDIT_ROTATE_BYTES:
            return None
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        rotated = AUDIT_LOG_PATH.with_name(f"audit_events-{stamp}.jsonl")
        AUDIT_LOG_PATH.replace(rotated)
        return rotated
    except OSError as exc:
        print(f"audit log rotation failed: {exc}", flush=True)
        return None
