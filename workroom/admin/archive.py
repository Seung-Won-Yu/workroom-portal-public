#!/usr/bin/env python3
import datetime as dt
import html
import os
from pathlib import Path
import posixpath
import time
import urllib.parse

from workroom.core.scopes import (
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
    shared_move_plan,
    summarize_workspace,
    summary_last_activity,
    user_team_key,
)
from workroom.core.settings import (
    ACTIVE_CONTENT_EXTENSIONS,
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
    OFFICE_PREVIEW_EXTENSIONS,
    STALE_FILE_DAYS,
)
from workroom.files.preview import convert_office_to_pdf, pptx_thumbnail, render_pdf_pages
from workroom.web.ui import preview_page
from workroom.core.urls import portal_url


class AdminArchiveMixin:
    def user_archive_entries(self, owner: dict, events_by_archive: dict[str, dict]) -> list[dict]:
        personal = root_by_id(owner, "personal")
        if not personal:
            return []
        personal_root = Path(personal["path"]).resolve()
        archive_root = archive_root_path(personal_root).resolve()
        if not archive_root.exists():
            return []

        entries = []
        seen: set[str] = set()

        def add_entry(path: Path, event: dict | None = None) -> None:
            if not path.exists():
                return
            try:
                archive_rel = path.relative_to(personal_root).as_posix()
                path_key = str(path.resolve())
            except ValueError:
                return
            if path_key in seen or not safe_archive_rel_path(archive_rel):
                return
            event = event or events_by_archive.get(path_key, {})
            original_rel = str(event.get("before_path") or restore_rel_from_archive_rel(archive_rel))
            try:
                stat = path.stat()
            except OSError:
                return
            type_key, type_label, _token = file_type_info(path, path.is_dir())
            seen.add(path_key)
            entries.append(
                {
                    "owner": owner,
                    "owner_username": owner["username"],
                    "owner_name": owner.get("name", owner["username"]),
                    "team": user_team_key(owner),
                    "archive_rel": archive_rel,
                    "archive_abs": path,
                    "original_rel": normalized_rel_path(original_rel),
                    "type_key": type_key,
                    "type_label": type_label,
                    "size": stat.st_size if path.is_file() else 0,
                    "mtime": stat.st_mtime,
                    "event": event,
                }
            )

        for archive_abs, event in events_by_archive.items():
            path = Path(archive_abs)
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if archive_root == resolved or archive_root in resolved.parents:
                add_entry(resolved, event)

        for current, dirs, files in os.walk(archive_root):
            dirs[:] = [d for d in dirs if safe_name(Path(d))]
            for name in files:
                path = Path(current) / name
                try:
                    rel_to_archive_root = path.relative_to(archive_root)
                except ValueError:
                    continue
                if len(rel_to_archive_root.parts) < 2:
                    continue
                add_entry(path)
        entries.sort(key=lambda item: item["mtime"], reverse=True)
        return entries

    def archive_entries_for_admin(self, limit: int = MAX_ARCHIVE_DISPLAY) -> list[dict]:
        events = self.portal.recent_events(800)
        events_by_archive = {}
        for event in events:
            if event.get("action") != "archive":
                continue
            archive_abs = str(event.get("archive_path_abs") or "")
            if archive_abs:
                events_by_archive[archive_abs] = event
        entries = []
        for owner in self.portal.all_users():
            if owner.get("username") == "admin":
                continue
            entries.extend(self.user_archive_entries(owner, events_by_archive))
        entries.sort(key=lambda item: item["mtime"], reverse=True)
        return entries[:limit]

    def resolve_admin_archive_item(self, user: dict, query: dict) -> tuple[dict, dict, Path, str] | None:
        if user.get("username") != "admin":
            return None
        owner_username = query.get("owner", [""])[0].strip()
        archive_rel = query.get("archive_path", [""])[0].strip()
        if not owner_username or not safe_archive_rel_path(archive_rel):
            return None
        owner = self.portal.user(owner_username)
        if not owner or owner.get("username") == "admin":
            return None
        personal = root_by_id(owner, "personal")
        if not personal:
            return None
        personal_root = Path(personal["path"]).resolve()
        archive_root = archive_root_path(personal_root).resolve()
        try:
            target = (personal_root / archive_rel).resolve()
        except OSError:
            return None
        if not target.exists() or not target.is_file():
            return None
        if archive_root != target and archive_root not in target.parents:
            return None
        return owner, personal, target, archive_rel

    def admin_archive_urls(self, owner: str, archive_rel: str) -> dict[str, str]:
        params = {"owner": owner, "archive_path": archive_rel}
        return {
            "view": portal_url("/admin/archive/view", params),
            "preview": portal_url("/admin/archive/preview", params),
            "download": portal_url("/admin/archive/download", params),
            "raw": portal_url("/admin/archive/raw", params),
            "pdf_page": "/admin/archive/pdf_page",
            "converted_page": "/admin/archive/converted_page",
            "thumbnail": portal_url("/admin/archive/thumbnail", params),
        }

    def admin_archive_preview_body(self, owner: dict, root: dict, target: Path, archive_rel: str, query: dict, show_toolbar: bool) -> str:
        try:
            xlsx_sheet = int(query.get("sheet", ["0"])[0])
        except (TypeError, ValueError):
            xlsx_sheet = 0
        urls = self.admin_archive_urls(owner["username"], archive_rel)
        params = {"owner": owner["username"], "archive_path": archive_rel}
        return self.file_preview_body(
            root,
            target,
            archive_rel,
            include_folder_link=False,
            show_toolbar=show_toolbar,
            xlsx_sheet=xlsx_sheet,
            xlsx_route="/admin/archive/view" if show_toolbar else "/admin/archive/preview",
            state_params=params,
            download_url=urls["download"],
            raw_url=urls["raw"],
            pdf_page_route=urls["pdf_page"],
            converted_page_route=urls["converted_page"],
            thumbnail_url=urls["thumbnail"],
        )

    def admin_archive_view(self, user: dict, query: dict):
        resolved = self.resolve_admin_archive_item(user, query)
        if not resolved:
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>관리자만 확인할 수 있거나 보관 항목이 없습니다.</p></div>", 403, user.get("name"))
            return
        owner, root, target, archive_rel = resolved
        urls = self.admin_archive_urls(owner["username"], archive_rel)
        original_rel = restore_rel_from_archive_rel(archive_rel)
        body = f"""<section class="admin-overview">
          <div class="admin-hero">
            <div>
              <span class="admin-kicker">보관함 미리보기</span>
              <h2>{html.escape(target.name)}</h2>
              <p class="admin-hero-copy">{html.escape(owner.get("name", owner["username"]))} · 원래 위치 {html.escape(original_rel)} · 보관 위치 {html.escape(archive_rel)}</p>
            </div>
            <div class="toolbar">
              <a class="button" href="/app?view=admin-archive">보관함 목록</a>
              <a class="button primary" href="{html.escape(urls["download"], quote=True)}">원본 다운로드</a>
            </div>
          </div>
          <section class="admin-section">
            {self.admin_archive_preview_body(owner, root, target, archive_rel, query, show_toolbar=False)}
          </section>
        </section>"""
        self.audit_event(user, "preview_open", root, archive_rel, target, status="ok", reason="admin_archive")
        self.send_html("보관함 파일 보기", body, user_name=user.get("name", user["username"]))

    def admin_archive_preview(self, user: dict, query: dict):
        resolved = self.resolve_admin_archive_item(user, query)
        if not resolved:
            data = preview_page("접근 불가", "<div class='card'><h2>접근 불가</h2><p>보관 항목을 확인할 수 없습니다.</p></div>")
        else:
            owner, root, target, archive_rel = resolved
            data = preview_page(target.name, self.admin_archive_preview_body(owner, root, target, archive_rel, query, show_toolbar=True))
            self.audit_event(user, "preview_open", root, archive_rel, target, status="ok", reason="admin_archive")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def admin_archive_download(self, user: dict, query: dict):
        resolved = self.resolve_admin_archive_item(user, query)
        if not resolved:
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>보관 항목을 다운로드할 수 없습니다.</p></div>", 403, user.get("name"))
            return
        _owner, root, target, archive_rel = resolved
        self.audit_event(user, "download", root, archive_rel, target, file_size=target.stat().st_size, reason="admin_archive")
        self.stream_file(target, download_name=target.name)

    def admin_archive_raw(self, user: dict, query: dict):
        resolved = self.resolve_admin_archive_item(user, query)
        if not resolved:
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>보관 항목을 열 수 없습니다.</p></div>", 403, user.get("name"))
            return
        _owner, _root, target, _archive_rel = resolved
        suffix = target.suffix.lower()
        if suffix in ACTIVE_CONTENT_EXTENSIONS or suffix == ".svg":
            self.stream_file(target, download_name=target.name, inline=False, content_type_override="text/plain; charset=utf-8", extra_headers={"X-Content-Type-Options": "nosniff"})
            return
        self.stream_file(target, download_name=target.name, inline=True, extra_headers={"X-Content-Type-Options": "nosniff"})

    def admin_archive_pdf_page(self, user: dict, query: dict):
        resolved = self.resolve_admin_archive_item(user, query)
        if not resolved:
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>페이지를 열 수 없습니다.</p></div>", 403, user.get("name"))
            return
        _owner, _root, target, _archive_rel = resolved
        if target.suffix.lower() != ".pdf":
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>PDF 파일이 아닙니다.</p></div>", 403, user.get("name"))
            return
        pages, _error = render_pdf_pages(target)
        self.stream_png_page(pages, self.page_from_query(query))

    def admin_archive_converted_page(self, user: dict, query: dict):
        resolved = self.resolve_admin_archive_item(user, query)
        if not resolved:
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>페이지를 열 수 없습니다.</p></div>", 403, user.get("name"))
            return
        _owner, root, target, archive_rel = resolved
        if target.suffix.lower() not in OFFICE_PREVIEW_EXTENSIONS:
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>변환 미리보기 대상이 아닙니다.</p></div>", 403, user.get("name"))
            return
        pdf_path, error = convert_office_to_pdf(target)
        if not pdf_path:
            self.audit_event(user, "preview_failed", root, archive_rel, target, status="failed", reason="admin_archive_office_pdf_convert", error=error or "")
            self.send_html("변환 실패", f"<div class='card'><h2>변환 실패</h2><p>{html.escape(error or 'PDF 변환에 실패했습니다.')}</p></div>", 500, user.get("name"))
            return
        pages, page_error = render_pdf_pages(pdf_path)
        if not pages:
            self.audit_event(user, "preview_failed", root, archive_rel, target, status="failed", reason="admin_archive_office_page_render", error=page_error or "")
            self.send_html("변환 실패", f"<div class='card'><h2>변환 실패</h2><p>{html.escape(page_error or '페이지 이미지 변환에 실패했습니다.')}</p></div>", 500, user.get("name"))
            return
        self.stream_png_page(pages, self.page_from_query(query))

    def admin_archive_thumbnail(self, user: dict, query: dict):
        resolved = self.resolve_admin_archive_item(user, query)
        if not resolved:
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>썸네일을 열 수 없습니다.</p></div>", 403, user.get("name"))
            return
        _owner, _root, target, _archive_rel = resolved
        if target.suffix.lower() != ".pptx":
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>PPTX 파일이 아닙니다.</p></div>", 403, user.get("name"))
            return
        thumb = pptx_thumbnail(target)
        if not thumb:
            self.send_html("썸네일 없음", "<div class='card'><h2>썸네일 없음</h2><p>이 PPTX에는 내장 썸네일이 없습니다.</p></div>", 404, user.get("name"))
            return
        data, mime = thumb
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.end_headers()
        self.wfile.write(data)

    def archive_table_html(self, entries: list[dict], compact: bool = False) -> str:
        if not entries:
            return "<div class='card'><p class='muted'>현재 보관함에 복구할 항목이 없습니다.</p></div>"
        rows = []
        for entry in entries:
            event = entry.get("event") or {}
            actor = str(event.get("actor_name") or event.get("actor") or entry["owner_name"])
            archive_rel = str(entry["archive_rel"])
            restore_rel = str(entry["original_rel"])
            owner = str(entry["owner_username"])
            urls = self.admin_archive_urls(owner, archive_rel)
            restore_action = ""
            if not compact:
                restore_action = f"""<div class="table-actions">
                  <a class="button small" href="{html.escape(urls["view"], quote=True)}">보기</a>
                  <a class="button small" href="{html.escape(urls["download"], quote=True)}">다운로드</a>
                  <form class="inline-form" method="post" action="/restore_archive" onsubmit="return confirm('보관함에서 원래 위치로 복구합니다. 같은 이름이 있으면 안전한 새 이름으로 복구됩니다. 계속할까요?');">
                  {self.csrf_input()}
                  <input type="hidden" name="owner" value="{html.escape(owner, quote=True)}">
                  <input type="hidden" name="archive_path" value="{html.escape(archive_rel, quote=True)}">
                  <button class="button small primary" type="submit">복구</button>
                </form></div>"""
            rows.append(
                f"""<tr>
                  <td><strong>{html.escape(entry["owner_name"])}</strong><div class="muted">{html.escape(entry["team"])}</div></td>
                  <td><span class="type-badge kind-{html.escape(entry["type_key"], quote=True)}">{html.escape(entry["type_label"])}</span></td>
                  <td class="path-cell"><strong>{html.escape(Path(restore_rel).name)}</strong><div class="muted">{html.escape(restore_rel)}</div></td>
                  <td>{format_size(int(entry["size"])) if int(entry["size"]) else "-"}</td>
                  <td>{dt.datetime.fromtimestamp(float(entry["mtime"])).strftime("%Y-%m-%d %H:%M")}<div class="muted">처리: {html.escape(actor)}</div></td>
                  <td>{restore_action}</td>
                </tr>"""
            )
        return f"""<div class="admin-table-scroll"><table class="archive-table">
          <thead><tr><th>소유자</th><th>종류</th><th>원래 위치</th><th>크기</th><th>보관일</th><th>작업</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table></div>"""
