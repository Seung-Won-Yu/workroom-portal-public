#!/usr/bin/env python3
import html
from pathlib import Path
import posixpath
import urllib.parse

from workroom.core.scopes import (
    SORT_OPTIONS,
    TYPE_FILTERS,
    breadcrumb_html,
    can_archive_personal_path,
    confirm_onsubmit,
    date_filter_bounds,
    file_status_key,
    file_type_info,
    format_mtime,
    format_size,
    listing_state_params,
    normalize_date_filter,
    normalized_rel_path,
    operation_notice_html,
    personal_upload_dir_key,
    root_badge_html,
    safe_name,
    search_key,
    shared_move_plan,
    summarize_workspace,
    summary_last_activity,
)
from workroom.core.settings import (
    FILE_STATUS_LABELS,
    HIDDEN_DIR_NAMES,
    MAX_UPLOAD_BYTES,
    PERSONAL_UPLOAD_DIRS,
    PERSONAL_UPLOAD_HINTS,
    SHARED_MOVE_TARGETS,
)
from workroom.core.urls import portal_url


class FileBrowseMixin:
    def list_controls_html(
        self,
        root_id: str,
        rel_path: str,
        q: str,
        type_filter: str,
        status_filter: str,
        date_from: str,
        date_to: str,
        sort_key: str,
    ) -> str:
        base_params = {"root": root_id, "path": "" if rel_path == "." else rel_path}
        reset_url = portal_url("/browse", base_params)
        sort_options = []
        for key, label in SORT_OPTIONS:
            selected = " selected" if key == sort_key else ""
            sort_options.append(f'<option value="{html.escape(key, quote=True)}"{selected}>{html.escape(label)}</option>')
        status_options = ['<option value="">모든 상태</option>']
        for key, label in FILE_STATUS_LABELS.items():
            selected = " selected" if key == status_filter else ""
            status_options.append(f'<option value="{html.escape(key, quote=True)}"{selected}>{html.escape(label)}</option>')
        chips = []
        for key, label in TYPE_FILTERS:
            params = {
                **base_params,
                **listing_state_params(q, key, status_filter, date_from, date_to, sort_key),
            }
            chip_url = portal_url("/browse", params)
            active = " active" if key == type_filter else ""
            chips.append(f'<a class="filter-chip{active}" href="{html.escape(chip_url, quote=True)}">{html.escape(label)}</a>')
        return f"""<div class="list-controls">
          <div class="list-controls-head">
            <strong>파일 찾기</strong>
          </div>
          <form class="list-search" method="get" action="/browse">
            <input type="hidden" name="root" value="{html.escape(root_id, quote=True)}">
            <input type="hidden" name="path" value="{html.escape('' if rel_path == '.' else rel_path, quote=True)}">
            <input type="hidden" name="type" value="{html.escape(type_filter, quote=True)}">
            <label class="list-field search-field">검색어
              <input class="search-input" type="search" name="q" value="{html.escape(q, quote=True)}" placeholder="파일명, 보고서, 코드 검색">
            </label>
            <label class="list-field">상태
              <select class="sort-select" name="status" aria-label="상태 필터">
                {''.join(status_options)}
              </select>
            </label>
            <label class="list-field">시작일
              <input type="date" name="date_from" value="{html.escape(date_from, quote=True)}" aria-label="수정 시작일">
            </label>
            <label class="list-field">종료일
              <input type="date" name="date_to" value="{html.escape(date_to, quote=True)}" aria-label="수정 종료일">
            </label>
            <label class="list-field" for="sort-select">정렬
              <select id="sort-select" class="sort-select" name="sort" aria-label="정렬 기준">
                {''.join(sort_options)}
              </select>
            </label>
            <div class="list-actions">
              <button class="button primary" type="submit">검색</button>
              <a class="button" href="{html.escape(reset_url, quote=True)}">초기화</a>
            </div>
        </form>
          <div class="filter-chips" aria-label="파일 종류 필터">{''.join(chips)}</div>
        </div>"""

    def archive_delete_form(self, root: dict, rel_path: str, label: str = "보관함으로 이동", small: bool = True) -> str:
        if not can_archive_personal_path(root, rel_path):
            return ""
        button_class = "button danger-button"
        if small:
            button_class += " small"
        target_name = Path(normalized_rel_path(rel_path)).name or normalized_rel_path(rel_path)
        confirm = confirm_onsubmit(f"'{target_name}' 항목을 개인 작업공간의 보관함으로 이동합니다. 실제 삭제는 아니며 관리자가 복구할 수 있습니다. 계속할까요?")
        return f"""<form class="inline-form" method="post" action="/archive_delete" {confirm}>
          {self.csrf_input()}
          <input type="hidden" name="root" value="{html.escape(root['id'], quote=True)}">
          <input type="hidden" name="path" value="{html.escape(rel_path, quote=True)}">
          <button class="{button_class}" type="submit">{html.escape(label)}</button>
        </form>"""

    def shared_target_options_html(self, selected_target: str) -> str:
        options = []
        for value, label in SHARED_MOVE_TARGETS.items():
            selected = " selected" if value == selected_target else ""
            options.append(f'<option value="{html.escape(value, quote=True)}"{selected}>{html.escape(label)}</option>')
        return "".join(options)

    def share_action_form_html(self, root: dict, rel_path: str, name: str, plan: dict[str, str], compact: bool = False) -> str:
        select_id = f"{'quick-share' if compact else 'share'}-{html.escape(rel_path, quote=True)}"
        hint = "" if compact else f"""<p class="form-hint">{html.escape(plan["reason"])}</p>
              <p class="destination-preview">이동 후 위치: {html.escape(plan["destination"])}</p>"""
        confirm = confirm_onsubmit(
            f"'{name}' 항목을 팀 공유공간으로 이동합니다. 이동 후 위치: {plan['destination']}. "
            "이동 후에는 개인 작업공간 목록에서 사라지고, 같은 팀원이 볼 수 있습니다. 계속할까요?"
        )
        return f"""<form class="{'share-action-form' if compact else 'mini-form'}" method="post" action="/move_to_shared" {confirm}>
          {self.csrf_input()}
          <input type="hidden" name="root" value="{html.escape(root['id'], quote=True)}">
          <input type="hidden" name="path" value="{html.escape(rel_path, quote=True)}">
          <label for="{select_id}">공유 위치
            <select id="{select_id}" name="shared_target">{self.shared_target_options_html(plan["target"])}</select>
          </label>
          <button class="button primary" type="submit">팀 공유로 이동</button>
          {hint}
        </form>"""

    def quick_share_button_html(self, root: dict, rel_path: str, name: str, plan: dict[str, str]) -> str:
        confirm = confirm_onsubmit(
            f"'{name}' 항목을 팀 공유공간으로 이동합니다. 이동 후 위치: {plan['destination']}. "
            "이동 후에는 개인 작업공간 목록에서 사라지고, 같은 팀원이 볼 수 있습니다. 계속할까요?"
        )
        return f"""<form class="inline-form" method="post" action="/move_to_shared" {confirm}>
          {self.csrf_input()}
          <input type="hidden" name="root" value="{html.escape(root['id'], quote=True)}">
          <input type="hidden" name="path" value="{html.escape(rel_path, quote=True)}">
          <input type="hidden" name="shared_target" value="{html.escape(plan["target"], quote=True)}">
          <button class="button primary" type="submit">팀 공유로 이동</button>
        </form>"""

    def share_callout_html(self, root: dict, rel_path: str, name: str) -> str:
        if root.get("id") == "team_shared":
            return """<section class="share-callout shared" aria-label="팀 공유 상태">
              <div>
                <strong>팀 공유공간에 있는 파일입니다</strong>
                <p>같은 팀원이 함께 확인할 수 있습니다. 수정 요청이나 검토 상태는 파일 상태에서 남겨두세요.</p>
              </div>
            </section>"""
        if not can_archive_personal_path(root, rel_path):
            return ""
        plan = shared_move_plan(rel_path, name)
        return f"""<section class="share-callout" aria-label="팀 공유 안내">
          <div>
            <strong>팀과 공유할 준비가 됐나요?</strong>
            <p>검토가 끝난 파일만 팀 공유공간으로 이동하세요.</p>
            <p class="share-destination">추천 위치: {html.escape(plan["target_label"])} · {html.escape(plan["reason"])}</p>
            <p class="destination-preview">이동 후 위치: {html.escape(plan["destination"])}</p>
          </div>
          {self.share_action_form_html(root, rel_path, name, plan, compact=True)}
        </section>"""

    def manage_menu_html(self, root: dict, rel_path: str, name: str) -> str:
        if not can_archive_personal_path(root, rel_path):
            return ""
        rename_confirm = confirm_onsubmit(f"'{name}' 항목의 이름을 변경합니다. 기존 링크나 보고서에서 쓰던 파일명과 달라질 수 있습니다. 계속할까요?")
        return f"""<details class="manage-menu">
          <summary class="button">이름 변경</summary>
          <div class="manage-panel">
            <form class="mini-form" method="post" action="/rename_item" {rename_confirm}>
              <h3>이름 변경</h3>
              {self.csrf_input()}
              <input type="hidden" name="root" value="{html.escape(root['id'], quote=True)}">
              <input type="hidden" name="path" value="{html.escape(rel_path, quote=True)}">
              <label for="rename-{html.escape(rel_path, quote=True)}">새 이름</label>
              <div class="form-row">
                <input id="rename-{html.escape(rel_path, quote=True)}" name="new_name" value="{html.escape(name, quote=True)}" required>
                <button class="button primary" type="submit">변경</button>
              </div>
            </form>
          </div>
        </details>"""

    def upload_form_html(self, root: dict, rel_path: str) -> str:
        if root.get("id") != "personal":
            return ""
        normalized = "" if rel_path == "." else rel_path
        upload_key = personal_upload_dir_key(normalized)
        if not upload_key:
            return self.upload_location_guide_html(root)
        upload_label = PERSONAL_UPLOAD_DIRS[upload_key]
        return f"""<form class="upload-panel" method="post" action="/upload_file" enctype="multipart/form-data">
          <strong>{html.escape(upload_label)}에 업로드</strong>
          <span class="upload-location">저장 위치: 개인 작업공간 / {html.escape(upload_label)}</span>
          {self.csrf_input()}
          <input type="hidden" name="root" value="{html.escape(root['id'], quote=True)}">
          <input type="hidden" name="path" value="{html.escape(normalized, quote=True)}">
          <input type="file" name="file" required>
          <button class="button primary" type="submit">업로드</button>
          <span class="upload-hint">최대 {format_size(MAX_UPLOAD_BYTES)}. 실행 파일과 설치 파일은 업로드할 수 없습니다. 업로드 후 파일 상세 화면에서 확인하고 필요한 것만 팀 공유로 이동하세요.</span>
        </form>"""

    def upload_location_guide_html(self, root: dict) -> str:
        if root.get("id") != "personal":
            return ""
        root_q = urllib.parse.quote(root["id"])
        links = []
        for folder, label in PERSONAL_UPLOAD_DIRS.items():
            url = f"/browse?root={root_q}&path={urllib.parse.quote(folder)}"
            links.append(
                f"""<a class="upload-target" href="{html.escape(url, quote=True)}">
                  <strong>{html.escape(label)}</strong>
                  <span>{html.escape(PERSONAL_UPLOAD_HINTS.get(folder, ""))}</span>
                  <em>열기</em>
                </a>"""
            )
        return f"""<section class="upload-panel upload-guide" aria-label="업로드 위치 안내">
          <strong>업로드 위치 선택</strong>
          <span class="upload-hint">파일을 올릴 위치를 선택하세요. 파일 성격에 맞는 위치를 먼저 열고, 검토가 끝난 파일만 팀 공유로 이동하세요. 팀 공유공간에는 직접 업로드하지 않습니다.</span>
          <div class="upload-targets">{''.join(links)}</div>
        </section>"""

    def shared_workspace_notice_html(self, root: dict, rel_path: str) -> str:
        if root.get("id") != "team_shared":
            return ""
        root_q = urllib.parse.quote(str(root["id"]))
        root_path = Path(root["path"]).resolve()
        summary = summarize_workspace(root_path, exclude_selftests=True)
        rel = "" if rel_path == "." else normalized_rel_path(rel_path)
        if not rel:
            links = []
            for folder, label in SHARED_MOVE_TARGETS.items():
                folder_path = root_path / folder
                folder_summary = summarize_workspace(folder_path, exclude_selftests=True)
                links.append(
                    f"""<a class="shared-target-card" href="/browse?root={root_q}&path={urllib.parse.quote(folder)}">
                      <strong>{html.escape(label)}</strong>
                      <span>{int(folder_summary["files"]):,}개 파일</span>
                    </a>"""
                )
            return f"""<section class="shared-workspace-panel" aria-label="팀 공유공간 안내">
              <div class="shared-workspace-top">
                <div>
                  <h3>팀 공유공간</h3>
                  <p>개인 작업공간에서 팀 공유로 이동한 산출물을 팀원이 함께 확인하는 공간입니다. 여기서는 직접 업로드하지 않고, 공유된 파일을 보기 또는 원본 다운로드로 확인합니다.</p>
                </div>
                <div class="home-summary-pills">
                  <span class="home-summary-pill">공유 파일 <strong>{int(summary["files"]):,}개</strong></span>
                  <span class="home-summary-pill">최근 공유 <strong>{html.escape(summary_last_activity(summary))}</strong></span>
                </div>
              </div>
              <div class="shared-target-grid">{''.join(links)}</div>
            </section>"""
        first = rel.split("/", 1)[0]
        label = SHARED_MOVE_TARGETS.get(first, "팀 공유")
        return f"""<section class="shared-workspace-panel" aria-label="팀 공유공간 안내">
          <div class="shared-workspace-top">
            <div>
              <h3>{html.escape(label)}</h3>
              <p>팀원이 함께 보는 공유 폴더입니다. 개인 작업공간에서 검토 후 이동된 파일만 모이며, 필요한 파일은 보기 또는 원본 다운로드로 확인합니다.</p>
            </div>
            <a class="button" href="/browse?root={root_q}">팀 공유 전체</a>
          </div>
        </section>"""

    def file_list_html(
        self,
        root: dict,
        folder: Path,
        current_file_rel: str = "",
        q: str = "",
        type_filter: str = "",
        status_filter: str = "",
        date_from: str = "",
        date_to: str = "",
        sort_key: str = "name",
        show_actions: bool = False,
        nav_only: bool = False,
    ) -> str:
        root_path = Path(root["path"]).resolve()
        root_q = urllib.parse.quote(root["id"])
        rows = []
        nav_rows = []
        needle = search_key(q.strip())
        date_start, date_end = date_filter_bounds(date_from, date_to)
        try:
            raw_entries = list(folder.iterdir())
        except OSError:
            raw_entries = []

        entries = []
        for entry in raw_entries:
            try:
                entry_rel = entry.relative_to(root_path)
            except ValueError:
                continue
            if entry.name in HIDDEN_DIR_NAMES or not safe_name(entry_rel):
                continue
            type_key, type_label, type_token = file_type_info(entry, entry.is_dir())
            if needle and needle not in search_key(entry.name):
                continue
            if type_filter and type_key != type_filter:
                continue
            try:
                stat = entry.stat()
                mtime = stat.st_mtime
                byte_size = 0 if entry.is_dir() else stat.st_size
            except OSError:
                mtime = 0
                byte_size = 0
            if date_start is not None and mtime < date_start:
                continue
            if date_end is not None and mtime > date_end:
                continue
            status_key = ""
            if entry.is_dir():
                if status_filter:
                    continue
            else:
                status_key = file_status_key(root, entry_rel.as_posix(), self.portal.events_for_target(entry, limit=12))
                if status_filter and status_key != status_filter:
                    continue
            entries.append((entry, entry_rel, type_key, type_label, type_token, mtime, byte_size, status_key))

        if sort_key == "modified":
            entries.sort(key=lambda item: (not item[0].is_dir(), -item[5], item[0].name.lower()))
        elif sort_key == "size":
            entries.sort(key=lambda item: (not item[0].is_dir(), -item[6], item[0].name.lower()))
        elif sort_key == "type":
            entries.sort(key=lambda item: (not item[0].is_dir(), item[2], item[0].name.lower()))
        else:
            entries.sort(key=lambda item: (not item[0].is_dir(), item[0].name.lower()))

        state_params = listing_state_params(q, type_filter, status_filter, date_from, date_to, sort_key)

        for entry, entry_rel, type_key, type_label, type_token, _mtime, byte_size, status_key in entries:
            rel_s = entry_rel.as_posix()
            rel_q = urllib.parse.quote(rel_s)
            is_dir = entry.is_dir()
            name = f"{entry.name}/" if is_dir else entry.name
            size = "-" if is_dir else format_size(byte_size)
            if is_dir:
                open_url = portal_url("/browse", {"root": root["id"], "path": rel_s, **state_params})
            else:
                if root.get("id") == "all":
                    open_url = portal_url("/app", {"root": root["id"], "file": rel_s, **state_params})
                else:
                    open_url = portal_url("/view", {"root": root["id"], "path": rel_s, **state_params})
            open_href = html.escape(open_url, quote=True)
            row_class = "file-row selected-row" if (not is_dir and rel_s == current_file_rel) else "file-row"
            nav_current = ' aria-current="page"' if (not is_dir and rel_s == current_file_rel) else ""
            open_label = "열기" if is_dir else "보기"
            download_label = "폴더 다운로드" if is_dir else "원본 다운로드"
            status_html = '<span class="muted">-</span>' if is_dir else self.status_pill_html(status_key)
            submeta_html = ""
            if rel_s != entry.name:
                submeta_html = f'<span class="file-submeta">{html.escape(rel_s)}</span>'
            nav_rows.append(
                f"""<a class="viewer-file-link {row_class}" href="{open_href}" title="{html.escape(rel_s, quote=True)}"{nav_current}>
                  <span class="file-icon kind-{type_key}" aria-hidden="true">{html.escape(type_token)}</span>
                  <span class="file-name-wrap">
                    <span class="file-name">{html.escape(name)}</span>
                  </span>
                </a>"""
            )
            archive_action = self.archive_delete_form(root, rel_s)
            actions_html = ""
            if show_actions:
                actions_html = f"""
                  <td>
                    <div class="file-actions">
                      <a class="button small" href="{open_href}">{open_label}</a>
                      <a class="button small" href="/download?root={root_q}&path={rel_q}">{download_label}</a>
                      {archive_action}
                    </div>
                  </td>"""
            rows.append(
                f"""<tr class="{row_class}">
                  <td class="name-cell">
                    <a class="file-main" href="{open_href}" title="{html.escape(rel_s, quote=True)}">
                      <span class="file-icon kind-{type_key}" aria-hidden="true">{html.escape(type_token)}</span>
                      <span class="file-name-wrap">
                        <span class="file-name">{html.escape(name)}</span>
                        {submeta_html}
                      </span>
                    </a>
                  </td>
                  <td><span class="type-badge kind-{type_key}">{html.escape(type_label)}</span></td>
                  <td>{status_html}</td>
                  <td>{size}</td>
                  <td>{format_mtime(entry)}</td>
                  {actions_html}
                </tr>"""
            )
        if not rows:
            if needle or type_filter or status_filter or date_from or date_to:
                return '<div class="empty-state"><p>검색 조건에 맞는 파일이 없습니다.</p><p class="muted">검색어, 파일 종류, 상태 또는 수정일 필터를 조정해보세요.</p></div>'
            if root.get("id") == "personal":
                return '<div class="empty-state"><p>이 개인 폴더는 비어 있습니다.</p><p class="muted">파일을 업로드하거나 Hermes 봇이 만든 산출물이 저장되면 여기에 나타납니다.</p></div>'
            if root.get("id") == "team_shared":
                return '<div class="empty-state"><p>아직 팀 공유 파일이 없습니다.</p><p class="muted">개인 작업공간에서 팀과 공유하기로 한 산출물이 여기에 모입니다.</p></div>'
            return '<div class="empty-state"><p>이 위치에는 아직 표시할 파일이 없습니다.</p><p class="muted">하위 작업공간을 열거나 검색 조건을 조정해보세요.</p></div>'
        if nav_only:
            return f"""<nav class="viewer-file-nav" aria-label="현재 폴더 파일">
              {''.join(nav_rows)}
            </nav>"""
        actions_header = "<th>작업</th>" if show_actions else ""
        return f"""<table class="file-table">
          <thead><tr><th>이름</th><th>종류</th><th>상태</th><th>크기</th><th>수정일</th>{actions_header}</tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>"""

    def browse(self, user: dict, query: dict):
        root_id = query.get("root", [""])[0]
        rel_path = query.get("path", [""])[0]
        selected_rel = query.get("selected", [""])[0]
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
        if selected_rel:
            params = {"root": root_id, "path": selected_rel, **listing_state_params(q, type_filter, status_filter, date_from, date_to, sort_key)}
            self.redirect(portal_url("/view", params))
            return
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if not root or not target or not target.exists() or not target.is_dir():
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>허용되지 않은 폴더입니다.</p></div>", 403, user.get("name"))
            return
        root_q = urllib.parse.quote(root_id)
        rel = target.relative_to(Path(root["path"]).resolve()).as_posix()
        parent_link = ""
        state_params = listing_state_params(q, type_filter, status_filter, date_from, date_to, sort_key)
        if rel != ".":
            parent = posixpath.dirname(rel)
            parent_url = portal_url("/browse", {"root": root_id, "path": "" if parent == "." else parent, **state_params})
            parent_link = f'<a class="button" href="{html.escape(parent_url, quote=True)}">상위 폴더</a>'
        title_path = "/" if rel == "." else "/" + rel
        file_list_html = self.file_list_html(
            root,
            target,
            q=q,
            type_filter=type_filter,
            status_filter=status_filter,
            date_from=date_from,
            date_to=date_to,
            sort_key=sort_key,
        )
        folder_title = f"""<div class="section-title">
          <h2>{html.escape(root['label'])} {html.escape(title_path)}</h2>
          {root_badge_html(root)}
        </div>"""
        if root.get("id") == "team_shared":
            folder_summary = "팀원이 함께 확인하는 공유공간입니다. 필요한 파일은 바로 열거나 원본으로 다운로드하세요."
        elif root.get("id") == "personal":
            folder_summary = "개인 작업공간입니다. 산출물을 먼저 확인하고, 검토가 끝난 파일만 팀 공유로 이동하세요."
        elif user.get("username") == "admin":
            folder_summary = "관리자 전체 작업공간입니다. 사용자와 팀 공유 위치를 확인하고 필요한 파일을 추적합니다."
        else:
            folder_summary = "파일과 산출물을 확인하는 작업공간입니다."
        folder_toolbar = f"""<div class="toolbar folder-actions">
          <a class="button" href="/">홈</a>
          {parent_link}
          <a class="button" href="/download?root={root_q}&path={urllib.parse.quote('' if rel == '.' else rel)}">현재 폴더 다운로드</a>
        </div>"""
        notice = operation_notice_html(
            msg,
            {key: query.get(key, [""])[0] for key in ("archived_name", "archived_path", "archived_at", "archived_by")},
        )
        upload_form = self.upload_form_html(root, rel)
        shared_notice = self.shared_workspace_notice_html(root, rel)

        body = f"""<section class="folder-view">
          <div class="folder-hero">
            <div class="folder-hero-main">
              {breadcrumb_html(root, rel, root_id)}
              {folder_title}
              <p class="folder-summary">{html.escape(folder_summary)}</p>
            </div>
            {folder_toolbar}
          </div>
          {notice}
          {shared_notice}
          {upload_form}
          {self.list_controls_html(root_id, rel, q, type_filter, status_filter, date_from, date_to, sort_key)}
          <div class="file-list">{file_list_html}</div>
        </section>"""
        self.send_html("폴더 보기", body, user_name=user.get("name", user["username"]))
