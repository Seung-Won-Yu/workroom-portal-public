#!/usr/bin/env python3
import datetime as dt
import html
import os
from pathlib import Path
import urllib.parse

from portal_core import (
    file_status_key,
    file_type_info,
    format_size,
    is_operational_recent_path,
    root_badge_html,
    root_by_id,
    root_type_info,
    safe_name,
    summarize_workspace,
    summary_last_activity,
)
from portal_settings import (
    FILE_STATUS_LABELS,
    HIDDEN_DIR_NAMES,
    MAX_RECENT_FILES,
    MAX_SCAN_FILES,
    PERSONAL_UPLOAD_DIRS,
    PERSONAL_UPLOAD_HINTS,
)


class UserViewsMixin:
    def login_page(self, error: str = "", status: int = 200):
        if status == 200 and not error and self.current_user():
            self.redirect("/app")
            return
        error_html = f"""
              <div class="login-error" role="alert">
                {html.escape(error)}
              </div>
        """ if error else ""
        body = f"""
        <section class="login">
          <aside class="login-stage">
            <div class="login-brand">
              <div class="mark">e.</div>
              <div class="name">
                <strong>Workroom Portal</strong>
                <span>에이전트 산출물 포털</span>
              </div>
            </div>

            <div class="login-headline">
              <span class="eyebrow">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>
                디스코드 에이전트 산출물 포털
              </span>
              <h1>에이전트가 만든 파일을<br>한 곳에서 확인하고 정리하세요.</h1>
              <p>내 작업공간의 리서치, 개발 산출물, 요약 보고를 빠르게 열어보고 필요한 결과만 팀 공유공간으로 넘깁니다.</p>
            </div>

            <div class="login-footer">
              <span>© 2026 Workroom · 사내 전용</span>
            </div>
          </aside>

          <main class="login-form-area">
            <form class="login-card" method="post" action="/login">
              <div>
                <h2>다시 만나서 반가워요</h2>
                <p class="sub">직원 원격 작업 포털에 관리자에게 받은 아이디와 비밀번호로 로그인하세요.</p>
              </div>

              <div class="login-fields">
                <div class="login-field">
                  <label for="username">아이디</label>
                  <div class="input-wrap">
                    <svg class="left" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 21a8 8 0 0 0-16 0"/><circle cx="12" cy="7" r="4"/></svg>
                    <input id="username" name="username" autocomplete="username" placeholder="예: user1" required>
                  </div>
                </div>

                <div class="login-field">
                  <label for="password">비밀번호</label>
                  <div class="input-wrap">
                    <svg class="left" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>
                    <input id="password" name="password" type="password" autocomplete="current-password" placeholder="••••••••" required>
                  </div>
                </div>
              </div>

              <div class="login-row">
                <label>
                  <input type="checkbox" name="remember" checked>
                  로그인 상태 유지
                </label>
              </div>

              {error_html}

              <button type="submit" class="login-submit">
                로그인
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
              </button>

              <div class="login-meta" id="login-help" aria-label="로그인 도움말">
                <div class="row">
                  <strong>로그인이 안 되나요?</strong>
                  <span>관리자에게 문의</span>
                </div>
                <p>비밀번호가 기억나지 않으면 관리자에게 아이디와 현재 접속 주소를 보내 초기화를 요청하세요.</p>
                <p>초기화된 임시 비밀번호는 관리자에게서 1:1로 전달받고, 로그인 후 새 비밀번호로 변경합니다.</p>
                <p>실패가 반복되면 보안을 위해 10분간 로그인이 제한됩니다.</p>
              </div>
            </form>
          </main>
        </section>
        """
        self.send_html("로그인", body, status=status)

    def home_file_table_html(self, root: dict | None, title: str, empty_text: str, limit: int = 6) -> str:
        if not root:
            return f"""<section class="home-panel">
              <div class="home-panel-head"><h3>{html.escape(title)}</h3><span>최근순</span></div>
              <div class="home-empty"><div class="empty-state compact"><p>{html.escape(empty_text)}</p></div></div>
            </section>"""
        root_id = str(root.get("id", ""))
        root_path = Path(root["path"]).resolve()
        rows = []
        for mtime, rel, size in self.recent_files_for_root(root, limit):
            rel_q = urllib.parse.quote(rel)
            view_url = f"/view?root={urllib.parse.quote(root_id)}&path={rel_q}"
            type_key, type_label, _type_token = file_type_info(Path(rel), False)
            status_key = "shared" if root_id == "team_shared" else "active"
            if root_id == "personal":
                status_key = file_status_key(root, rel, self.portal.events_for_target(root_path / rel, limit=12))
            status_label = FILE_STATUS_LABELS.get(status_key, status_key)
            rows.append(
                f"""<li class="home-work-item">
                  <div class="home-work-main">
                    <a class="home-work-name" href="{html.escape(view_url, quote=True)}">{html.escape(rel)}</a>
                    <span class="home-work-meta">
                      <span class="type-badge kind-{type_key}">{html.escape(type_label)}</span>
                      <span class="status-pill status-{html.escape(status_key, quote=True)}">{html.escape(status_label)}</span>
                      <span>{format_size(size)}</span>
                      <span>{dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")}</span>
                    </span>
                  </div>
                  <a class="button small" href="{html.escape(view_url, quote=True)}">보기</a>
                </li>"""
            )
        if not rows:
            return f"""<section class="home-panel">
              <div class="home-panel-head"><h3>{html.escape(title)}</h3><span>최근순</span></div>
              <div class="home-empty"><div class="empty-state compact"><p>{html.escape(empty_text)}</p></div></div>
            </section>"""
        return f"""<section class="home-panel">
          <div class="home-panel-head"><h3>{html.escape(title)}</h3><span>최근순</span></div>
          <ul class="home-work-list">{''.join(rows)}</ul>
        </section>"""

    def user_dashboard_overview(self, user: dict) -> str:
        personal = root_by_id(user, "personal")
        shared = root_by_id(user, "team_shared")
        personal_summary = summarize_workspace(Path(personal["path"]).resolve(), exclude_selftests=True) if personal else {
            "exists": False,
            "files": 0,
            "bytes": 0,
            "last_mtime": 0,
        }
        shared_summary = summarize_workspace(Path(shared["path"]).resolve(), exclude_selftests=True) if shared else {
            "exists": False,
            "files": 0,
            "bytes": 0,
            "last_mtime": 0,
        }
        personal_url = f"/browse?root={urllib.parse.quote(str(personal['id']))}" if personal else "#"
        shared_url = f"/browse?root={urllib.parse.quote(str(shared['id']))}" if shared else "#"
        folder_links = []
        if personal:
            root_q = urllib.parse.quote(personal["id"])
            for folder, label in PERSONAL_UPLOAD_DIRS.items():
                folder_links.append(
                    f"""<a class="home-folder-link" href="/browse?root={root_q}&path={urllib.parse.quote(folder)}">
                      <strong>{html.escape(label)}</strong>
                      <span>{html.escape(PERSONAL_UPLOAD_HINTS.get(folder, ""))}</span>
                      <em>열기</em>
                    </a>"""
                )
        if shared:
            folder_links.append(
                f"""<a class="home-folder-link" href="/browse?root={urllib.parse.quote(shared["id"])}">
                  <strong>팀 공유</strong>
                  <span>검토가 끝난 자료를 팀원이 함께 확인</span>
                  <em>열기</em>
                </a>"""
            )
        folder_links_html = "".join(folder_links) if folder_links else '<p class="muted">연결된 작업공간이 없습니다.</p>'
        summary_pills = [
            f"""<span class="home-summary-pill">내 파일 <strong>{int(personal_summary["files"]):,}개</strong></span>""",
            f"""<span class="home-summary-pill">사용량 <strong>{format_size(int(personal_summary["bytes"]))}</strong></span>""",
            f"""<span class="home-summary-pill">팀 공유 <strong>{int(shared_summary["files"]):,}개</strong></span>""",
            f"""<span class="home-summary-pill">최근 공유 <strong>{html.escape(summary_last_activity(shared_summary))}</strong></span>""",
        ]
        return f"""<section class="admin-section user-home-summary">
          <div class="home-action-hero">
            <div class="home-action-top">
              <div>
                <span class="home-kicker">직원 작업 허브</span>
                <h2>내 산출물을 찾고 팀에 공유하세요</h2>
                <p class="home-action-copy">봇이 만든 파일과 직접 올린 파일을 먼저 확인한 뒤, 필요한 파일만 다운로드하거나 팀 공유로 이동합니다.</p>
                <ul class="home-intent-list" aria-label="주요 흐름">
                  <li>최근 산출물 확인</li>
                  <li>원본 다운로드</li>
                  <li>검토 후 팀 공유</li>
                </ul>
              </div>
              <div class="home-primary-actions" aria-label="주요 작업">
                <a class="button primary" href="{html.escape(personal_url, quote=True)}">내 산출물 보기</a>
                <a class="button" href="{html.escape(shared_url, quote=True)}">팀 공유 보기</a>
              </div>
            </div>
            <div class="home-quick-panel">
              <h3>작업공간 요약</h3>
              <div class="home-summary-pills" aria-label="작업공간 요약">
                {''.join(summary_pills)}
              </div>
              <div class="home-secondary-row" aria-label="폴더 바로가기">
                {folder_links_html}
              </div>
            </div>
          </div>
          <div class="home-focus-grid">
            {self.home_file_table_html(personal, "최근 내 산출물", "아직 개인 작업공간에 표시할 산출물이 없습니다.")}
            {self.home_file_table_html(shared, "최근 팀 공유", "아직 팀 공유공간에 표시할 산출물이 없습니다.")}
          </div>
        </section>"""

    def dashboard(self, user: dict):
        roots = self.portal.roots_for(user)
        cards = []
        is_admin = user.get("username") == "admin"
        for root in roots:
            path = Path(root["path"])
            _scope_class, _scope_label, scope_description = root_type_info(root)
            path_line = f'<p class="muted path-line">{html.escape(str(path))}</p>' if is_admin else ""
            actions = [f'<a class="button primary" href="/browse?root={urllib.parse.quote(root["id"])}">열기</a>']
            if is_admin:
                actions.append(f'<a class="button" href="/download?root={urllib.parse.quote(root["id"])}">전체 다운로드</a>')
            cards.append(
                f"""<div class="card root-card">
                  <div class="card-title-row">
                    <h3>{html.escape(root["label"])}</h3>
                    {root_badge_html(root)}
                  </div>
                  <p class="root-description">{html.escape(scope_description)}</p>
                  {path_line}
                  <div class="card-actions">
                    {''.join(actions)}
                  </div>
                </div>"""
            )
        admin_link = ""
        if is_admin:
            admin_link = '<a class="button primary" href="/admin">관리자 대시보드</a>'
            body = f"""<div class="section-title">
              <h2>내 작업공간</h2>
              {admin_link}
            </div>
            <div class='grid'>{''.join(cards)}</div>"""
            body += self.recent_section(user)
        else:
            body = self.user_dashboard_overview(user)
            body += f"""<div class="section-title">
              <h2>내 작업공간</h2>
            </div>
            <div class='grid'>{''.join(cards)}</div>"""
        self.send_html("작업물 포털", body, user_name=user.get("name", user["username"]))

    def recent_section(self, user: dict) -> str:
        rows = []
        scanned = 0
        for root in self.portal.roots_for(user):
            root_path = Path(root["path"])
            if not root_path.exists():
                continue
            for current, dirs, files in os.walk(root_path):
                dirs[:] = [d for d in dirs if safe_name(Path(d)) and d not in HIDDEN_DIR_NAMES]
                for filename in files:
                    scanned += 1
                    if scanned > MAX_SCAN_FILES:
                        break
                    path = Path(current) / filename
                    try:
                        rel = path.relative_to(root_path).as_posix()
                        if not safe_name(Path(rel)):
                            continue
                        if is_operational_recent_path(root, rel):
                            continue
                        stat = path.stat()
                    except OSError:
                        continue
                    rows.append((stat.st_mtime, root, rel, stat.st_size))
                if scanned > MAX_SCAN_FILES:
                    break
        rows.sort(reverse=True, key=lambda item: item[0])
        lines = []
        for mtime, root, rel, size in rows[:MAX_RECENT_FILES]:
            root_q = urllib.parse.quote(root["id"])
            rel_q = urllib.parse.quote(rel)
            view_url = f"/view?root={root_q}&path={rel_q}"
            type_key, type_label, _type_token = file_type_info(Path(rel), False)
            lines.append(
                f"""<tr>
                  <td class="name-cell"><a href="{view_url}">{html.escape(rel)}</a></td>
                  <td><span class="root-cell">{root_badge_html(root)}<span>{html.escape(root["label"])}</span></span></td>
                  <td><span class="type-badge kind-{type_key}">{html.escape(type_label)}</span></td>
                  <td>{format_size(size)}</td>
                  <td>{dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")}</td>
                  <td class="actions">
                    <a class="button" href="{view_url}">보기</a>
                    <a class="button" href="/download?root={root_q}&path={rel_q}">원본 다운로드</a>
                  </td>
                </tr>"""
            )
        if not lines:
            return "<h2>최근 작업물</h2><div class='card'><p class='muted'>아직 표시할 파일이 없습니다.</p></div>"
        return f"""<h2>최근 작업물</h2>
        <table class="recent-table">
          <thead><tr><th>파일</th><th>공간</th><th>종류</th><th>크기</th><th>수정일</th><th>작업</th></tr></thead>
          <tbody>{''.join(lines)}</tbody>
        </table>"""
