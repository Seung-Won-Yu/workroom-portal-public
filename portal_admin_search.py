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
from portal_urls import portal_url


class AdminSearchMixin:
    def admin_file_context_from_rel(self, rel_path: str) -> dict[str, str]:
        parts = [part for part in normalized_rel_path(rel_path).split("/") if part]
        if not parts:
            return {"team": "-", "owner": "-", "owner_username": "", "scope": "전체 작업공간"}
        team = parts[0]
        if len(parts) >= 2 and parts[1] == "shared":
            return {"team": team, "owner": "팀 공유", "owner_username": "", "scope": "팀 공유"}
        owner_username = parts[1] if len(parts) >= 2 else ""
        owner_name = owner_username or "-"
        member = self.portal.user(owner_username)
        if member:
            owner_name = member.get("name", owner_username)
        return {"team": team, "owner": owner_name, "owner_username": owner_username, "scope": "개인 작업공간"}

    def admin_file_search_entries(
        self,
        user: dict,
        q: str,
        type_filter: str,
        status_filter: str,
        date_from: str,
        date_to: str,
        owner_filter: str,
        team_filter: str,
        scope_filter: str,
        sort_key: str,
        result_limit: int = MAX_ADMIN_FILE_SEARCH_RESULTS,
    ) -> dict:
        admin_root = self.admin_root(user)
        if not admin_root:
            return {"entries": [], "total": 0, "scanned": 0, "truncated": False}
        root_path = Path(admin_root["path"]).resolve()
        if not root_path.exists() or not root_path.is_dir():
            return {"entries": [], "total": 0, "scanned": 0, "truncated": False}

        needle = search_key(q)
        date_start, date_end = date_filter_bounds(date_from, date_to)
        entries = []
        scanned = 0
        truncated = False

        for current, dirs, files in os.walk(root_path):
            dirs[:] = [d for d in dirs if safe_name(Path(d)) and d not in HIDDEN_DIR_NAMES]
            dirs[:] = [d for d in dirs if not self.portal.is_personal_shared_path(Path(current) / d)]
            for filename in files:
                scanned += 1
                if scanned > MAX_SCAN_FILES:
                    truncated = True
                    break
                path = Path(current) / filename
                try:
                    rel = path.relative_to(root_path).as_posix()
                    if not safe_name(Path(rel)) or is_operational_recent_path(admin_root, rel):
                        continue
                    if is_selftest_path(rel):
                        continue
                    if self.portal.is_personal_shared_path(path):
                        continue
                    stat = path.stat()
                except OSError:
                    continue

                context = self.admin_file_context_from_rel(rel)
                if team_filter and context["team"] != team_filter:
                    continue
                if owner_filter and context["owner_username"] != owner_filter:
                    continue
                if scope_filter and context["scope"] != scope_filter:
                    continue
                if needle:
                    haystack = search_key(" ".join((filename, rel, context["owner"], context["owner_username"], context["team"])))
                    if needle not in haystack:
                        continue
                if date_start is not None and stat.st_mtime < date_start:
                    continue
                if date_end is not None and stat.st_mtime > date_end:
                    continue

                type_key, type_label, type_token = file_type_info(path, False)
                if type_filter and type_key != type_filter:
                    continue
                status_key = ""
                if status_filter:
                    status_key = file_status_key(admin_root, rel, self.portal.events_for_target(path, limit=12))
                    if status_key != status_filter:
                        continue

                entries.append(
                    {
                        "path": path,
                        "rel": rel,
                        "name": filename,
                        "type_key": type_key,
                        "type_label": type_label,
                        "type_token": type_token,
                        "status_key": status_key,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                        **context,
                    }
                )
            if truncated:
                break

        if sort_key == "size":
            entries.sort(key=lambda item: (-int(item["size"]), search_key(item["name"])))
        elif sort_key == "type":
            entries.sort(key=lambda item: (str(item["type_key"]), search_key(item["name"])))
        elif sort_key == "name":
            entries.sort(key=lambda item: search_key(item["rel"]))
        else:
            entries.sort(key=lambda item: (-float(item["mtime"]), search_key(item["rel"])))
        display_entries = entries[:result_limit]
        if not status_filter:
            for item in display_entries:
                item["status_key"] = file_status_key(admin_root, str(item["rel"]), self.portal.events_for_target(item["path"], limit=12))
        return {
            "entries": display_entries,
            "total": len(entries),
            "scanned": scanned,
            "truncated": truncated,
            "entry_limit": result_limit,
        }

    def admin_file_search_form_html(
        self,
        q: str,
        type_filter: str,
        status_filter: str,
        date_from: str,
        date_to: str,
        owner_filter: str,
        team_filter: str,
        scope_filter: str,
        sort_key: str,
        users: list[dict],
        teams: list[str],
    ) -> str:
        owner_options = ['<option value="">전체 사용자</option>']
        for member in users:
            selected = " selected" if member["username"] == owner_filter else ""
            label = f"{member.get('name', member['username'])} ({member['username']})"
            owner_options.append(f'<option value="{html.escape(member["username"], quote=True)}"{selected}>{html.escape(label)}</option>')
        team_options = ['<option value="">전체 팀</option>']
        for team in teams:
            selected = " selected" if team == team_filter else ""
            team_options.append(f'<option value="{html.escape(team, quote=True)}"{selected}>{html.escape(team)}</option>')
        type_options = []
        for key, label in TYPE_FILTERS:
            selected = " selected" if key == type_filter else ""
            type_options.append(f'<option value="{html.escape(key, quote=True)}"{selected}>{html.escape(label)}</option>')
        status_options = ['<option value="">모든 상태</option>']
        for key, label in FILE_STATUS_LABELS.items():
            selected = " selected" if key == status_filter else ""
            status_options.append(f'<option value="{html.escape(key, quote=True)}"{selected}>{html.escape(label)}</option>')
        scope_options = ['<option value="">전체 공간</option>']
        for value in ("개인 작업공간", "팀 공유"):
            selected = " selected" if value == scope_filter else ""
            scope_options.append(f'<option value="{html.escape(value, quote=True)}"{selected}>{html.escape(value)}</option>')
        sort_options = []
        for key, label in SORT_OPTIONS:
            selected = " selected" if key == sort_key else ""
            sort_options.append(f'<option value="{html.escape(key, quote=True)}"{selected}>{html.escape(label)}</option>')
        return f"""<form class="admin-filter-form" method="get" action="/admin/search">
          <div class="admin-filter-heading">
            <strong>산출물 필터</strong>
            <span>파일명, 사용자, 팀, 상태, 날짜를 조합해 찾습니다</span>
          </div>
          <label>검색어
            <input type="search" name="q" value="{html.escape(q, quote=True)}" placeholder="파일명, 경로, 사용자">
          </label>
          <label>사용자
            <select name="owner">{''.join(owner_options)}</select>
          </label>
          <label>팀
            <select name="team">{''.join(team_options)}</select>
          </label>
          <label>공간
            <select name="scope">{''.join(scope_options)}</select>
          </label>
          <label>종류
            <select name="type">{''.join(type_options)}</select>
          </label>
          <label>상태
            <select name="status">{''.join(status_options)}</select>
          </label>
          <label>시작일
            <input type="date" name="date_from" value="{html.escape(date_from, quote=True)}">
          </label>
          <label>종료일
            <input type="date" name="date_to" value="{html.escape(date_to, quote=True)}">
          </label>
          <label>정렬
            <select name="sort">{''.join(sort_options)}</select>
          </label>
          <button class="button primary" type="submit">검색</button>
          <a class="button" href="/admin/search">초기화</a>
        </form>"""

    def admin_file_search_table_html(self, user: dict, entries: list[dict], state_params: dict[str, str]) -> str:
        if not entries:
            return "<div class='card'><p class='muted'>조건에 맞는 산출물이 없습니다. 검색어, 사용자, 상태 또는 날짜를 조정해보세요.</p></div>"
        admin_root = self.admin_root(user)
        root_id = admin_root["id"] if admin_root else "all"
        rows = []
        for entry in entries:
            rel = str(entry["rel"])
            rel_q = urllib.parse.quote(rel)
            parent = posixpath.dirname(rel)
            view_url = portal_url("/app", {"root": root_id, "file": rel, **state_params})
            folder_url = portal_url("/app", {"root": root_id, "path": "" if parent == "." else parent, **state_params})
            rows.append(
                f"""<tr>
                  <td class="path-cell"><strong>{html.escape(str(entry["name"]))}</strong><div class="muted">{html.escape(rel)}</div></td>
                  <td>{html.escape(str(entry["owner"]))}<div class="muted">{html.escape(str(entry["team"]))} · {html.escape(str(entry["scope"]))}</div></td>
                  <td><span class="type-badge kind-{html.escape(str(entry["type_key"]), quote=True)}">{html.escape(str(entry["type_label"]))}</span></td>
                  <td>{self.status_pill_html(str(entry["status_key"]))}</td>
                  <td>{format_size(int(entry["size"]))}</td>
                  <td>{dt.datetime.fromtimestamp(float(entry["mtime"])).strftime("%Y-%m-%d %H:%M")}</td>
                  <td><div class="file-actions">
                    <a class="button small primary" href="{html.escape(view_url, quote=True)}">보기</a>
                    <a class="button small" href="{html.escape(folder_url, quote=True)}">폴더</a>
                    <a class="button small" href="/download?root={urllib.parse.quote(root_id)}&path={rel_q}">다운로드</a>
                  </div></td>
                </tr>"""
            )
        return f"""<div class="admin-table-scroll"><table class="member-table admin-file-search-table">
          <thead><tr><th>파일</th><th>소유/공간</th><th>종류</th><th>상태</th><th>크기</th><th>수정일</th><th>작업</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table></div>"""

    def admin_file_search(self, user: dict, query: dict):
        if user.get("username") != "admin":
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>관리자만 볼 수 있는 화면입니다.</p></div>", 403, user.get("name"))
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
        )
        state_params = listing_state_params(q, type_filter, status_filter, date_from, date_to, sort_key)
        count_note = (
            f"조건에 맞는 산출물 {int(result['total']):,}개 중 최근 {len(result['entries']):,}개를 표시합니다. "
            f"스캔 파일 {int(result['scanned']):,}개 기준입니다."
        )
        if result["truncated"]:
            count_note += f" 스캔이 {MAX_SCAN_FILES:,}개에서 중단되어 더 좁은 조건을 권장합니다."
        body = f"""<section class="admin-overview">
          <div class="admin-hero">
            <div>
              <span class="admin-kicker">운영 허브</span>
              <h2>전체 산출물 검색</h2>
              <p class="admin-hero-copy">모든 팀과 개인 작업공간에서 파일명, 사용자, 팀, 상태, 수정일 기준으로 산출물을 찾습니다.</p>
            </div>
            <div class="toolbar">
              <a class="button" href="/admin">관리자 대시보드</a>
              <a class="button" href="/admin/activity">작업 기록 검색</a>
            </div>
          </div>
          {self.admin_file_search_form_html(q, type_filter, status_filter, date_from, date_to, owner_filter, team_filter, scope_filter, sort_key, users, teams)}
          <div class="stat-grid">
            <div class="stat-card"><span>검색 결과</span><strong>{int(result["total"]):,}개</strong></div>
            <div class="stat-card"><span>표시</span><strong>{len(result["entries"]):,}개</strong></div>
            <div class="stat-card"><span>스캔</span><strong>{int(result["scanned"]):,}개</strong></div>
          </div>
          <section class="admin-section">
            <p class="muted">{html.escape(count_note)}</p>
            {self.admin_file_search_table_html(user, result["entries"], state_params)}
          </section>
        </section>"""
        self.send_html("전체 산출물 검색", body, user_name=user.get("name", user["username"]))
