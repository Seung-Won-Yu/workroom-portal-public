#!/usr/bin/env python3
import secrets
import urllib.parse

from workroom.core.scopes import now_ts, verify_password
from workroom.web.ui import html_page
from workroom.core.urls import portal_url


class PortalRouterMixin:
    def query_value(self, query: dict, key: str) -> str:
        return query.get(key, [""])[0].strip()

    def redirect_to_react_folder(self, query: dict):
        params = {"root": self.query_value(query, "root")}
        selected = self.query_value(query, "selected")
        rel_path = selected or self.query_value(query, "path")
        if selected:
            params["file"] = rel_path
        elif rel_path:
            params["path"] = rel_path
        for key in ("q", "type", "status", "date_from", "date_to", "sort", "msg", "archived_name", "archived_path", "archived_at", "archived_by"):
            value = self.query_value(query, key)
            if value:
                params[key] = value
        self.redirect(portal_url("/app", params))

    def redirect_to_react_admin(self, view: str, query: dict):
        params = {"view": view, "root": "all"}
        for key in ("q", "type", "status", "owner", "team", "scope", "sort", "actor", "action", "username", "msg"):
            value = self.query_value(query, key)
            if value:
                params[key] = value
        self.redirect(portal_url("/app", params))

    def require_admin_user(self) -> dict | None:
        user = self.require_user()
        if not user:
            return None
        if user.get("username") != "admin":
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>관리자만 볼 수 있는 화면입니다.</p></div>", 403, user.get("name"))
            return None
        return user

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path
        if path.startswith("/api/"):
            self.handle_api_get(path, query)
            return
        if path.startswith("/static/"):
            self.send_static_asset(path)
            return
        if path == "/health":
            self.send_health()
        elif path in {"/", "/app"}:
            user = self.require_user()
            if user:
                self.send_react_app()
        elif path == "/login":
            self.login_page()
        elif path == "/logout":
            user = self.current_user()
            if user:
                self.audit_event(user, "logout")
            self.send_response(303)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", self.session_cookie_header("", 0))
            self.end_headers()
        elif path == "/legacy":
            if self.require_user():
                self.redirect("/app")
        elif path == "/admin":
            if self.require_admin_user():
                self.redirect_to_react_admin("admin-overview", query)
        elif path == "/admin/archive":
            if self.require_admin_user():
                self.redirect_to_react_admin("admin-archive", query)
        elif path == "/admin/archive/view":
            user = self.require_user()
            if user:
                self.admin_archive_view(user, query)
        elif path == "/admin/archive/preview":
            user = self.require_user()
            if user:
                self.admin_archive_preview(user, query)
        elif path == "/admin/archive/download":
            user = self.require_user()
            if user:
                self.admin_archive_download(user, query)
        elif path == "/admin/archive/raw":
            user = self.require_user()
            if user:
                self.admin_archive_raw(user, query)
        elif path == "/admin/archive/pdf_page":
            user = self.require_user()
            if user:
                self.admin_archive_pdf_page(user, query)
        elif path == "/admin/archive/converted_page":
            user = self.require_user()
            if user:
                self.admin_archive_converted_page(user, query)
        elif path == "/admin/archive/thumbnail":
            user = self.require_user()
            if user:
                self.admin_archive_thumbnail(user, query)
        elif path == "/admin/activity":
            if self.require_admin_user():
                self.redirect_to_react_admin("admin-activity", query)
        elif path == "/admin/search":
            if self.require_admin_user():
                self.redirect_to_react_admin("admin-search", query)
        elif path == "/admin/user":
            if self.require_admin_user():
                self.redirect_to_react_admin("admin-user", query)
        elif path == "/browse":
            if self.require_user():
                self.redirect_to_react_folder(query)
        elif path == "/view":
            user = self.require_user()
            if user:
                self.view_file(user, query)
        elif path == "/preview":
            user = self.require_user()
            if user:
                self.preview_file(user, query)
        elif path == "/converted":
            user = self.require_user()
            if user:
                self.converted_file(user, query)
        elif path == "/pdf_page":
            user = self.require_user()
            if user:
                self.pdf_page(user, query)
        elif path == "/converted_page":
            user = self.require_user()
            if user:
                self.converted_page(user, query)
        elif path == "/raw":
            user = self.require_user()
            if user:
                self.raw_file(user, query)
        elif path == "/asset":
            user = self.require_user()
            if user:
                self.asset_file(user, query)
        elif path.startswith("/asset_path/"):
            user = self.require_user()
            if user:
                self.asset_path_file(user, path)
        elif path == "/thumbnail":
            user = self.require_user()
            if user:
                self.thumbnail(user, query)
        elif path == "/download":
            user = self.require_user()
            if user:
                self.download(user, query)
        else:
            self.send_html("찾을 수 없음", "<div class='card'><h2>404</h2><p>없는 경로입니다.</p></div>", 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_post(parsed.path)
            return
        if parsed.path == "/upload_file":
            user = self.require_user()
            if user:
                self.upload_file(user)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_html("잘못된 요청", "<div class='card'><h2>잘못된 요청</h2><p>요청 길이가 올바르지 않습니다.</p></div>", 400)
            return
        if length < 0:
            self.send_html("잘못된 요청", "<div class='card'><h2>잘못된 요청</h2><p>요청 길이가 올바르지 않습니다.</p></div>", 400)
            return
        data = self.rfile.read(length).decode("utf-8")
        form = urllib.parse.parse_qs(data)

        if parsed.path == "/archive_delete":
            user = self.require_user()
            if user and self.verify_csrf_form(user, form):
                self.archive_delete(user, form)
            return
        if parsed.path == "/rename_item":
            user = self.require_user()
            if user and self.verify_csrf_form(user, form):
                self.rename_item(user, form)
            return
        if parsed.path == "/move_to_shared":
            user = self.require_user()
            if user and self.verify_csrf_form(user, form):
                self.move_to_shared(user, form)
            return
        if parsed.path == "/set_file_status":
            user = self.require_user()
            if user and self.verify_csrf_form(user, form):
                self.set_file_status(user, form)
            return
        if parsed.path == "/restore_archive":
            user = self.require_user()
            if user and self.verify_csrf_form(user, form):
                self.restore_archive(user, form)
            return

        if parsed.path != "/login":
            self.send_html("찾을 수 없음", "<div class='card'><h2>404</h2><p>없는 경로입니다.</p></div>", 404)
            return
        username = form.get("username", [""])[0].strip()
        password = form.get("password", [""])[0]
        audit_user = {"username": username or "-", "name": username or "-"}
        client_ip, _client_ip_source = self.request_client_ip()
        if self.portal.login_limited(client_ip, username):
            self.audit_event(audit_user, "login_rate_limited", status="denied", reason="too_many_failures")
            self.login_page("로그인 실패가 많아 10분간 보호 제한이 걸렸습니다. 10분 후 다시 시도하거나 관리자에게 비밀번호 초기화를 요청하세요.", status=429)
            return
        user = self.portal.user(username)
        if not user or user.get("disabled") or not verify_password(password, user.get("password_hash", "")):
            self.portal.record_login_failure(client_ip, username)
            self.audit_event(audit_user, "login_failed", status="denied", reason="bad_credentials")
            self.login_page("아이디 또는 비밀번호가 맞지 않습니다. 비밀번호가 기억나지 않으면 관리자에게 아이디와 현재 접속 주소를 보내 초기화를 요청하세요.")
            return
        self.portal.clear_login_failures(client_ip, username)
        token = self.portal.sign({"u": username, "exp": now_ts() + 60 * 60 * 12, "csrf": secrets.token_urlsafe(32)})
        self.audit_event(user, "login_success")
        self.send_response(303)
        self.send_header("Location", "/app")
        self.send_header("Set-Cookie", self.session_cookie_header(token, 60 * 60 * 12))
        self.end_headers()

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/static/"):
            self.send_static_asset(parsed.path, include_body=False)
            return
        if parsed.path == "/health":
            self.send_health(include_body=False)
            return
        if parsed.path in {"/", "/app"}:
            if self.current_user():
                self.send_react_app(include_body=False)
            else:
                self.send_response(303)
                self.send_header("Location", "/login")
                self.end_headers()
            return
        if parsed.path == "/login":
            if self.current_user():
                self.send_response(303)
                self.send_header("Location", "/app")
                self.end_headers()
                return
            data = html_page("로그인", "", None)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()
