#!/usr/bin/env python3
import cgi
import datetime as dt
import hmac
import json
import os
import posixpath
import re
import secrets
import shutil
import tempfile
import time
import urllib.parse
from pathlib import Path

from workroom.core.scopes import (
    SORT_OPTIONS,
    TYPE_FILTERS,
    archive_destination,
    archive_root_path,
    action_label,
    audit_time_label,
    can_archive_personal_path,
    can_upload_to_folder,
    cleanup_empty_archive_dirs,
    date_filter_bounds,
    event_primary_path,
    file_status_key,
    file_type_info,
    format_mtime,
    format_size,
    hash_password,
    is_private_client,
    is_selftest_path,
    listing_state_params,
    normalize_date_filter,
    normalized_rel_path,
    operational_events,
    path_tree_size,
    root_type_info,
    root_by_id,
    restore_rel_from_archive_rel,
    safe_archive_rel_path,
    safe_entry_name,
    safe_name,
    safe_upload_name,
    search_key,
    shared_move_plan,
    summarize_workspace,
    summary_last_activity,
    unique_peer_path,
    user_team_key,
    verify_password,
)
from workroom.agent.jobs import cancel_job, create_job, hide_session, jobs_for_user, role_options
from workroom.core.settings import (
    AUDIT_ACTION_LABELS,
    AUDIT_LOG_PATH,
    FILE_STATUS_LABELS,
    HIDDEN_DIR_NAMES,
    MAX_ADMIN_FILE_SEARCH_RESULTS,
    MAX_ARCHIVE_DISPLAY,
    MAX_UPLOAD_BYTES,
    PERSONAL_UPLOAD_DIRS,
    SHARED_MOVE_TARGETS,
)
from workroom.core.urls import app_file_url, app_folder_url, portal_url

WORKFLOW_AUDIT_ACTIONS = {
    "archive",
    "archive_bulk_purged",
    "archive_purged",
    "copy_to_agent_shared",
    "copy_to_personal",
    "move_to_shared",
    "admin_audit_cleaned",
    "permission_denied",
    "portal_password_reset",
    "portal_password_changed",
    "portal_user_created",
    "portal_user_disabled",
    "portal_user_enabled",
    "preview_failed",
    "rename",
    "restore",
    "status_update",
    "upload",
}

TEAM_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")

COPY_TO_PERSONAL_TARGETS = {
    "research": "리서치",
    "dev": "개발 산출물",
    "summary": "요약/보고",
}

WORKSPACES_ROOT = Path("/home/portal/workspaces")
PORTAL_PASSWORDS_PATH = Path("/home/portal/workspaces/admin/portal_initial_passwords.txt")
PORTAL_USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,15}$")
DEFAULT_PERSONAL_DIRS = ("dev", "research", "summary")

API_CACHE_SECONDS = 5
API_CACHE_PATHS = {"/api/session", "/api/folder", "/api/admin/summary", "/api/admin/search", "/api/admin/activity"}


class PortalApiMixin:
    def send_json(self, payload: dict, status: int = 200):
        cache_key = getattr(self, "_api_cache_key", None)
        if status == 200 and cache_key:
            self.api_cache_set(cache_key, payload)
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            return

    def api_cache_key(self, path: str, query: dict, user: dict) -> tuple | None:
        if path not in API_CACHE_PATHS:
            return None
        query_key = tuple(sorted((key, tuple(values)) for key, values in query.items()))
        return (str(user.get("username", "")), path, query_key)

    def api_cache_get(self, key: tuple) -> dict | None:
        cache = getattr(self.server, "api_cache", None)
        if not isinstance(cache, dict):
            self.server.api_cache = {}
            return None
        cached = cache.get(key)
        if not cached:
            return None
        expires_at, payload = cached
        if expires_at < time.time():
            cache.pop(key, None)
            return None
        return payload

    def api_cache_set(self, key: tuple, payload: dict):
        cache = getattr(self.server, "api_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self.server.api_cache = cache
        cache[key] = (time.time() + API_CACHE_SECONDS, payload)

    def clear_api_cache(self):
        self.server.api_cache = {}

    def api_user(self) -> dict | None:
        if not is_private_client(self.peer_ip()):
            self.send_json({"error": "forbidden", "message": "internal network only"}, 403)
            return None
        user = self.current_user()
        if not user:
            self.send_json({"error": "unauthorized", "login_url": "/login"}, 401)
            return None
        return user

    def handle_api_get(self, path: str, query: dict):
        user = self.api_user()
        if not user:
            return
        cache_key = self.api_cache_key(path, query, user)
        if cache_key:
            cached = self.api_cache_get(cache_key)
            if cached is not None:
                self.send_json(cached)
                return
            self._api_cache_key = cache_key
        if path == "/api/session":
            self.api_session(user)
        elif path == "/api/folder":
            self.api_folder(user, query)
        elif path == "/api/file":
            self.api_file(user, query)
        elif path == "/api/agent/jobs":
            self.api_agent_jobs(user, query)
        elif path == "/api/admin/summary":
            self.api_admin_summary(user)
        elif path == "/api/admin/search":
            self.api_admin_search(user, query)
        elif path == "/api/admin/activity":
            self.api_admin_activity(user, query)
        elif path == "/api/admin/archive":
            self.api_admin_archive(user)
        elif path == "/api/admin/user":
            self.api_admin_user(user, query)
        else:
            self.send_json({"error": "not_found"}, 404)
        if hasattr(self, "_api_cache_key"):
            delattr(self, "_api_cache_key")

    def handle_api_post(self, path: str):
        user = self.api_user()
        if not user:
            return
        self.clear_api_cache()
        if path == "/api/upload":
            self.api_upload(user)
            return
        payload = self.read_api_json_body()
        if payload is None:
            return
        if not self.verify_api_csrf(user, str(payload.get("csrf_token") or "")):
            return
        if path == "/api/actions/status":
            self.api_action_status(user, payload)
        elif path == "/api/actions/rename":
            self.api_action_rename(user, payload)
        elif path == "/api/actions/share":
            self.api_action_share(user, payload)
        elif path == "/api/actions/agent-share":
            self.api_action_agent_share(user, payload)
        elif path == "/api/actions/copy-to-personal":
            self.api_action_copy_to_personal(user, payload)
        elif path == "/api/actions/archive":
            self.api_action_archive(user, payload)
        elif path == "/api/actions/restore":
            self.api_action_restore(user, payload)
        elif path == "/api/actions/purge-archive":
            self.api_action_purge_archive(user, payload)
        elif path == "/api/admin/archive/purge-old":
            self.api_admin_archive_purge_old(user, payload)
        elif path == "/api/admin/activity/cleanup":
            self.api_admin_activity_cleanup(user, payload)
        elif path == "/api/account/password":
            self.api_account_password(user, payload)
        elif path == "/api/admin/users/create":
            self.api_admin_user_create(user, payload)
        elif path == "/api/admin/users/reset-password":
            self.api_admin_user_reset_password(user, payload)
        elif path == "/api/admin/users/status":
            self.api_admin_user_status(user, payload)
        elif path == "/api/agent/jobs":
            self.api_agent_job_create(user, payload)
        elif path == "/api/agent/jobs/cancel":
            self.api_agent_job_cancel(user, payload)
        elif path == "/api/agent/sessions/hide":
            self.api_agent_session_hide(user, payload)
        else:
            self.send_json({"error": "not_found"}, 404)

    def read_api_json_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json({"error": "bad_request", "message": "invalid content length"}, 400)
            return None
        if length < 0:
            self.send_json({"error": "bad_request", "message": "invalid content length"}, 400)
            return None
        if length == 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json({"error": "bad_json", "message": "JSON body is required"}, 400)
            return None
        if not isinstance(payload, dict):
            self.send_json({"error": "bad_json", "message": "JSON object is required"}, 400)
            return None
        return payload

    def verify_api_csrf(self, user: dict, token: str = "") -> bool:
        payload = self.current_session() or {}
        expected = str(payload.get("csrf", ""))
        candidate = token or self.headers.get("X-CSRF-Token", "") or self.headers.get("X-Portal-CSRF", "")
        if expected and candidate and hmac.compare_digest(expected, str(candidate)):
            return True
        self.audit_event(user, "csrf_denied", status="denied", reason="bad_csrf_api")
        self.send_json({"error": "csrf_denied", "message": "refresh session and retry"}, 403)
        return False

    def api_action_error(self, user: dict, reason: str, root: dict | None, rel_path: str, target: Path | None, message: str, status: int = 403, **extra):
        self.audit_event(user, "permission_denied", root, rel_path, target, status="denied", reason=reason, **extra)
        self.send_json({"error": reason, "message": message}, status)

    def api_agent_jobs(self, user: dict, query: dict):
        try:
            limit = int(query.get("limit", ["30"])[0])
        except ValueError:
            limit = 30
        limit = max(1, min(limit, 100))
        include_all_admin = user.get("username") == "admin" and query.get("scope", [""])[0] == "all"
        self.send_json({"jobs": jobs_for_user(user, limit, include_all_admin=include_all_admin), "roles": role_options(user)})

    def api_agent_job_create(self, user: dict, payload: dict):
        try:
            job = create_job(
                user,
                str(payload.get("role") or ""),
                str(payload.get("prompt") or ""),
                str(payload.get("reference_root") or ""),
                str(payload.get("reference_path") or ""),
                str(payload.get("session_id") or ""),
                str(payload.get("session_title") or ""),
                payload.get("references"),
            )
        except PermissionError as exc:
            self.audit_event(user, "permission_denied", None, "", None, status="denied", reason="agent_job_create")
            self.send_json({"error": "agent_job_create", "message": str(exc)}, 403)
            return
        except ValueError as exc:
            self.send_json({"error": "agent_job_create", "message": str(exc)}, 400)
            return
        self.audit_event(
            user,
            "agent_job_created",
            root_by_id(user, "personal"),
            str(job.get("output_path") or ""),
            None,
            status="queued",
            reason=str(job.get("role", "")),
            agent_job_id=str(job.get("id", "")),
            agent_role=str(job.get("role", "")),
        )
        self.send_json({"ok": True, "job": job})

    def api_agent_job_cancel(self, user: dict, payload: dict):
        try:
            job = cancel_job(user, str(payload.get("job_id") or ""))
        except FileNotFoundError as exc:
            self.send_json({"error": "agent_job_cancel", "message": str(exc)}, 404)
            return
        except PermissionError as exc:
            self.audit_event(user, "permission_denied", None, "", None, status="denied", reason="agent_job_cancel")
            self.send_json({"error": "agent_job_cancel", "message": str(exc)}, 403)
            return
        except ValueError as exc:
            self.send_json({"error": "agent_job_cancel", "message": str(exc)}, 409)
            return
        self.send_json({"ok": True, "job": job})

    def api_agent_session_hide(self, user: dict, payload: dict):
        try:
            result = hide_session(user, str(payload.get("session_id") or ""))
        except FileNotFoundError as exc:
            self.send_json({"error": "agent_session_hide", "message": str(exc)}, 404)
            return
        except PermissionError as exc:
            self.audit_event(user, "permission_denied", None, "", None, status="denied", reason="agent_session_hide")
            self.send_json({"error": "agent_session_hide", "message": str(exc)}, 403)
            return
        except ValueError as exc:
            self.send_json({"error": "agent_session_hide", "message": str(exc)}, 400)
            return
        self.send_json({"ok": True, **result})

    def api_root_payload(self, root: dict) -> dict:
        class_name, label, description = root_type_info(root)
        root_id = str(root.get("id", ""))
        return {
            "id": root_id,
            "label": str(root.get("label", "")),
            "kind": class_name.replace("scope-", ""),
            "kind_label": label,
            "description": description,
            "url": app_folder_url(root_id),
        }

    def api_session(self, user: dict):
        session = self.current_session() or {}
        self.send_json(
            {
                "user": {
                    "username": user.get("username", ""),
                    "name": user.get("name", user.get("username", "")),
                    "is_admin": user.get("username") == "admin",
                    "team": user_team_key(user),
                    "must_change_password": bool(user.get("must_change_password")),
                },
                "csrf_token": str(session.get("csrf", "")),
                "roots": [self.api_root_payload(root) for root in self.portal.roots_for(user)],
            }
        )

    def api_listing_state(self, query: dict) -> dict[str, str | int]:
        type_filter = query.get("type", [""])[0].strip()
        status_filter = query.get("status", [""])[0].strip()
        sort_key = query.get("sort", ["name"])[0].strip() or "name"
        valid_filters = {key for key, _label in TYPE_FILTERS}
        valid_sorts = {key for key, _label in SORT_OPTIONS}
        try:
            limit = int(query.get("limit", ["0"])[0] or 0)
        except ValueError:
            limit = 0
        try:
            offset = int(query.get("offset", ["0"])[0] or 0)
        except ValueError:
            offset = 0
        return {
            "q": query.get("q", [""])[0].strip(),
            "type": type_filter if type_filter in valid_filters else "",
            "status": status_filter if status_filter in FILE_STATUS_LABELS else "",
            "date_from": normalize_date_filter(query.get("date_from", [""])[0]),
            "date_to": normalize_date_filter(query.get("date_to", [""])[0]),
            "sort": sort_key if sort_key in valid_sorts else "name",
            "limit": max(0, min(limit, 200)),
            "offset": max(0, offset),
        }

    def team_shared_owner_for_target(self, target: Path) -> str:
        try:
            target_s = str(target.resolve())
        except OSError:
            return ""
        owner_cache = getattr(self, "_team_shared_owner_cache", None)
        if owner_cache is None:
            owner_cache = {}
            for event in self.portal.recent_events(5000):
                if event.get("action") != "move_to_shared":
                    continue
                after_path = str(event.get("after_path_abs") or "")
                if after_path and after_path not in owner_cache:
                    owner_cache[after_path] = str(event.get("actor") or "")
            self._team_shared_owner_cache = owner_cache
        return str(owner_cache.get(target_s) or "")

    def can_archive_team_shared_file(self, user: dict, root: dict, rel_path: str, target: Path) -> bool:
        if root.get("id") != "team_shared" or not target.is_file():
            return False
        normalized = normalized_rel_path(rel_path)
        parts = [part for part in normalized.split("/") if part]
        if len(parts) < 2 or parts[0] not in SHARED_MOVE_TARGETS:
            return False
        return self.team_shared_owner_for_target(target) == str(user.get("username") or "")

    def archive_owner_root_for_item(self, user: dict, root: dict, rel_path: str, target: Path) -> tuple[dict | None, dict | None]:
        if can_archive_personal_path(root, rel_path):
            return user, root
        if self.can_archive_team_shared_file(user, root, rel_path, target):
            owner = self.portal.user(str(user.get("username") or ""))
            personal = root_by_id(owner, "personal") if owner else None
            if owner and personal:
                return owner, personal
        return None, None

    def can_archive_item(self, user: dict, root: dict, rel_path: str, target: Path) -> bool:
        _owner, archive_root = self.archive_owner_root_for_item(user, root, rel_path, target)
        return bool(archive_root)

    def api_folder_entries(self, user: dict, root: dict, folder: Path, state: dict[str, str | int]) -> tuple[list[dict], int, bool]:
        root_path = Path(root["path"]).resolve()
        try:
            folder_rel = folder.relative_to(root_path).as_posix()
        except ValueError:
            folder_rel = ""
        hide_selftest_entries = not is_selftest_path(folder_rel)
        needle = search_key(state["q"])
        date_start, date_end = date_filter_bounds(str(state["date_from"]), str(state["date_to"]))
        entries = []
        try:
            raw_entries = list(folder.iterdir())
        except OSError:
            raw_entries = []

        for entry in raw_entries:
            try:
                entry_rel = entry.relative_to(root_path)
            except ValueError:
                continue
            if self.portal.is_personal_shared_path(entry):
                continue
            if hide_selftest_entries and is_selftest_path(entry_rel.as_posix()):
                continue
            if entry.name in HIDDEN_DIR_NAMES or not safe_name(entry_rel):
                continue
            is_dir = entry.is_dir()
            type_key, type_label, type_token = file_type_info(entry, is_dir)
            if needle and needle not in search_key(entry.name):
                continue
            if state["type"] and type_key != state["type"]:
                continue
            try:
                stat = entry.stat()
                mtime = stat.st_mtime
                byte_size = 0 if is_dir else stat.st_size
            except OSError:
                mtime = 0
                byte_size = 0
            if date_start is not None and mtime < date_start:
                continue
            if date_end is not None and mtime > date_end:
                continue
            status_key = ""
            if is_dir:
                if state["status"]:
                    continue
            elif state["status"]:
                status_key = file_status_key(root, entry_rel.as_posix(), self.portal.events_for_target(entry, limit=12))
                if state["status"] and status_key != state["status"]:
                    continue
            entries.append((entry, entry_rel, type_key, type_label, type_token, mtime, byte_size, status_key))

        sort_key = str(state["sort"])
        if sort_key == "modified":
            entries.sort(key=lambda item: (not item[0].is_dir(), -item[5], search_key(item[0].name)))
        elif sort_key == "size":
            entries.sort(key=lambda item: (not item[0].is_dir(), -item[6], search_key(item[0].name)))
        elif sort_key == "type":
            entries.sort(key=lambda item: (not item[0].is_dir(), item[2], search_key(item[0].name)))
        else:
            entries.sort(key=lambda item: (not item[0].is_dir(), search_key(item[0].name)))

        total_count = len(entries)
        offset = int(state.get("offset", 0) or 0)
        limit = int(state.get("limit", 0) or 0)
        if limit:
            page_entries = entries[offset : offset + limit]
        else:
            page_entries = entries
        has_more = bool(limit and offset + len(page_entries) < total_count)

        payload = []
        for entry, entry_rel, type_key, type_label, type_token, _mtime, byte_size, status_key in page_entries:
            rel_s = entry_rel.as_posix()
            is_dir = entry.is_dir()
            if not is_dir and not status_key:
                status_key = file_status_key(root, rel_s, self.portal.events_for_target(entry, limit=12))
            if is_dir:
                open_url = app_folder_url(root["id"], rel_s)
            else:
                open_url = app_file_url(root["id"], rel_s)
            can_manage = self.can_archive_item(user, root, rel_s, entry)
            item = {
                "name": entry.name,
                "path": rel_s,
                "is_dir": is_dir,
                "kind": type_key,
                "kind_label": type_label,
                "kind_token": type_token,
                "status": status_key,
                "status_label": FILE_STATUS_LABELS.get(status_key, ""),
                "size": byte_size,
                "size_label": "-" if is_dir else format_size(byte_size),
                "modified": format_mtime(entry),
                "url": open_url,
                "download_url": portal_url("/download", {"root": root["id"], "path": rel_s}),
                "can_archive": can_manage,
                "can_share": root.get("id") == "personal" and can_manage,
                "can_agent_share": False,
                "can_copy_to_personal": root.get("id") == "team_shared",
            }
            if item["can_share"]:
                item["share_plan"] = shared_move_plan(rel_s, entry.name)
            payload.append(item)
        return payload, total_count, has_more

    def api_folder(self, user: dict, query: dict):
        root_id = query.get("root", [""])[0]
        rel_path = query.get("path", [""])[0]
        state = self.api_listing_state(query)
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if not root or not target or not target.exists() or not target.is_dir():
            self.send_json({"error": "forbidden", "message": "folder not available"}, 403)
            return
        rel = target.relative_to(Path(root["path"]).resolve()).as_posix()
        rel = "" if rel == "." else rel
        parent = ""
        if rel:
            parent = normalized_rel_path(str(Path(rel).parent).replace("\\", "/"))
            if parent == ".":
                parent = ""
        entries, entry_count, has_more = self.api_folder_entries(user, root, target, state)
        upload_targets = []
        if root.get("id") == "personal":
            for folder, label in PERSONAL_UPLOAD_DIRS.items():
                upload_targets.append(
                    {
                        "path": folder,
                        "label": label,
                        "url": app_folder_url(root["id"], folder),
                    }
                )
        workspace_summary = summarize_workspace(target, exclude_selftests=True)
        self.send_json(
            {
                "root": self.api_root_payload(root),
                "path": rel,
                "title_path": "/" + rel if rel else "/",
                "parent_url": app_folder_url(root["id"], parent) if rel else "",
                "download_url": portal_url("/download", {"root": root["id"], "path": rel}),
                "can_upload": can_upload_to_folder(root, target, rel),
                "upload_targets": upload_targets,
                "filters": state,
                "entries": entries,
                "entry_count": entry_count,
                "entry_offset": int(state.get("offset", 0) or 0),
                "entry_limit": int(state.get("limit", 0) or 0),
                "has_more": has_more,
                "summary": {
                    "files": int(workspace_summary.get("files", 0) or 0),
                    "dirs": int(workspace_summary.get("dirs", 0) or 0),
                    "bytes": int(workspace_summary.get("bytes", 0) or 0),
                    "truncated": bool(workspace_summary.get("truncated", False)),
                    "last_activity": summary_last_activity(workspace_summary),
                },
            }
        )

    def api_file(self, user: dict, query: dict):
        root_id = query.get("root", [""])[0]
        rel_path = query.get("path", [""])[0]
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if not root or not target or not target.exists() or not target.is_file():
            self.send_json({"error": "forbidden", "message": "file not available"}, 403)
            return
        stat = target.stat()
        type_key, type_label, type_token = file_type_info(target, False)
        events = self.portal.events_for_target(target, limit=8)
        status_key = file_status_key(root, rel_path, events)
        parent = normalized_rel_path(str(Path(rel_path).parent).replace("\\", "/"))
        if parent == ".":
            parent = ""
        can_manage = self.can_archive_item(user, root, rel_path, target)
        payload = {
            "root": self.api_root_payload(root),
            "path": normalized_rel_path(rel_path),
            "name": target.name,
            "kind": type_key,
            "kind_label": type_label,
            "kind_token": type_token,
            "status": status_key,
            "status_label": FILE_STATUS_LABELS.get(status_key, ""),
            "size": stat.st_size,
            "size_label": format_size(stat.st_size),
            "modified": format_mtime(target),
            "folder_url": app_folder_url(root["id"], parent),
            "view_url": app_file_url(root["id"], rel_path),
            "preview_url": portal_url("/preview", {"root": root["id"], "path": rel_path}),
            "download_url": portal_url("/download", {"root": root["id"], "path": rel_path}),
            "can_archive": can_manage,
            "can_share": root.get("id") == "personal" and can_manage,
            "can_agent_share": False,
            "can_copy_to_personal": root.get("id") == "team_shared",
            "context": self.file_context(user, root, rel_path),
            "events": [
                {
                    "time": audit_time_label(str(event.get("ts", ""))),
                    "action": str(event.get("action", "")),
                    "action_label": action_label(str(event.get("action", ""))),
                    "actor": str(event.get("actor_name") or event.get("actor") or ""),
                }
                for event in events[:5]
            ],
        }
        if payload["can_share"]:
            payload["share_plan"] = shared_move_plan(rel_path, target.name)
        self.send_json(payload)

    def api_action_copy_to_personal(self, user: dict, payload: dict):
        root_id = str(payload.get("root") or "")
        rel_path = str(payload.get("path") or "")
        target_folder = str(payload.get("target_folder") or "").strip()
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        personal = root_by_id(user, "personal")
        if (
            not root
            or not target
            or not target.exists()
            or root.get("id") != "team_shared"
            or not personal
            or target_folder not in COPY_TO_PERSONAL_TARGETS
        ):
            self.api_action_error(user, "copy_to_personal", root, rel_path, target, "item cannot be copied to personal workspace")
            return
        personal_root = Path(personal["path"]).resolve()
        destination_dir = (personal_root / target_folder).resolve()
        if personal_root not in destination_dir.parents:
            self.api_action_error(user, "copy_to_personal", root, rel_path, target, "personal destination is not allowed")
            return
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = unique_peer_path(destination_dir / target.name, target.is_dir())
        if target.is_dir():
            shutil.copytree(str(target), str(destination))
        else:
            shutil.copy2(str(target), str(destination))
        new_rel = destination.relative_to(personal_root).as_posix()
        self.audit_event(
            user,
            "copy_to_personal",
            personal,
            new_rel,
            destination,
            before_root_id=root.get("id", ""),
            before_root_label=root.get("label", ""),
            before_path=normalized_rel_path(rel_path),
            before_path_abs=target,
            after_root_id=personal.get("id", ""),
            after_root_label=personal.get("label", ""),
            target_folder=target_folder,
            target_folder_label=COPY_TO_PERSONAL_TARGETS[target_folder],
        )
        self.send_json(
            {
                "ok": True,
                "action": "copy_to_personal",
                "root": "personal",
                "path": new_rel,
                "name": destination.name,
                "url": app_file_url("personal", new_rel, {"msg": "copied"}) if destination.is_file() else app_folder_url("personal", new_rel, {"msg": "copied"}),
            }
        )

    def api_action_agent_share(self, user: dict, payload: dict):
        self.send_json(
            {
                "error": "copy_to_agent_shared",
                "message": "개인 shared 폴더는 더 이상 봇 참고자료 흐름에 사용하지 않습니다. 봇 요청 화면에서 내 산출물 또는 팀 공유 자료를 직접 선택해주세요.",
            },
            410,
        )

    def api_action_status(self, user: dict, payload: dict):
        root_id = str(payload.get("root") or "")
        rel_path = str(payload.get("path") or "")
        status_key = str(payload.get("file_status") or "")
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if (
            not root
            or not target
            or not target.exists()
            or not target.is_file()
            or status_key not in FILE_STATUS_LABELS
        ):
            self.api_action_error(
                user,
                "set_file_status",
                root,
                rel_path,
                target,
                "file status cannot be changed",
                requested_status=status_key,
            )
            return
        self.audit_event(
            user,
            "status_update",
            root,
            rel_path,
            target,
            file_status=status_key,
            file_status_label=FILE_STATUS_LABELS[status_key],
        )
        self.send_json(
            {
                "ok": True,
                "action": "status_update",
                "root": root_id,
                "path": normalized_rel_path(rel_path),
                "status": status_key,
                "status_label": FILE_STATUS_LABELS[status_key],
                "view_url": app_file_url(root_id, rel_path, {"msg": "status_updated"}),
            }
        )

    def api_action_rename(self, user: dict, payload: dict):
        root_id = str(payload.get("root") or "")
        rel_path = str(payload.get("path") or "")
        new_name = str(payload.get("new_name") or "").strip()
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if (
            not root
            or not target
            or not target.exists()
            or not can_archive_personal_path(root, rel_path)
            or not safe_entry_name(new_name)
        ):
            self.api_action_error(user, "rename_item", root, rel_path, target, "item cannot be renamed")
            return
        destination = (target.parent / new_name).resolve()
        root_path = Path(root["path"]).resolve()
        if root_path not in destination.parents or destination.exists() or not safe_name(destination.relative_to(root_path)):
            self.api_action_error(user, "rename_conflict", root, rel_path, target, "name already exists or destination is not allowed", 409)
            return
        was_file = target.is_file()
        target.rename(destination)
        new_rel = destination.relative_to(root_path).as_posix()
        self.audit_event(
            user,
            "rename",
            root,
            new_rel,
            destination,
            before_path=normalized_rel_path(rel_path),
            before_path_abs=target,
            after_path=new_rel,
            after_path_abs=destination,
        )
        self.send_json(
            {
                "ok": True,
                "action": "rename",
                "root": root_id,
                "path": new_rel,
                "name": destination.name,
                "url": app_file_url(root_id, new_rel, {"msg": "renamed"}) if was_file else app_folder_url(root_id, new_rel, {"msg": "renamed"}),
            }
        )

    def api_action_share(self, user: dict, payload: dict):
        root_id = str(payload.get("root") or "")
        rel_path = str(payload.get("path") or "")
        shared_target = str(payload.get("shared_target") or "").strip()
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        shared_root = self.portal.root_for(user, "team_shared")
        if (
            not root
            or not target
            or not target.exists()
            or root.get("id") != "personal"
            or not can_archive_personal_path(root, rel_path)
            or shared_target not in SHARED_MOVE_TARGETS
            or not shared_root
        ):
            self.api_action_error(user, "move_to_shared", root, rel_path, target, "item cannot be moved to team shared")
            return
        shared_root_path = Path(shared_root["path"]).resolve()
        destination_dir = (shared_root_path / shared_target).resolve()
        if shared_root_path != destination_dir and shared_root_path not in destination_dir.parents:
            self.api_action_error(user, "move_target", root, rel_path, target, "shared destination is not allowed")
            return
        destination_dir.mkdir(parents=True, exist_ok=True)
        was_file = target.is_file()
        destination = unique_peer_path(destination_dir / target.name, target.is_dir())
        shutil.move(str(target), str(destination))
        new_rel = destination.relative_to(shared_root_path).as_posix()
        self.audit_event(
            user,
            "move_to_shared",
            shared_root,
            new_rel,
            destination,
            before_root_id=root.get("id", ""),
            before_root_label=root.get("label", ""),
            before_path=normalized_rel_path(rel_path),
            before_path_abs=target,
            after_root_id=shared_root.get("id", ""),
            after_root_label=shared_root.get("label", ""),
            after_path=new_rel,
            after_path_abs=destination,
        )
        self.send_json(
            {
                "ok": True,
                "action": "move_to_shared",
                "root": "team_shared",
                "path": new_rel,
                "name": destination.name,
                "url": app_file_url("team_shared", new_rel, {"msg": "shared"}) if was_file else app_folder_url("team_shared", new_rel, {"msg": "shared"}),
            }
        )

    def api_action_archive(self, user: dict, payload: dict):
        root_id = str(payload.get("root") or "")
        rel_path = str(payload.get("path") or "")
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if not root or not target or not target.exists():
            self.api_action_error(user, "archive_delete", root, rel_path, target, "item cannot be archived")
            return
        owner, archive_root = self.archive_owner_root_for_item(user, root, rel_path, target)
        if not owner or not archive_root:
            self.api_action_error(user, "archive_delete", root, rel_path, target, "item cannot be archived")
            return
        archive_root_path = Path(archive_root["path"]).resolve()
        destination = archive_destination(archive_root_path, rel_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(destination))
        archive_rel = destination.relative_to(archive_root_path).as_posix()
        self.audit_event(
            user,
            "archive",
            root,
            rel_path,
            target,
            owner=owner["username"],
            owner_name=owner.get("name", owner["username"]),
            archive_owner=owner["username"],
            archive_root_id=archive_root.get("id", ""),
            archive_root_label=archive_root.get("label", ""),
            before_root_id=root.get("id", ""),
            before_root_label=root.get("label", ""),
            before_path=normalized_rel_path(rel_path),
            before_path_abs=target,
            archive_path=archive_rel,
            archive_path_abs=destination,
        )
        parent = posixpath.dirname(normalized_rel_path(rel_path))
        parent_path = "" if parent in ("", ".") else parent
        self.send_json(
            {
                "ok": True,
                "action": "archive",
                "root": root_id,
                "path": normalized_rel_path(rel_path),
                "name": target.name,
                "archive_path": archive_rel,
                "archived_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                "folder_url": app_folder_url(root_id, parent_path, {"msg": "archived"}),
            }
        )

    def api_action_restore(self, user: dict, payload: dict):
        if user.get("username") != "admin":
            self.send_json({"error": "forbidden", "message": "admin only"}, 403)
            return
        owner_name = str(payload.get("owner") or "").strip()
        archive_rel_raw = str(payload.get("archive_path") or "").strip()
        owner = self.portal.user(owner_name)
        archive_rel = safe_archive_rel_path(archive_rel_raw)
        personal = root_by_id(owner, "personal") if owner else None
        if not owner or not archive_rel or not personal:
            self.audit_event(user, "permission_denied", None, archive_rel_raw, None, status="denied", reason="restore_archive_invalid")
            self.send_json({"error": "restore_archive_invalid", "message": "archive item cannot be restored"}, 400)
            return
        personal_root = Path(personal["path"]).resolve()
        archive_root = archive_root_path(personal_root).resolve()
        archive_target = (personal_root / archive_rel).resolve()
        if not archive_target.exists() or (archive_root != archive_target and archive_root not in archive_target.parents):
            self.audit_event(user, "permission_denied", personal, archive_rel, archive_target, status="denied", reason="restore_archive_missing")
            self.send_json({"error": "restore_archive_missing", "message": "archive item was not found"}, 404)
            return
        restore_rel = restore_rel_from_archive_rel(archive_rel)
        restore_path = (personal_root / restore_rel).resolve()
        if personal_root not in restore_path.parents or not safe_name(restore_path.relative_to(personal_root)):
            self.audit_event(user, "permission_denied", personal, archive_rel, archive_target, status="denied", reason="restore_destination")
            self.send_json({"error": "restore_destination", "message": "restore destination is not allowed"}, 403)
            return
        restore_path.parent.mkdir(parents=True, exist_ok=True)
        destination = unique_peer_path(restore_path, archive_target.is_dir())
        shutil.move(str(archive_target), str(destination))
        cleanup_empty_archive_dirs(archive_target.parent, archive_root)
        restored_rel = destination.relative_to(personal_root).as_posix()
        self.audit_event(
            user,
            "restore",
            personal,
            restored_rel,
            destination,
            owner=owner["username"],
            owner_name=owner.get("name", owner["username"]),
            before_path=archive_rel,
            before_path_abs=archive_target,
            after_path=restored_rel,
            after_path_abs=destination,
        )
        admin_root = self.admin_root(user)
        admin_rel = ""
        if admin_root:
            try:
                admin_rel = destination.relative_to(Path(admin_root["path"]).resolve()).as_posix()
            except ValueError:
                admin_rel = ""
        self.send_json(
            {
                "ok": True,
                "action": "restore",
                "owner": owner["username"],
                "path": restored_rel,
                "name": destination.name,
                "view_url": app_file_url("all", admin_rel) if admin_rel else "",
            }
        )

    def api_action_purge_archive(self, user: dict, payload: dict):
        if user.get("username") != "admin":
            self.audit_event(user, "permission_denied", None, "", None, status="denied", reason="purge_archive_admin_only")
            self.send_json({"error": "forbidden", "message": "admin only"}, 403)
            return
        owner_name = str(payload.get("owner") or "").strip()
        archive_rel_raw = str(payload.get("archive_path") or "").strip()
        owner = self.portal.user(owner_name)
        archive_rel = safe_archive_rel_path(archive_rel_raw)
        personal = root_by_id(owner, "personal") if owner else None
        if not owner or not archive_rel or not personal:
            self.audit_event(user, "permission_denied", None, archive_rel_raw, None, status="denied", reason="purge_archive_invalid")
            self.send_json({"error": "purge_archive_invalid", "message": "archive item cannot be deleted"}, 400)
            return
        personal_root = Path(personal["path"]).resolve()
        archive_root = archive_root_path(personal_root).resolve()
        archive_target = (personal_root / archive_rel).resolve()
        if not archive_target.exists() or (archive_root != archive_target and archive_root not in archive_target.parents):
            self.audit_event(user, "permission_denied", personal, archive_rel, archive_target, status="denied", reason="purge_archive_missing")
            self.send_json({"error": "purge_archive_missing", "message": "archive item was not found"}, 404)
            return
        if archive_root != archive_target and archive_root not in archive_target.parents:
            self.audit_event(user, "permission_denied", personal, archive_rel, archive_target, status="denied", reason="purge_archive_outside")
            self.send_json({"error": "purge_archive_denied", "message": "archive item is outside archive root"}, 403)
            return

        target_name = archive_target.name
        target_size = path_tree_size(archive_target)
        if archive_target.is_dir():
            shutil.rmtree(archive_target)
        else:
            archive_target.unlink()
        cleanup_empty_archive_dirs(archive_target.parent, archive_root)
        self.audit_event(
            user,
            "archive_purged",
            personal,
            archive_rel,
            archive_target,
            owner=owner["username"],
            owner_name=owner.get("name", owner["username"]),
            status="ok",
            reason="admin_permanent_delete",
            size=target_size,
        )
        self.send_json(
            {
                "ok": True,
                "action": "purge_archive",
                "owner": owner["username"],
                "archive_path": archive_rel,
                "name": target_name,
                "size": target_size,
            }
        )

    def api_upload(self, user: dict):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self.send_json({"error": "bad_request", "message": "file body is required"}, 400)
            return
        if length > MAX_UPLOAD_BYTES:
            self.send_json({"error": "upload_too_large", "message": f"max upload size is {format_size(MAX_UPLOAD_BYTES)}"}, 413)
            return
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            self.send_json({"error": "bad_request", "message": "multipart/form-data is required"}, 400)
            return
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(length),
            },
        )
        if not self.verify_api_csrf(user, form.getfirst("csrf_token", "")):
            return
        root_id = form.getfirst("root", "")
        rel_path = form.getfirst("path", "")
        root, folder = self.portal.resolve_path(user, root_id, rel_path)
        if not root or not folder or not can_upload_to_folder(root, folder, rel_path):
            reason = "upload_folder_scope" if root and root.get("id") == "personal" else "upload_file"
            self.api_action_error(user, reason, root, rel_path, folder, "upload location is not allowed")
            return
        if "file" not in form:
            self.send_json({"error": "bad_request", "message": "file field is required"}, 400)
            return
        upload_item = form["file"]
        if isinstance(upload_item, list):
            upload_item = upload_item[0]
        filename = upload_item.filename or ""
        if not filename or filename != Path(filename).name or not safe_upload_name(filename):
            self.api_action_error(user, "unsafe_upload_name", root, rel_path, folder, "file name is not allowed", filename=filename)
            return

        root_path = Path(root["path"]).resolve()
        destination = unique_peer_path((folder / filename).resolve(), is_dir=False)
        if root_path not in destination.parents or not safe_name(destination.relative_to(root_path)):
            self.api_action_error(user, "upload_destination", root, rel_path, folder, "upload destination is not allowed", filename=filename)
            return

        fd, tmp_name = tempfile.mkstemp(prefix="portal-upload-", dir=str(folder))
        tmp_path = Path(tmp_name)
        os.close(fd)
        try:
            written = 0
            with tmp_path.open("wb") as out:
                while True:
                    chunk = upload_item.file.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise ValueError("upload too large")
                    out.write(chunk)
            shutil.move(str(tmp_path), str(destination))
        except ValueError:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            self.send_json({"error": "upload_too_large", "message": f"max upload size is {format_size(MAX_UPLOAD_BYTES)}"}, 413)
            return
        except OSError as exc:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            self.send_json({"error": "upload_failed", "message": str(exc)}, 500)
            return

        new_rel = destination.relative_to(root_path).as_posix()
        self.audit_event(
            user,
            "upload",
            root,
            new_rel,
            destination,
            after_path=new_rel,
            after_path_abs=destination,
            file_size=destination.stat().st_size,
        )
        self.send_json(
            {
                "ok": True,
                "action": "upload",
                "root": root_id,
                "path": new_rel,
                "name": destination.name,
                "size": destination.stat().st_size,
                "size_label": format_size(destination.stat().st_size),
                "view_url": app_file_url(root_id, new_rel, {"msg": "uploaded"}),
            },
            201,
        )

    def write_portal_config(self) -> None:
        self.portal.config_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.portal.config_path.parent, delete=False) as tmp:
            tmp.write(json.dumps(self.portal.config, ensure_ascii=False, indent=2) + "\n")
            tmp_path = Path(tmp.name)
        tmp_path.chmod(0o600)
        tmp_path.replace(self.portal.config_path)

    def update_portal_passwords_file(self, username: str, name: str, password: str) -> None:
        lines = []
        replaced = False
        if PORTAL_PASSWORDS_PATH.exists():
            lines = PORTAL_PASSWORDS_PATH.read_text(encoding="utf-8").splitlines()
        if not lines:
            lines = [
                "Workroom Portal Portal initial passwords",
                "Change these after rollout if needed.",
                "",
            ]
        updated = []
        for line in lines:
            parts = line.split("\t")
            if len(parts) == 3 and parts[0] == username:
                updated.append(f"{username}\t{name}\t{password}")
                replaced = True
            else:
                updated.append(line)
        if not replaced:
            if updated and updated[-1].strip():
                updated.append("")
            updated.append(f"{username}\t{name}\t{password}")
        PORTAL_PASSWORDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=PORTAL_PASSWORDS_PATH.parent, delete=False) as tmp:
            tmp.write("\n".join(updated).rstrip() + "\n")
            tmp_path = Path(tmp.name)
        tmp_path.chmod(0o600)
        tmp_path.replace(PORTAL_PASSWORDS_PATH)

    def portal_password_record(self, username: str) -> dict:
        if not PORTAL_PASSWORDS_PATH.exists():
            return {}
        try:
            lines = PORTAL_PASSWORDS_PATH.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        for line in lines:
            parts = line.split("\t")
            if len(parts) == 3 and parts[0] == username:
                return {"username": parts[0], "name": parts[1], "password": parts[2]}
        return {}

    def admin_team_options(self) -> list[str]:
        teams = set()
        for member in self.portal.all_users():
            if member.get("username") == "admin":
                continue
            team = user_team_key(member)
            if team and team != "unknown":
                teams.add(team)
        return sorted(teams)

    def admin_user_option_payload(self, member: dict) -> dict:
        return {
            "username": member.get("username", ""),
            "name": member.get("name", member.get("username", "")),
            "team": user_team_key(member),
            "disabled": bool(member.get("disabled")),
        }

    def api_admin_user_create(self, user: dict, payload: dict):
        if user.get("username") != "admin":
            self.send_json({"error": "forbidden", "message": "admin only"}, 403)
            return
        username = str(payload.get("username") or "").strip().lower()
        name = str(payload.get("name") or "").strip()
        team = str(payload.get("team") or "").strip().lower()
        if not PORTAL_USERNAME_RE.match(username):
            self.send_json({"error": "invalid_username", "message": "아이디는 소문자 영문으로 시작하고 소문자/숫자/_만 2~16자로 입력하세요."}, 400)
            return
        if username in {"admin", "server", "portal"}:
            self.send_json({"error": "reserved_username", "message": "예약된 아이디는 사용할 수 없습니다."}, 400)
            return
        if not name:
            self.send_json({"error": "invalid_name", "message": "이름을 입력하세요."}, 400)
            return
        if team in {"admin", "server", "portal"} or not TEAM_KEY_RE.match(team):
            self.send_json({"error": "invalid_team", "message": "팀명은 소문자 영문으로 시작하고 소문자/숫자/_만 2~32자로 입력하세요."}, 400)
            return

        personal_root = (WORKSPACES_ROOT / team / username).resolve()
        team_shared = (WORKSPACES_ROOT / team / "shared").resolve()
        if WORKSPACES_ROOT.resolve() not in personal_root.parents:
            self.send_json({"error": "invalid_workspace", "message": "개인 작업공간 경로가 허용되지 않습니다."}, 400)
            return

        password = secrets.token_urlsafe(9)
        with self.portal.config_lock:
            if username in self.portal.config.get("users", {}):
                self.send_json({"error": "user_exists", "message": "이미 있는 아이디입니다."}, 409)
                return
            personal_root.mkdir(parents=True, exist_ok=True)
            team_shared.mkdir(parents=True, exist_ok=True)
            for folder_name in DEFAULT_PERSONAL_DIRS:
                (personal_root / folder_name).mkdir(parents=True, exist_ok=True)
            self.portal.config.setdefault("users", {})[username] = {
                "name": name,
                "password_hash": hash_password(password),
                "must_change_password": True,
                "password_issued_at": dt.datetime.now().isoformat(timespec="seconds"),
                "roots": [
                    {"id": "personal", "label": f"{name} 개인 작업공간", "path": str(personal_root)},
                    {"id": "team_shared", "label": f"{team} 팀 공유", "path": str(team_shared)},
                ],
            }
            self.write_portal_config()
            self.update_portal_passwords_file(username, name, password)

        created_user = self.portal.user(username) or {"username": username, "name": name}
        self.audit_event(user, "portal_user_created", status="ok", owner=username, owner_name=name, team=team, reason="admin_created_user")
        self.send_json(
            {
                "ok": True,
                "action": "portal_user_created",
                "user": self.admin_user_option_payload(created_user),
                "password": password,
            },
            201,
        )

    def api_admin_user_reset_password(self, user: dict, payload: dict):
        if user.get("username") != "admin":
            self.send_json({"error": "forbidden", "message": "admin only"}, 403)
            return
        username = str(payload.get("username") or "").strip()
        if username == "admin":
            self.send_json({"error": "protected_user", "message": "관리자 계정은 이 화면에서 초기화하지 않습니다."}, 403)
            return
        with self.portal.config_lock:
            target = self.portal.config.get("users", {}).get(username)
            if not target:
                self.send_json({"error": "not_found", "message": "사용자를 찾을 수 없습니다."}, 404)
                return
            password = secrets.token_urlsafe(9)
            name = str(target.get("name") or username)
            target["password_hash"] = hash_password(password)
            target["must_change_password"] = True
            target["password_issued_at"] = dt.datetime.now().isoformat(timespec="seconds")
            target.pop("password_changed_at", None)
            self.write_portal_config()
            self.update_portal_passwords_file(username, name, password)
        self.audit_event(user, "portal_password_reset", status="ok", owner=username, owner_name=name, reason="admin_reset_password")
        self.send_json({"ok": True, "action": "portal_password_reset", "username": username, "password": password})

    def api_account_password(self, user: dict, payload: dict):
        username = str(user.get("username") or "").strip()
        current_password = str(payload.get("current_password") or "")
        new_password = str(payload.get("new_password") or "")
        confirm_password = str(payload.get("confirm_password") or "")
        if len(new_password) < 10:
            self.send_json({"error": "weak_password", "message": "새 비밀번호는 10자 이상으로 입력하세요."}, 400)
            return
        if new_password != confirm_password:
            self.send_json({"error": "password_mismatch", "message": "새 비밀번호 확인이 일치하지 않습니다."}, 400)
            return
        with self.portal.config_lock:
            target = self.portal.config.get("users", {}).get(username)
            if not target:
                self.send_json({"error": "not_found", "message": "사용자를 찾을 수 없습니다."}, 404)
                return
            stored_hash = str(target.get("password_hash") or "")
            if not verify_password(current_password, stored_hash):
                self.send_json({"error": "bad_password", "message": "현재 비밀번호가 맞지 않습니다."}, 403)
                return
            if verify_password(new_password, stored_hash):
                self.send_json({"error": "same_password", "message": "현재 비밀번호와 다른 새 비밀번호를 입력하세요."}, 400)
                return
            target["password_hash"] = hash_password(new_password)
            target.pop("must_change_password", None)
            target["password_changed_at"] = dt.datetime.now().isoformat(timespec="seconds")
            self.write_portal_config()
        self.audit_event(user, "portal_password_changed", status="ok", owner=username, owner_name=str(user.get("name") or username))
        self.send_json({"ok": True, "action": "portal_password_changed"})

    def api_admin_user_status(self, user: dict, payload: dict):
        if user.get("username") != "admin":
            self.send_json({"error": "forbidden", "message": "admin only"}, 403)
            return
        username = str(payload.get("username") or "").strip()
        disabled = str(payload.get("disabled") or "") == "1"
        if username == "admin":
            self.send_json({"error": "protected_user", "message": "관리자 계정은 비활성화할 수 없습니다."}, 403)
            return
        with self.portal.config_lock:
            target = self.portal.config.get("users", {}).get(username)
            if not target:
                self.send_json({"error": "not_found", "message": "사용자를 찾을 수 없습니다."}, 404)
                return
            name = str(target.get("name") or username)
            if disabled:
                target["disabled"] = True
            else:
                target.pop("disabled", None)
            self.write_portal_config()
        action = "portal_user_disabled" if disabled else "portal_user_enabled"
        self.audit_event(user, action, status="ok", owner=username, owner_name=name, reason="admin_user_status")
        updated_user = self.portal.user(username) or {"username": username, "name": name}
        self.send_json({"ok": True, "action": action, "user": self.admin_user_option_payload(updated_user)})

    def api_admin_summary(self, user: dict):
        if user.get("username") != "admin":
            self.send_json({"error": "forbidden", "message": "admin only"}, 403)
            return
        members = [member for member in self.portal.all_users() if member.get("username") != "admin"]
        active_members = [member for member in members if not member.get("disabled")]
        disabled_members = [member for member in members if member.get("disabled")]
        teams = sorted({user_team_key(member) for member in members})
        member_summaries = []
        for member in members:
            personal = root_by_id(member, "personal")
            workspace_summary = (
                summarize_workspace(Path(personal["path"]).resolve(), exclude_selftests=True)
                if personal
                else {"files": 0, "bytes": 0, "last_mtime": 0}
            )
            bytes_used = int(workspace_summary.get("bytes", 0) or 0)
            member_summaries.append(
                {
                    "username": str(member.get("username", "")),
                    "name": str(member.get("name") or member.get("username") or ""),
                    "team": user_team_key(member),
                    "disabled": bool(member.get("disabled")),
                    "files": int(workspace_summary.get("files", 0) or 0),
                    "bytes": bytes_used,
                    "bytes_label": format_size(bytes_used),
                    "last_activity": summary_last_activity(workspace_summary),
                }
            )
        member_summaries.sort(key=lambda item: int(item["bytes"]), reverse=True)
        events = [
            event
            for event in operational_events(self.portal.recent_events(200))
            if str(event.get("action") or "") in WORKFLOW_AUDIT_ACTIONS
        ]
        self.send_json(
            {
                "member_count": len(members),
                "active_member_count": len(active_members),
                "disabled_member_count": len(disabled_members),
                "teams": teams,
                "team_count": len(teams),
                "member_summaries": member_summaries[:8],
                "recent_events": [
                    {
                        "time": audit_time_label(str(event.get("ts", ""))),
                        "action": str(event.get("action", "")),
                        "action_label": action_label(str(event.get("action", ""))),
                        "actor": str(event.get("actor_name") or event.get("actor") or ""),
                        "team": self.event_team(event),
                        "path": event_primary_path(event),
                    }
                    for event in events[:12]
                ],
                "maintenance": self.portal.maintenance_summary,
            }
        )

    def cleanup_noise_event(self, event: dict) -> bool:
        action = str(event.get("action") or "")
        actor = str(event.get("actor") or "")
        reason = str(event.get("reason") or "")
        status = str(event.get("status") or "")
        if actor.startswith("selftest-"):
            return True
        if action == "permission_denied" and reason in {
            "agent_job_cancel",
            "agent_job_create",
            "agent_session_hide",
            "archive_delete",
            "purge_archive_invalid",
            "purge_archive_missing",
            "purge_archive_outside",
            "rename_item",
            "restore_archive_invalid",
            "restore_archive_missing",
            "unsafe_upload_name",
            "upload_file",
            "upload_folder_scope",
        }:
            return True
        return False

    def api_admin_activity_cleanup(self, user: dict, payload: dict):
        if user.get("username") != "admin":
            self.send_json({"error": "forbidden", "message": "admin only"}, 403)
            return
        if not AUDIT_LOG_PATH.exists():
            self.send_json({"ok": True, "removed": 0, "kept": 0, "backup_path": ""})
            return
        raw_lines = AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines()
        timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = AUDIT_LOG_PATH.with_name(f"audit_events-cleanup-{timestamp}.jsonl")
        backup_path.write_text("\n".join(raw_lines).rstrip() + ("\n" if raw_lines else ""), encoding="utf-8")
        backup_path.chmod(0o600)

        kept_lines = []
        removed = 0
        for line in raw_lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                kept_lines.append(line)
                continue
            if self.cleanup_noise_event(event):
                removed += 1
            else:
                kept_lines.append(line)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=AUDIT_LOG_PATH.parent, delete=False) as tmp:
            tmp.write("\n".join(kept_lines).rstrip() + ("\n" if kept_lines else ""))
            tmp_path = Path(tmp.name)
        tmp_path.chmod(0o600)
        tmp_path.replace(AUDIT_LOG_PATH)
        self.audit_event(
            user,
            "admin_audit_cleaned",
            status="ok",
            reason="denied_noise_cleanup",
            removed=removed,
            backup_path=str(backup_path),
        )
        self.send_json(
            {
                "ok": True,
                "removed": removed,
                "kept": len(kept_lines) + 1,
                "backup_path": str(backup_path),
            }
        )

    def api_admin_search(self, user: dict, query: dict):
        if user.get("username") != "admin":
            self.send_json({"error": "forbidden", "message": "admin only"}, 403)
            return
        q = query.get("q", [""])[0].strip()
        type_filter = query.get("type", [""])[0].strip()
        status_filter = query.get("status", [""])[0].strip()
        date_from = normalize_date_filter(query.get("date_from", [""])[0])
        date_to = normalize_date_filter(query.get("date_to", [""])[0])
        owner_filter = query.get("owner", [""])[0].strip()
        team_filter = query.get("team", [""])[0].strip()
        scope_filter = query.get("scope", [""])[0].strip()
        sort_key = query.get("sort", ["modified"])[0].strip() or "modified"
        try:
            result_limit = int(query.get("limit", [str(MAX_ADMIN_FILE_SEARCH_RESULTS)])[0] or MAX_ADMIN_FILE_SEARCH_RESULTS)
        except ValueError:
            result_limit = MAX_ADMIN_FILE_SEARCH_RESULTS
        result_limit = max(0, min(result_limit, MAX_ADMIN_FILE_SEARCH_RESULTS))
        users = [member for member in self.portal.all_users() if member.get("username") != "admin"]
        teams = sorted({user_team_key(member) for member in users})
        valid_owners = {member["username"] for member in users}
        if owner_filter not in valid_owners:
            owner_filter = ""
        if team_filter not in teams:
            team_filter = ""
        if scope_filter not in {"개인 작업공간", "팀 공유"}:
            scope_filter = ""
        valid_filters = {key for key, _label in TYPE_FILTERS}
        if type_filter not in valid_filters:
            type_filter = ""
        if status_filter not in FILE_STATUS_LABELS:
            status_filter = ""
        valid_sorts = {key for key, _label in SORT_OPTIONS}
        if sort_key not in valid_sorts:
            sort_key = "modified"

        result = self.admin_file_search_entries(
            user,
            q,
            type_filter,
            status_filter,
            date_from,
            date_to,
            owner_filter,
            team_filter,
            scope_filter,
            sort_key,
            result_limit,
        )
        admin_root = self.admin_root(user)
        root_id = admin_root["id"] if admin_root else "all"
        entries = []
        for entry in result["entries"]:
            rel = str(entry["rel"])
            parent = posixpath.dirname(rel)
            parent_path = "" if parent == "." else parent
            entries.append(
                {
                    "name": str(entry["name"]),
                    "path": rel,
                    "owner": str(entry["owner"]),
                    "owner_username": str(entry["owner_username"]),
                    "team": str(entry["team"]),
                    "scope": str(entry["scope"]),
                    "kind": str(entry["type_key"]),
                    "kind_label": str(entry["type_label"]),
                    "kind_token": str(entry["type_token"]),
                    "status": str(entry["status_key"]),
                    "status_label": FILE_STATUS_LABELS.get(str(entry["status_key"]), ""),
                    "size": int(entry["size"]),
                    "size_label": format_size(int(entry["size"])),
                    "modified": dt.datetime.fromtimestamp(float(entry["mtime"])).strftime("%Y-%m-%d %H:%M"),
                    "view_url": app_file_url(root_id, rel),
                    "folder_url": app_folder_url(root_id, parent_path),
                    "download_url": portal_url("/download", {"root": root_id, "path": rel}),
                }
            )
        self.send_json(
            {
                "filters": {
                    "q": q,
                    "type": type_filter,
                    "status": status_filter,
                    "date_from": date_from,
                    "date_to": date_to,
                    "owner": owner_filter,
                    "team": team_filter,
                    "scope": scope_filter,
                    "sort": sort_key,
                },
                "users": [
                    self.admin_user_option_payload(member)
                    for member in users
                ],
                "teams": teams,
                "entries": entries,
                "total": int(result["total"]),
                "scanned": int(result["scanned"]),
                "truncated": bool(result["truncated"]),
                "entry_limit": int(result["entry_limit"]),
            }
        )

    def api_admin_activity(self, user: dict, query: dict):
        if user.get("username") != "admin":
            self.send_json({"error": "forbidden", "message": "admin only"}, 403)
            return
        actor = query.get("actor", [""])[0].strip()
        action = query.get("action", [""])[0].strip()
        team = query.get("team", [""])[0].strip()
        q = query.get("q", [""])[0].strip()
        include_tests = query.get("include_tests", [""])[0].strip() == "1"
        has_filters = bool(actor or action or team or q)
        events = self.portal.recent_events(1000)
        if not include_tests and not has_filters:
            events = operational_events(events)
            events = [event for event in events if str(event.get("action") or "") in WORKFLOW_AUDIT_ACTIONS]
        filtered = self.filter_events(events, query)
        users = [member for member in self.portal.all_users() if member.get("username") != "admin"]
        teams = sorted({user_team_key(member) for member in users})
        actions = sorted(AUDIT_ACTION_LABELS.keys(), key=action_label)
        summary = self.audit_summary(filtered)
        self.send_json(
            {
                "filters": {
                    "actor": actor,
                    "action": action,
                    "team": team,
                    "q": q,
                    "include_tests": "1" if include_tests else "",
                },
                "users": [
                    self.admin_user_option_payload(member)
                    for member in users
                ],
                "teams": teams,
                "actions": [{"value": key, "label": action_label(key)} for key in actions],
                "summary": {
                    "total": len(filtered),
                    "denied": int(summary["denied"]),
                    "latest": audit_time_label(summary["latest"]),
                },
                "entries": [
                    {
                        "time": audit_time_label(str(event.get("ts", ""))),
                        "action": str(event.get("action", "")),
                        "action_label": action_label(str(event.get("action", ""))),
                        "actor": str(event.get("actor", "")),
                        "actor_name": str(event.get("actor_name") or event.get("actor") or ""),
                        "team": self.event_team(event),
                        "status": str(event.get("status", "ok")),
                        "path": event_primary_path(event),
                        "root_label": str(event.get("root_label", "")),
                        "reason": str(event.get("reason", "")),
                        "file_status_label": str(event.get("file_status_label", "")),
                    }
                    for event in filtered[:120]
                ],
                "limit_note": "최근 1,000건 기준",
            }
        )

    def api_admin_archive(self, user: dict):
        if user.get("username") != "admin":
            self.send_json({"error": "forbidden", "message": "admin only"}, 403)
            return
        entries = self.archive_entries_for_admin(MAX_ARCHIVE_DISPLAY)
        payload_entries = []
        owner_stats = {}
        total_bytes = 0
        for entry in entries:
            archive_rel = str(entry["archive_rel"])
            original_rel = str(entry["original_rel"])
            if "/home/" in archive_rel or "/home/" in original_rel:
                continue
            owner = str(entry["owner_username"])
            size = int(entry["size"])
            total_bytes += size
            owner_stat = owner_stats.setdefault(
                owner,
                {
                    "owner": owner,
                    "owner_name": str(entry["owner_name"]),
                    "team": str(entry["team"]),
                    "count": 0,
                    "bytes": 0,
                },
            )
            owner_stat["count"] += 1
            owner_stat["bytes"] += size
            archive_urls = self.admin_archive_urls(owner, archive_rel)
            payload_entries.append(
                {
                    "owner": owner,
                    "owner_name": str(entry["owner_name"]),
                    "team": str(entry["team"]),
                    "archive_path": archive_rel,
                    "original_path": original_rel,
                    "name": Path(original_rel).name,
                    "kind": str(entry["type_key"]),
                    "kind_label": str(entry["type_label"]),
                    "size": size,
                    "size_label": format_size(size) if size else "-",
                    "archived_at": dt.datetime.fromtimestamp(float(entry["mtime"])).strftime("%Y-%m-%d %H:%M"),
                    "actor": str((entry.get("event") or {}).get("actor_name") or (entry.get("event") or {}).get("actor") or entry["owner_name"]),
                    "view_url": archive_urls["view"],
                    "preview_url": archive_urls["preview"],
                    "download_url": archive_urls["download"],
                }
            )
        self.send_json(
            {
                "entries": payload_entries,
                "total": len(payload_entries),
                "limit": MAX_ARCHIVE_DISPLAY,
                "total_bytes": total_bytes,
                "total_bytes_label": format_size(total_bytes) if total_bytes else "0 B",
                "owners": sorted(
                    [
                        {
                            **stat,
                            "bytes_label": format_size(int(stat["bytes"])) if int(stat["bytes"]) else "0 B",
                        }
                        for stat in owner_stats.values()
                    ],
                    key=lambda item: int(item["bytes"]),
                    reverse=True,
                ),
            }
        )

    def api_admin_archive_purge_old(self, user: dict, payload: dict):
        if user.get("username") != "admin":
            self.send_json({"error": "forbidden", "message": "admin only"}, 403)
            return
        try:
            min_days = int(payload.get("min_days") or 30)
        except (TypeError, ValueError):
            min_days = 30
        min_days = max(1, min(min_days, 3650))
        cutoff = time.time() - (min_days * 24 * 60 * 60)
        purged = 0
        reclaimed_bytes = 0
        for entry in self.archive_entries_for_admin(10000):
            try:
                mtime = float(entry.get("mtime") or 0)
                archive_target = Path(entry["archive_abs"]).resolve()
                owner = entry["owner"]
                personal = root_by_id(owner, "personal")
            except (KeyError, OSError, TypeError, ValueError):
                continue
            if mtime > cutoff or not personal:
                continue
            archive_root = archive_root_path(Path(personal["path"]).resolve()).resolve()
            if archive_target != archive_root and archive_root not in archive_target.parents:
                continue
            if not archive_target.exists():
                continue
            size = path_tree_size(archive_target)
            if archive_target.is_dir():
                shutil.rmtree(archive_target)
            else:
                archive_target.unlink()
            cleanup_empty_archive_dirs(archive_target.parent, archive_root)
            purged += 1
            reclaimed_bytes += size
        self.audit_event(
            user,
            "archive_bulk_purged",
            status="ok",
            reason=f"older_than_{min_days}_days",
            count=purged,
            size=reclaimed_bytes,
        )
        self.send_json(
            {
                "ok": True,
                "action": "archive_bulk_purged",
                "purged": purged,
                "reclaimed_bytes": reclaimed_bytes,
                "reclaimed_label": format_size(reclaimed_bytes) if reclaimed_bytes else "0 B",
            }
        )

    def api_admin_user(self, user: dict, query: dict):
        if user.get("username") != "admin":
            self.send_json({"error": "forbidden", "message": "admin only"}, 403)
            return
        username = query.get("username", [""])[0].strip()
        target_user = self.portal.user(username)
        if not target_user or username == "admin":
            self.send_json({"error": "not_found", "message": "user not found"}, 404)
            return
        personal = root_by_id(target_user, "personal")
        shared = root_by_id(target_user, "team_shared")
        personal_summary = summarize_workspace(Path(personal["path"]).resolve(), exclude_selftests=True) if personal else {"exists": False, "files": 0, "bytes": 0, "last_mtime": 0}
        shared_summary = summarize_workspace(Path(shared["path"]).resolve(), exclude_selftests=True) if shared else {"exists": False, "files": 0, "bytes": 0, "last_mtime": 0}
        events = [
            event
            for event in self.portal.recent_events(1000)
            if str(event.get("actor") or "") == username or str(event.get("owner") or "") == username
        ]
        events = operational_events(events)
        report_events = [
            event
            for event in events
            if str(event.get("action", "")) in WORKFLOW_AUDIT_ACTIONS
        ]
        summary = self.audit_summary(events)
        recent_files = self.recent_files_for_root(personal, 10) if personal else []
        password_record = self.portal_password_record(username)
        password_changed_at = str(target_user.get("password_changed_at") or "")
        must_change_password = bool(target_user.get("must_change_password"))
        password_value = str(password_record.get("password") or "")
        if password_changed_at:
            credential_status = "changed"
            credential_label = "사용자가 직접 변경함"
            password_value = ""
        elif password_value and must_change_password:
            credential_status = "temporary"
            credential_label = "임시 비밀번호"
        elif password_value:
            credential_status = "issued"
            credential_label = "관리자 발급 비밀번호"
        else:
            credential_status = "missing"
            credential_label = "기록 없음"
        self.send_json(
            {
                "user": {
                    "username": username,
                    "name": target_user.get("name", username),
                    "team": user_team_key(target_user),
                    "disabled": bool(target_user.get("disabled")),
                },
                "credentials": {
                    "username": username,
                    "name": target_user.get("name", username),
                    "password": password_value,
                    "status": credential_status,
                    "status_label": credential_label,
                    "must_change_password": must_change_password,
                    "changed_at": password_changed_at,
                    "issued_at": str(target_user.get("password_issued_at") or ""),
                },
                "personal": {
                    "exists": bool(personal_summary.get("exists")),
                    "files": int(personal_summary.get("files", 0)),
                    "bytes": int(personal_summary.get("bytes", 0)),
                    "bytes_label": format_size(int(personal_summary.get("bytes", 0))),
                    "last_activity": summary_last_activity(personal_summary),
                    "url": self.admin_browse_url(user, Path(personal["path"]).resolve()) if personal else "",
                },
                "shared": {
                    "exists": bool(shared_summary.get("exists")),
                    "files": int(shared_summary.get("files", 0)),
                    "bytes": int(shared_summary.get("bytes", 0)),
                    "bytes_label": format_size(int(shared_summary.get("bytes", 0))),
                    "last_activity": summary_last_activity(shared_summary),
                    "url": self.admin_browse_url(user, Path(shared["path"]).resolve()) if shared else "",
                },
                "actions": {
                    "upload": int(summary["actions"].get("upload", 0)),
                    "preview_open": int(summary["actions"].get("preview_open", 0)),
                    "move_to_shared": int(summary["actions"].get("move_to_shared", 0)),
                    "status_update": int(summary["actions"].get("status_update", 0)),
                },
                "recent_files": [
                    {
                        "path": rel,
                        "name": Path(rel).name,
                        "size": size,
                        "size_label": format_size(size),
                        "modified": dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
                        "url": self.admin_browse_url(user, Path(personal["path"]).resolve() / rel) if personal else "",
                    }
                    for mtime, rel, size in recent_files
                    if "/home/" not in rel
                ],
                "recent_events": [
                    {
                        "time": audit_time_label(str(event.get("ts", ""))),
                        "action": str(event.get("action", "")),
                        "action_label": action_label(str(event.get("action", ""))),
                        "path": event_primary_path(event),
                        "status": str(event.get("status", "ok")),
                    }
                    for event in report_events[:12]
                ],
            }
        )
