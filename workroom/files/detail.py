#!/usr/bin/env python3
import html
import mimetypes
from pathlib import Path
import posixpath
import urllib.parse

from workroom.core.scopes import (
    SORT_OPTIONS,
    TYPE_FILTERS,
    action_label,
    audit_time_label,
    can_archive_personal_path,
    file_status_key,
    file_type_info,
    format_mtime,
    format_size,
    listing_state_params,
    normalize_date_filter,
    normalized_rel_path,
    operation_notice_html,
    shared_move_plan,
    user_team_key,
)
from workroom.files.preview import (
    code_preview_html,
    convert_office_to_pdf,
    docx_text_preview,
    html_preview_srcdoc,
    page_gallery_html,
    pptx_slide_text,
    pptx_thumbnail,
    render_markdown,
    render_pdf_pages,
    xlsx_grid_preview,
    xlsx_preview_html,
)
from workroom.core.settings import (
    FILE_STATUS_LABELS,
    MAX_PREVIEW_BYTES,
    OFFICE_PREVIEW_EXTENSIONS,
    TEXT_EXTENSIONS,
)
from workroom.core.urls import portal_url


class FileDetailMixin:
    def file_preview_body(
        self,
        root: dict,
        target: Path,
        rel_path: str,
        include_folder_link: bool,
        show_toolbar: bool = True,
        show_heading: bool = True,
        xlsx_sheet: int = 0,
        xlsx_route: str = "/view",
        state_params: dict[str, str] | None = None,
        download_url: str | None = None,
        raw_url: str | None = None,
        pdf_page_route: str = "/pdf_page",
        converted_page_route: str = "/converted_page",
        thumbnail_url: str | None = None,
    ) -> str:
        root_q = urllib.parse.quote(root["id"])
        rel_q = urllib.parse.quote(rel_path)
        parent = urllib.parse.quote(posixpath.dirname(rel_path))
        toolbar_items = []
        if include_folder_link:
            toolbar_items.append(f'<a class="button" href="/browse?root={root_q}&path={parent}">폴더 열기</a>')
        effective_download_url = download_url or f"/download?root={root_q}&path={rel_q}"
        toolbar_items.append(f'<a class="button primary" href="{html.escape(effective_download_url, quote=True)}">원본 다운로드</a>')
        toolbar = f"<div class='toolbar'>{''.join(toolbar_items)}</div>" if show_toolbar else ""
        download_hint = "원본 다운로드로 확인하세요." if show_toolbar else "상단 다운로드로 확인하세요."

        stat = target.stat()
        info = f"<p class='muted'>{html.escape(rel_path)} · {format_size(stat.st_size)} · {format_mtime(target)}</p>"
        suffix = target.suffix.lower()
        heading = f"<section class='file-head'><div><h2>{html.escape(target.name)}</h2>{info}</div></section>" if show_heading else ""

        if suffix == ".md" and stat.st_size <= MAX_PREVIEW_BYTES:
            content = target.read_text(encoding="utf-8", errors="replace")
            return toolbar + heading + render_markdown(content, root["id"], rel_path)

        if suffix in {".html", ".htm"}:
            source = target.read_text(encoding="utf-8", errors="replace") if stat.st_size <= MAX_PREVIEW_BYTES else "파일이 커서 소스 미리보기를 생략합니다."
            srcdoc = html.escape(html_preview_srcdoc(source, root["id"], rel_path), quote=True)
            return (
                toolbar
                + heading
                + "<div class='html-preview'>"
                + f"<iframe sandbox referrerpolicy='no-referrer' srcdoc=\"{srcdoc}\"></iframe>"
                + "</div>"
                + "<details class='source-details'><summary>소스 보기</summary>"
                + code_preview_html(source, "HTML")
                + "</details>"
            )

        if suffix in TEXT_EXTENSIONS and stat.st_size <= MAX_PREVIEW_BYTES:
            content = target.read_text(encoding="utf-8", errors="replace")
            label = suffix.lstrip(".").upper() or "TEXT"
            return toolbar + heading + code_preview_html(content, label)

        if suffix == ".pdf":
            pages, error = render_pdf_pages(target)
            if pages:
                return toolbar + heading + page_gallery_html(root_q, rel_q, pages, converted=False, route=pdf_page_route, extra_params=state_params)
            return (
                toolbar
                + heading
                + f"<div class='card'><p>페이지 이미지 미리보기를 만들 수 없습니다.</p><p class='muted'>{html.escape(error or '알 수 없는 오류')}</p><p class='muted'>{download_hint}</p></div>"
            )

        if suffix == ".xlsx":
            grid = xlsx_grid_preview(target, xlsx_sheet)
            sheet_name = str(grid.get("sheet_name", "Sheet1"))
            return (
                toolbar
                + heading
                + f"<p class='viewer-note'>선택한 시트 표 미리보기: {html.escape(sheet_name)}</p>"
                + xlsx_preview_html(grid, root["id"], rel_path, xlsx_route, state_params)
            )

        if suffix in OFFICE_PREVIEW_EXTENSIONS:
            pdf_path, error = convert_office_to_pdf(target)
            if pdf_path:
                pages, page_error = render_pdf_pages(pdf_path)
                if pages:
                    return (
                        toolbar
                        + heading
                        + f"<p class='viewer-note'>LibreOffice로 변환한 미리보기입니다. 실제 파일은 {download_hint}</p>"
                        + page_gallery_html(root_q, rel_q, pages, converted=True, route=converted_page_route, extra_params=state_params)
                    )
                return (
                    toolbar
                    + heading
                    + f"<div class='card'><p>페이지 이미지 미리보기를 만들 수 없습니다.</p><p class='muted'>{html.escape(page_error or '알 수 없는 오류')}</p><p class='muted'>{download_hint}</p></div>"
                )

            fallback = "<div class='card'><p class='muted'>문서 이미지 미리보기를 만들 수 없어 텍스트 미리보기로 표시합니다.</p></div>"
            if suffix == ".docx":
                content = docx_text_preview(target)
                fallback += f"<pre>{html.escape(content)}</pre>"
            elif suffix == ".pptx":
                effective_thumbnail_url = thumbnail_url or f"/thumbnail?root={root_q}&path={rel_q}"
                text = pptx_slide_text(target)
                thumb = pptx_thumbnail(target)
                if thumb:
                    fallback += f"<img class='preview-thumbnail' src='{html.escape(effective_thumbnail_url, quote=True)}' alt='PPTX 썸네일'>"
                fallback += f"<pre>{html.escape(text)}</pre>"
            return toolbar + heading + fallback

        if mimetypes.guess_type(str(target))[0] and mimetypes.guess_type(str(target))[0].startswith("image/"):
            effective_raw_url = raw_url or f"/raw?root={root_q}&path={rel_q}"
            return toolbar + heading + f"<img class='preview-image' src='{html.escape(effective_raw_url, quote=True)}' alt='{html.escape(target.name, quote=True)}'>"

        return toolbar + heading + f"<div class='card'><p>미리보기를 지원하지 않는 파일입니다. {download_hint}</p></div>"

    def file_context(self, user: dict, root: dict, rel_path: str) -> dict[str, str]:
        root_id = root.get("id", "")
        parts = [part for part in normalized_rel_path(rel_path).split("/") if part]
        if root_id == "personal":
            return {
                "owner": user.get("name", user.get("username", "")),
                "team": user_team_key(user),
                "scope": "개인 작업공간",
            }
        if root_id == "team_shared":
            return {
                "owner": "팀 공유",
                "team": user_team_key(user),
                "scope": "팀 공유",
            }
        if root_id == "all" and parts:
            team = parts[0]
            owner = "팀 공유" if len(parts) >= 2 and parts[1] == "shared" else (parts[1] if len(parts) >= 2 else "-")
            for member in self.portal.all_users():
                if member.get("username") == owner:
                    owner = member.get("name", owner)
                    break
            return {
                "owner": owner,
                "team": team,
                "scope": "관리자 전체",
            }
        return {
            "owner": "-",
            "team": "-",
            "scope": root.get("label", "작업공간"),
        }

    def status_pill_html(self, status_key: str) -> str:
        label = FILE_STATUS_LABELS.get(status_key, FILE_STATUS_LABELS["active"])
        return f'<span class="status-pill status-{html.escape(status_key, quote=True)}">{html.escape(label)}</span>'

    def file_scope_banner_html(self, user: dict, root: dict, rel_path: str, name: str) -> str:
        root_id = root.get("id", "")
        if root_id == "personal" and can_archive_personal_path(root, rel_path):
            plan = shared_move_plan(rel_path, name)
            return f"""<div class="file-scope-banner personal" aria-label="공개 범위">
              <strong>공개 범위: 개인 작업공간</strong>
              <span class="scope-note">팀원에게 보이지 않습니다. 검토가 끝났다면 팀 공유로 이동하세요.</span>
              <span class="scope-note">추천 이동 위치: {html.escape(plan["destination"])}</span>
            </div>"""
        if root_id == "team_shared":
            return """<div class="file-scope-banner shared" aria-label="공개 범위">
              <strong>공개 범위: 팀 공유공간</strong>
              <span class="scope-note">같은 팀원이 볼 수 있습니다.</span>
            </div>"""
        if root_id == "all":
            context = self.file_context(user, root, rel_path)
            return f"""<div class="file-scope-banner admin" aria-label="공개 범위">
              <strong>공개 범위: 관리자 전체 보기</strong>
              <span class="scope-note">{html.escape(context["owner"])} · {html.escape(context["scope"])}</span>
            </div>"""
        return f"""<div class="file-scope-banner" aria-label="공개 범위">
          <strong>공개 범위: {html.escape(root.get("label", "작업공간"))}</strong>
        </div>"""

    def status_form_html(self, root: dict, rel_path: str, current_status: str) -> str:
        options = []
        for key, label in FILE_STATUS_LABELS.items():
            if key == "shared" and root.get("id") != "team_shared" and current_status != "shared":
                continue
            selected = " selected" if key == current_status else ""
            options.append(f'<option value="{html.escape(key, quote=True)}"{selected}>{html.escape(label)}</option>')
        return f"""<form class="status-form" method="post" action="/set_file_status">
          {self.csrf_input()}
          <input type="hidden" name="root" value="{html.escape(root["id"], quote=True)}">
          <input type="hidden" name="path" value="{html.escape(rel_path, quote=True)}">
          <label>상태 변경
            <select name="file_status">{''.join(options)}</select>
          </label>
          <button class="button small primary" type="submit">상태 저장</button>
        </form>"""

    def file_detail_panel_html(self, user: dict, root: dict, target: Path, rel_path: str) -> str:
        events = self.portal.events_for_target(target, limit=20)
        status_key = file_status_key(root, rel_path, events)
        context = self.file_context(user, root, rel_path)
        stat = target.stat()
        activity_items = []
        for event in events[:5]:
            actor = str(event.get("actor_name") or event.get("actor") or "-")
            activity_items.append(
                f"""<li>
                  <span>{html.escape(audit_time_label(str(event.get("ts", ""))))}</span>
                  <span class="event-pill">{html.escape(action_label(str(event.get("action", ""))))}</span>
                  <span>{html.escape(actor)}</span>
                </li>"""
            )
        if not activity_items:
            activity_items.append("<li><span>-</span><span class='event-pill'>기록 없음</span><span>아직 기록된 포털 작업이 없습니다.</span></li>")
        return f"""<details class="file-detail-panel" aria-label="파일 상세 정보">
          <summary>
            <span class="file-detail-summary-title"><span>파일 정보와 최근 작업</span></span>
            {self.status_pill_html(status_key)}
          </summary>
          <div class="file-detail-body">
            <div class="detail-grid">
              <div class="detail-item"><span>파일 상태</span><strong>{self.status_pill_html(status_key)}</strong></div>
              <div class="detail-item"><span>소유/공간</span><strong>{html.escape(context["owner"])} · {html.escape(context["scope"])}</strong></div>
              <div class="detail-item"><span>팀</span><strong>{html.escape(context["team"])}</strong></div>
              <div class="detail-item"><span>크기/수정일</span><strong>{format_size(stat.st_size)} · {format_mtime(target)}</strong></div>
              <div class="detail-item"><span>현재 경로</span><code>{html.escape(rel_path)}</code></div>
            </div>
            <div>
              <strong class="detail-section-title">최근 작업</strong>
              <ul class="activity-list">{''.join(activity_items)}</ul>
              {self.status_form_html(root, rel_path, status_key)}
            </div>
          </div>
        </details>"""

    def view_file(self, user: dict, query: dict):
        root_id = query.get("root", [""])[0]
        rel_path = query.get("path", [""])[0]
        q = query.get("q", [""])[0].strip()
        type_filter = query.get("type", [""])[0].strip()
        status_filter = query.get("status", [""])[0].strip()
        date_from = normalize_date_filter(query.get("date_from", [""])[0])
        date_to = normalize_date_filter(query.get("date_to", [""])[0])
        sort_key = query.get("sort", ["name"])[0].strip() or "name"
        msg = query.get("msg", [""])[0].strip()
        try:
            xlsx_sheet = int(query.get("sheet", ["0"])[0])
        except (TypeError, ValueError):
            xlsx_sheet = 0
        valid_filters = {key for key, _label in TYPE_FILTERS}
        if type_filter not in valid_filters:
            type_filter = ""
        if status_filter not in FILE_STATUS_LABELS:
            status_filter = ""
        valid_sorts = {key for key, _label in SORT_OPTIONS}
        if sort_key not in valid_sorts:
            sort_key = "name"
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if not root or not target or not target.exists() or not target.is_file():
            self.audit_event(user, "permission_denied", root, rel_path, target, status="denied", reason="view_file")
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>허용되지 않은 파일입니다.</p></div>", 403, user.get("name"))
            return
        self.audit_event(user, "preview_open", root, rel_path, target, file_size=target.stat().st_size)
        parent = posixpath.dirname(rel_path)
        root_q = urllib.parse.quote(root_id)
        rel_q = urllib.parse.quote(rel_path)
        state_params = listing_state_params(q, type_filter, status_filter, date_from, date_to, sort_key)
        folder_params = {"root": root_id, "path": "" if parent == "." else parent, **state_params}
        folder_url = portal_url("/browse", folder_params)
        preview_body = self.file_preview_body(
            root,
            target,
            rel_path,
            include_folder_link=False,
            show_toolbar=False,
            show_heading=False,
            xlsx_sheet=xlsx_sheet,
            xlsx_route="/view",
            state_params=state_params,
        )
        _type_key, type_label, type_token = file_type_info(target, False)
        file_meta = f"{html.escape(root['label'])} · {html.escape(type_label)} · {format_size(target.stat().st_size)} · {format_mtime(target)}"
        scope_banner = self.file_scope_banner_html(user, root, rel_path, target.name)
        share_primary_action = ""
        if root.get("id") == "personal" and can_archive_personal_path(root, rel_path):
            share_primary_action = self.quick_share_button_html(root, rel_path, target.name, shared_move_plan(rel_path, target.name))
        download_class = "button" if share_primary_action else "button primary"
        manage_action = self.manage_menu_html(root, rel_path, target.name)
        archive_action = self.archive_delete_form(root, rel_path, small=False)
        secondary_actions = f"""<div class="viewer-secondary-actions">
          <a class="button" href="{html.escape(folder_url, quote=True)}">폴더 열기</a>
          {manage_action}
          {archive_action}
        </div>"""
        share_callout = self.share_callout_html(root, rel_path, target.name)
        detail_panel = self.file_detail_panel_html(user, root, target, rel_path)
        notice = operation_notice_html(msg)
        body = f"""<div class="viewer-shell">
          <section class="viewer-main">
            <div class="viewer-topbar">
              <div class="viewer-heading">
                <span class="file-icon kind-{_type_key}" aria-hidden="true">{html.escape(type_token)}</span>
                <div class="viewer-title">
                  <strong>{html.escape(target.name)}</strong>
                  <span>{html.escape(rel_path)} · {file_meta}</span>
                  {scope_banner}
                </div>
              </div>
              <div class="viewer-actions">
                {share_primary_action}
                <a class="{download_class}" href="/download?root={root_q}&path={rel_q}">다운로드</a>
              </div>
            </div>
            {notice}
            {secondary_actions}
            {share_callout}
            {detail_panel}
            <div class="viewer-canvas">{preview_body}</div>
          </section>
        </div>"""
        self.send_html("파일 보기", body, user_name=user.get("name", user["username"]))
