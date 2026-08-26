#!/usr/bin/env python3
import datetime as dt
import html
import os
from pathlib import Path
import posixpath
import time
import urllib.parse

from portal_core import (
    SORT_OPTIONS,
    TYPE_FILTERS,
    action_label,
    archive_root_path,
    audit_time_label,
    can_archive_personal_path,
    date_filter_bounds,
    event_primary_path,
    file_status_key,
    file_type_info,
    format_size,
    is_operational_recent_path,
    is_selftest_path,
    listing_state_params,
    normalize_date_filter,
    normalized_rel_path,
    operation_notice_html,
    operational_events,
    restore_rel_from_archive_rel,
    root_by_id,
    safe_archive_rel_path,
    safe_name,
    search_key,
    shared_move_plan,
    summarize_workspace,
    summary_last_activity,
    user_team_key,
)
from portal_settings import (
    AUDIT_ACTION_LABELS,
    AUDIT_ROTATE_BYTES,
    CACHE_MAX_BYTES,
    CACHE_RETENTION_DAYS,
    FILE_STATUS_LABELS,
    HIDDEN_DIR_NAMES,
    LARGE_FILE_BYTES,
    MAX_ADMIN_FILE_SEARCH_RESULTS,
    MAX_ARCHIVE_DISPLAY,
    MAX_AUDIT_DISPLAY,
    MAX_SCAN_FILES,
    STALE_FILE_DAYS,
)
from portal_urls import app_file_url, app_folder_url, portal_url


class AdminCommonMixin:
    def admin_root(self, user: dict) -> dict | None:
        return root_by_id(user, "all")

    def admin_browse_url(self, admin_user: dict, target_path: Path) -> str:
        admin_root = self.admin_root(admin_user)
        if not admin_root:
            return "#"
        root_path = Path(admin_root["path"]).resolve()
        try:
            resolved = target_path.resolve()
            rel = resolved.relative_to(root_path).as_posix()
        except (OSError, ValueError):
            rel = ""
        rel_path = "" if rel == "." else rel
        if target_path.is_file():
            return app_file_url(admin_root["id"], rel_path)
        return app_folder_url(admin_root["id"], rel_path)

    def audit_table_html(self, events: list[dict], empty_text: str = "아직 기록된 포털 작업이 없습니다.") -> str:
        rows = []
        for event in events:
            action = str(event.get("action", ""))
            actor = str(event.get("actor_name") or event.get("actor") or "-")
            status = str(event.get("status") or "ok")
            path = event_primary_path(event) or str(event.get("root_label") or "-")
            status_text = "" if status == "ok" else f" · {status}"
            rows.append(
                f"""<tr>
                  <td>{html.escape(audit_time_label(str(event.get("ts", ""))))}</td>
                  <td>{html.escape(actor)}</td>
                  <td><span class="event-pill">{html.escape(action_label(action))}</span></td>
                  <td>{html.escape(path)}<span class="muted">{html.escape(status_text)}</span></td>
                </tr>"""
            )
        if not rows:
            return f"<div class='card'><p class='muted'>{html.escape(empty_text)}</p></div>"
        return f"""<div class="admin-table-scroll"><table class="audit-table">
          <thead><tr><th>시간</th><th>사용자</th><th>작업</th><th>대상</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table></div>"""

    def compact_audit_list_html(self, events: list[dict], empty_text: str) -> str:
        if not events:
            return f"<p class='muted'>{html.escape(empty_text)}</p>"
        rows = []
        for event in events:
            action = str(event.get("action", ""))
            actor = str(event.get("actor_name") or event.get("actor") or "-")
            path = event_primary_path(event) or str(event.get("root_label") or "-")
            rows.append(
                f"""<li>
                  <span>{html.escape(audit_time_label(str(event.get("ts", ""))))}</span>
                  <span class="event-pill">{html.escape(action_label(action))}</span>
                  <span class="path"><strong>{html.escape(actor)}</strong> · {html.escape(path)}</span>
                </li>"""
            )
        return f"<ul class='compact-audit-list'>{''.join(rows)}</ul>"

    def audit_summary(self, events: list[dict]) -> dict:
        actions = {key: 0 for key in AUDIT_ACTION_LABELS}
        actors: dict[str, int] = {}
        denied = 0
        latest = ""
        for event in events:
            action = str(event.get("action", ""))
            if action in actions:
                actions[action] += 1
            if str(event.get("status", "ok")) != "ok" or action == "permission_denied":
                denied += 1
            actor = str(event.get("actor_name") or event.get("actor") or "").strip()
            if actor:
                actors[actor] = actors.get(actor, 0) + 1
            latest = latest or str(event.get("ts", ""))
        return {
            "actions": actions,
            "actors": actors,
            "denied": denied,
            "latest": latest,
        }

    def latest_events_by_action(self, events: list[dict], actions: list[str], limit: int = 3) -> dict[str, list[dict]]:
        grouped = {action: [] for action in actions}
        for event in events:
            action = str(event.get("action") or "")
            if action in grouped and len(grouped[action]) < limit:
                grouped[action].append(event)
        return grouped

    def preview_failure_summary(self, events: list[dict]) -> dict:
        labels = {
            "office_pdf_convert": "Office 변환 실패",
            "pdf_page_render": "PDF 페이지 렌더 실패",
            "office_page_render": "Office 페이지 렌더 실패",
            "pptx_thumbnail_missing": "PPTX 썸네일 없음",
        }
        summary: dict[str, dict] = {}
        for event in events:
            if event.get("action") != "preview_failed":
                continue
            reason = str(event.get("reason") or "unknown")
            bucket = summary.setdefault(reason, {"label": labels.get(reason, reason or "원인 미상"), "count": 0, "latest": event})
            bucket["count"] += 1
        return summary

    def event_team(self, event: dict) -> str:
        for key in ("after_path_abs", "path_abs", "before_path_abs", "archive_path_abs"):
            value = str(event.get(key) or "")
            marker = "/home/portal/workspaces/"
            if marker in value:
                tail = value.split(marker, 1)[1]
                team = tail.split("/", 1)[0]
                if team:
                    return team
        root_label = str(event.get("root_label") or "")
        if "team-alpha" in root_label:
            return "team-alpha"
        if "team-beta" in root_label:
            return "team-beta"
        return ""

    def filter_events(self, events: list[dict], query: dict) -> list[dict]:
        actor = query.get("actor", [""])[0].strip()
        action = query.get("action", [""])[0].strip()
        team = query.get("team", [""])[0].strip()
        needle = search_key(query.get("q", [""])[0].strip())
        filtered = []
        for event in events:
            if actor and str(event.get("actor") or "") != actor:
                continue
            if action and str(event.get("action") or "") != action:
                continue
            if team and self.event_team(event) != team:
                continue
            if needle:
                haystack = search_key(" ".join(
                    str(event.get(key) or "")
                    for key in (
                        "actor",
                        "actor_name",
                        "action",
                        "path",
                        "before_path",
                        "after_path",
                        "archive_path",
                        "root_label",
                        "reason",
                        "file_status_label",
                    )
                ))
                if needle not in haystack:
                    continue
            filtered.append(event)
        return filtered

    def admin_filter_form_html(self, action: str, actor: str, team: str, q: str, users: list[dict], actions: list[str], teams: list[str]) -> str:
        actor_options = ['<option value="">전체 사용자</option>']
        for item in users:
            selected = " selected" if item["username"] == actor else ""
            label = f'{item.get("name", item["username"])} ({item["username"]})'
            actor_options.append(f'<option value="{html.escape(item["username"], quote=True)}"{selected}>{html.escape(label)}</option>')
        action_options = ['<option value="">전체 작업</option>']
        for item in actions:
            selected = " selected" if item == action else ""
            action_options.append(f'<option value="{html.escape(item, quote=True)}"{selected}>{html.escape(action_label(item))}</option>')
        team_options = ['<option value="">전체 팀</option>']
        for item in teams:
            selected = " selected" if item == team else ""
            team_options.append(f'<option value="{html.escape(item, quote=True)}"{selected}>{html.escape(item)}</option>')
        return f"""<form class="admin-filter-form" method="get" action="/admin/activity">
          <div class="admin-filter-heading">
            <strong>작업 기록 필터</strong>
            <span>사용자, 팀, 작업 종류, 파일명으로 좁혀봅니다</span>
          </div>
          <label>사용자
            <select name="actor">{''.join(actor_options)}</select>
          </label>
          <label>작업
            <select name="action">{''.join(action_options)}</select>
          </label>
          <label>팀
            <select name="team">{''.join(team_options)}</select>
          </label>
          <label>검색어
            <input type="search" name="q" value="{html.escape(q, quote=True)}" placeholder="파일명, 경로, 사유">
          </label>
          <button class="button primary" type="submit">필터 적용</button>
          <a class="button" href="/admin/activity">초기화</a>
        </form>"""

    def recent_files_for_root(self, root: dict, limit: int = 8) -> list[tuple[float, str, int]]:
        root_path = Path(root["path"]).resolve()
        rows = []
        if not root_path.exists():
            return rows
        scanned = 0
        for current, dirs, files in os.walk(root_path):
            dirs[:] = [d for d in dirs if safe_name(Path(d)) and d not in HIDDEN_DIR_NAMES]
            dirs[:] = [d for d in dirs if not self.portal.is_personal_shared_path(Path(current) / d)]
            for filename in files:
                scanned += 1
                if scanned > MAX_SCAN_FILES:
                    break
                path = Path(current) / filename
                try:
                    rel = path.relative_to(root_path).as_posix()
                    stat = path.stat()
                except OSError:
                    continue
                if is_selftest_path(rel):
                    continue
                if self.portal.is_personal_shared_path(path):
                    continue
                if safe_name(Path(rel)):
                    rows.append((stat.st_mtime, rel, stat.st_size))
            if scanned > MAX_SCAN_FILES:
                break
        rows.sort(reverse=True, key=lambda item: item[0])
        return rows[:limit]
