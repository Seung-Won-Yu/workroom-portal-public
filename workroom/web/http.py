#!/usr/bin/env python3
import datetime as dt
import html
from pathlib import Path
import urllib.parse

from workroom.core.scopes import normalized_rel_path, request_client_ip, root_by_id
from workroom.core.model import Portal
from workroom.web.ui import html_page, react_app_page, static_asset_response


class PortalHttpMixin:
    @property
    def portal(self) -> Portal:
        return self.server.portal

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            return

    def finish(self):
        try:
            super().finish()
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, fmt, *args):
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        client_ip, source = self.request_client_ip()
        peer_ip = self.peer_ip()
        if source == "socket":
            print(f"{stamp} {client_ip} {fmt % args}")
        else:
            print(f"{stamp} {client_ip} via {peer_ip} {fmt % args}")

    def global_nav_html(self, user: dict | None) -> str:
        if not user:
            return ""
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path
        root_id = query.get("root", [""])[0]
        items: list[tuple[str, str, bool]] = [("워크룸", "/app", path in {"/", "/app"})]
        is_admin = user.get("username") == "admin"
        if is_admin:
            items.extend(
                [
                    ("관리자", "/admin", path == "/admin"),
                    ("전체 작업공간", "/browse?root=all", path in {"/browse", "/view"} and root_id == "all"),
                    ("전체 산출물", "/admin/search", path == "/admin/search"),
                    ("작업 기록", "/admin/activity", path == "/admin/activity"),
                ]
            )
        else:
            personal = root_by_id(user, "personal")
            shared = root_by_id(user, "team_shared")
            if personal:
                items.append(("내 산출물", f"/browse?root={urllib.parse.quote(str(personal['id']))}", path in {"/browse", "/view"} and root_id == personal["id"]))
            if shared:
                items.append(("팀 공유", f"/browse?root={urllib.parse.quote(str(shared['id']))}", path in {"/browse", "/view"} and root_id == shared["id"]))
        links = []
        for label, href, active in items:
            active_class = " active" if active else ""
            current = ' aria-current="page"' if active else ""
            links.append(f'<a class="nav-link{active_class}" href="{html.escape(href, quote=True)}"{current}>{html.escape(label)}</a>')
        return f'<nav class="global-nav" aria-label="주요 이동">{"".join(links)}</nav>'

    def send_html(self, title: str, body: str, status: int = 200, user_name: str | None = None):
        current = self.current_user()
        data = html_page(title, body, user_name, self.global_nav_html(current))
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location: str):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def is_secure_request(self) -> bool:
        if self.headers.get("CF-Visitor", "").lower().find('"scheme":"https"') >= 0:
            return True
        proto = self.headers.get("X-Forwarded-Proto", "")
        return proto.split(",", 1)[0].strip().lower() == "https"

    def session_cookie_header(self, value: str, max_age: int) -> str:
        parts = [
            f"portal_session={value}",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
            f"Max-Age={max_age}",
        ]
        if self.is_secure_request():
            parts.append("Secure")
        return "; ".join(parts)

    def send_health(self, include_body: bool = True):
        body = b"ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body) if include_body else 0))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def send_static_asset(self, request_path: str, include_body: bool = True):
        asset = static_asset_response(request_path)
        if not asset:
            self.send_response(404)
            self.end_headers()
            return
        content_type, data = asset
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if request_path.startswith("/static/app/assets/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if include_body:
            self.wfile.write(data)

    def send_react_app(self, include_body: bool = True):
        data = react_app_page()
        if data is None:
            self.send_html(
                "앱 준비 중",
                "<div class='card'><h2>React 앱 준비 중</h2><p>아직 빌드된 앱이 없습니다. frontend 폴더에서 빌드한 뒤 다시 접속하세요.</p></div>",
                503,
            )
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data) if include_body else 0))
        self.end_headers()
        if include_body:
            self.wfile.write(data)

    def peer_ip(self) -> str:
        return self.client_address[0]

    def request_client_ip(self) -> tuple[str, str]:
        return request_client_ip(self.headers, self.peer_ip())

    def audit_event(
        self,
        user: dict,
        action: str,
        root: dict | None = None,
        path: str = "",
        target: Path | None = None,
        status: str = "ok",
        **extra,
    ):
        client_ip, client_ip_source = self.request_client_ip()
        event = {
            "action": action,
            "actor": user.get("username", ""),
            "actor_name": user.get("name", user.get("username", "")),
            "status": status,
            "client_ip": client_ip,
            "user_agent": self.headers.get("User-Agent", "")[:180],
        }
        if client_ip_source != "socket":
            event["client_ip_source"] = client_ip_source
            event["peer_ip"] = self.peer_ip()
        if root:
            event["root_id"] = root.get("id", "")
            event["root_label"] = root.get("label", "")
        if path:
            event["path"] = normalized_rel_path(path)
        if target:
            try:
                event["path_abs"] = str(target.resolve())
            except OSError:
                pass
        for key, value in extra.items():
            if isinstance(value, Path):
                try:
                    event[key] = str(value.resolve())
                except OSError:
                    event[key] = str(value)
            else:
                event[key] = value
        self.portal.log_event(event)
