#!/usr/bin/env python3
import hmac
import html
import http.cookies

from portal_core import is_private_client


class PortalAuthMixin:
    def current_session(self) -> dict | None:
        raw = self.headers.get("Cookie", "")
        cookies = http.cookies.SimpleCookie(raw)
        morsel = cookies.get("portal_session")
        if not morsel:
            return None
        return self.portal.unsign(morsel.value)

    def current_user(self) -> dict | None:
        payload = self.current_session()
        if not payload:
            return None
        user = self.portal.user(payload.get("u", ""))
        if user and user.get("disabled"):
            return None
        return user

    def csrf_input(self) -> str:
        payload = self.current_session() or {}
        token = str(payload.get("csrf", ""))
        return f'<input type="hidden" name="csrf_token" value="{html.escape(token, quote=True)}">'

    def verify_csrf_value(self, user: dict, token: str) -> bool:
        payload = self.current_session() or {}
        expected = str(payload.get("csrf", ""))
        if expected and token and hmac.compare_digest(expected, str(token)):
            return True
        self.audit_event(user, "csrf_denied", status="denied", reason="bad_csrf")
        self.send_html(
            "요청 차단",
            "<div class='card'><h2>요청 차단</h2><p>보안 토큰이 만료되었거나 맞지 않습니다. 페이지를 새로고침한 뒤 다시 시도하세요.</p></div>",
            403,
            user.get("name"),
        )
        return False

    def verify_csrf_form(self, user: dict, form: dict) -> bool:
        return self.verify_csrf_value(user, form.get("csrf_token", [""])[0])

    def require_user(self) -> dict | None:
        if not is_private_client(self.peer_ip()):
            self.send_html("접근 차단", "<div class='card'><h2>접근 차단</h2><p>내부 네트워크에서만 접속할 수 있습니다.</p></div>", 403)
            return None
        user = self.current_user()
        if not user:
            self.redirect("/login")
            return None
        return user
