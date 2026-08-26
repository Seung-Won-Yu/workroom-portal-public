#!/usr/bin/env python3
import base64
import http.cookiejar
import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile


BASE = "http://127.0.0.1:8787"
AUDIT_LOG = Path("/home/portal/workspaces/admin/portal/audit_events.jsonl")
SAMPLES = [
    "sample-pdf.pdf",
    "sample-docx.docx",
    "sample-xlsx.xlsx",
    "sample-pptx.pptx",
    "sample-markdown.md",
    "sample-page.html",
    "sample-code.py",
    "sample-style.css",
]


def require(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(label, "ok")


def portal_password(username: str) -> str:
    password_file = Path("/home/portal/workspaces/admin/portal_initial_passwords.txt")
    for line in password_file.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] == username:
            return parts[2]
    raise RuntimeError(f"{username} password not found")


def login(username: str = "admin") -> urllib.request.OpenerDirector:
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    opener.portal_cookies = cookies
    data = urllib.parse.urlencode({"username": username, "password": portal_password(username)}).encode()
    opener.open(f"{BASE}/login", data=data, timeout=10)
    return opener


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def response_status(request: urllib.request.Request) -> tuple[int, urllib.response.addinfourl]:
    try:
        response = urllib.request.urlopen(request, timeout=10)
        return response.status, response
    except urllib.error.HTTPError as exc:
        return exc.code, exc


def csrf_token(opener: urllib.request.OpenerDirector) -> str:
    for cookie in getattr(opener, "portal_cookies", []):
        if cookie.name == "portal_session":
            raw = cookie.value.split(".", 1)[0]
            raw += "=" * (-len(raw) % 4)
            payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
            return str(payload.get("csrf", ""))
    raise RuntimeError("csrf token not found")


def cookie_header(opener: urllib.request.OpenerDirector) -> str:
    return "; ".join(f"{cookie.name}={cookie.value}" for cookie in getattr(opener, "portal_cookies", []))


def post_form(opener: urllib.request.OpenerDirector, route: str, fields: dict[str, str]):
    payload = dict(fields)
    payload["csrf_token"] = csrf_token(opener)
    data = urllib.parse.urlencode(payload).encode()
    return opener.open(f"{BASE}{route}", data=data, timeout=30)


def post_json(opener: urllib.request.OpenerDirector, route: str, payload: dict):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE}{route}",
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf_token(opener),
        },
        method="POST",
    )
    return json.loads(opener.open(request, timeout=30).read().decode("utf-8"))


def read_text_response(response) -> str:
    return response.read().decode("utf-8", "replace")


def is_react_shell(body: str) -> bool:
    return '<div id="root"></div>' in body and "/static/app/assets/" in body


def require_react_shell(label: str, response, body: str, **expected_params: str) -> None:
    parsed = urllib.parse.urlparse(response.geturl())
    query = urllib.parse.parse_qs(parsed.query)
    require(f"{label}-react-shell", parsed.path == "/app" and is_react_shell(body))
    for key, value in expected_params.items():
        require(f"{label}-param-{key}", query.get(key, [""])[0] == value)


def sample_path(filename: str) -> str:
    return urllib.parse.quote(f"admin/portal_preview_tests/{filename}")


def ensure_samples() -> None:
    sample_dir = Path("/home/portal/workspaces/admin/portal_preview_tests")
    if all((sample_dir / filename).exists() for filename in SAMPLES):
        return
    subprocess.run(["python3", str(Path(__file__).with_name("create_portal_samples.py"))], check=True)


def multipart_upload(
    opener: urllib.request.OpenerDirector,
    fields: dict[str, str],
    filename: str,
    content: bytes,
    content_type: str = "text/plain",
):
    fields = dict(fields)
    fields.setdefault("csrf_token", csrf_token(opener))
    boundary = f"----portal-selftest-{int(time.time() * 1000000)}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("ascii"))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"))
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")
    parts.append(f"--{boundary}\r\n".encode("ascii"))
    parts.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(content)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    body = b"".join(parts)
    request = urllib.request.Request(
        f"{BASE}/upload_file",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )
    return opener.open(request, timeout=30)


def api_multipart_upload(
    opener: urllib.request.OpenerDirector,
    fields: dict[str, str],
    filename: str,
    content: bytes,
    content_type: str = "text/plain",
):
    boundary = f"----portal-api-selftest-{int(time.time() * 1000000)}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode("ascii"))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"))
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")
    parts.append(f"--{boundary}\r\n".encode("ascii"))
    parts.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(content)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    body = b"".join(parts)
    request = urllib.request.Request(
        f"{BASE}/api/upload",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "X-CSRF-Token": csrf_token(opener),
        },
        method="POST",
    )
    return json.loads(opener.open(request, timeout=30).read().decode("utf-8"))


def oversized_upload_response(opener: urllib.request.OpenerDirector) -> tuple[int, str]:
    conn = http.client.HTTPConnection("127.0.0.1", 8787, timeout=10)
    try:
        conn.putrequest("POST", "/upload_file")
        conn.putheader("Cookie", cookie_header(opener))
        conn.putheader("Content-Type", "multipart/form-data; boundary=oversized")
        conn.putheader("Content-Length", str(210 * 1024 * 1024))
        conn.endheaders()
        response = conn.getresponse()
        body = response.read().decode("utf-8", "replace")
        return response.status, body
    finally:
        conn.close()


def main() -> None:
    ensure_samples()
    health_body = urllib.request.urlopen(f"{BASE}/health", timeout=10).read().decode("utf-8")
    require("health-endpoint-ok", health_body == "ok\n")
    health_head = urllib.request.Request(f"{BASE}/health", method="HEAD")
    health_status, health_response = response_status(health_head)
    require("health-head-ok", health_status == 200 and health_response.headers.get("Cache-Control") == "no-store")

    login_body = urllib.request.urlopen(f"{BASE}/login", timeout=10).read().decode("utf-8", "replace")
    login_rendered = login_body.split("</style>", 1)[-1]
    require("login-page-remote-work-copy", "직원 원격 작업 포털" in login_rendered and "아이디와 비밀번호" in login_rendered)
    require("login-page-help-copy", "로그인이 안 되나요?" in login_rendered and "현재 접속 주소" in login_rendered and "10분간 로그인이 제한" in login_rendered)

    bad_guidance_username = f"selftest-bad-login-{int(time.time() * 1000)}"
    bad_guidance_body = urllib.request.urlopen(
        f"{BASE}/login",
        data=urllib.parse.urlencode({"username": bad_guidance_username, "password": "bad-password"}).encode(),
        timeout=10,
    ).read().decode("utf-8", "replace")
    bad_guidance_rendered = bad_guidance_body.split("</style>", 1)[-1]
    require("login-bad-credentials-recovery-copy", "비밀번호가 기억나지 않으면" in bad_guidance_rendered and "초기화를 요청" in bad_guidance_rendered)

    secure_login = urllib.request.build_opener(NoRedirect)
    secure_request = urllib.request.Request(
        f"{BASE}/login",
        data=urllib.parse.urlencode({"username": "admin", "password": portal_password("admin")}).encode(),
        headers={"X-Forwarded-Proto": "https"},
    )
    try:
        secure_login.open(secure_request, timeout=10)
        secure_cookie = ""
    except urllib.error.HTTPError as exc:
        secure_cookie = exc.headers.get("Set-Cookie", "")
    require("secure-cookie-behind-https-proxy", "Secure" in secure_cookie and "HttpOnly" in secure_cookie)

    opener = login()
    logged_in_login = urllib.request.build_opener(NoRedirect)
    logged_in_login_request = urllib.request.Request(f"{BASE}/login", headers={"Cookie": cookie_header(opener)})
    try:
        logged_in_login.open(logged_in_login_request, timeout=10)
        logged_in_login_status = "allowed"
        logged_in_login_location = ""
    except urllib.error.HTTPError as exc:
        logged_in_login_status = str(exc.code)
        logged_in_login_location = exc.headers.get("Location", "")
    require("logged-in-login-redirects-to-app", logged_in_login_status == "303" and logged_in_login_location == "/app")
    logged_in_login_head = urllib.request.Request(f"{BASE}/login", headers={"Cookie": cookie_header(opener)}, method="HEAD")
    try:
        logged_in_login.open(logged_in_login_head, timeout=10)
        logged_in_login_head_status = "allowed"
        logged_in_login_head_location = ""
    except urllib.error.HTTPError as exc:
        logged_in_login_head_status = str(exc.code)
        logged_in_login_head_location = exc.headers.get("Location", "")
    require("logged-in-login-head-redirects-to-app", logged_in_login_head_status == "303" and logged_in_login_head_location == "/app")
    api_unauth_status, api_unauth_response = response_status(urllib.request.Request(f"{BASE}/api/session"))
    api_unauth = json.loads(api_unauth_response.read().decode("utf-8"))
    require("api-session-unauth-json", api_unauth_status == 401 and api_unauth.get("error") == "unauthorized")
    api_session = json.loads(opener.open(f"{BASE}/api/session", timeout=10).read().decode("utf-8"))
    require(
        "api-session-user-roots",
        api_session["user"]["username"] == "admin"
        and api_session["user"]["is_admin"] is True
        and api_session["csrf_token"]
        and any(root["id"] == "all" for root in api_session["roots"]),
    )
    react_root_body = opener.open(BASE, timeout=10).read().decode("utf-8", "replace")
    require("react-root-route", '<div id="root"></div>' in react_root_body and "/static/app/assets/" in react_root_body)
    react_app_body = opener.open(f"{BASE}/app", timeout=10).read().decode("utf-8", "replace")
    require("react-app-route", '<div id="root"></div>' in react_app_body and "/static/app/assets/" in react_app_body)
    react_app_static = urllib.request.urlopen(f"{BASE}/static/app/index.html", timeout=10).read().decode("utf-8", "replace")
    require("react-app-static-index", "Workroom Portal App" in react_app_static and "/static/app/assets/" in react_app_static)
    api_admin_folder = json.loads(
        opener.open(f"{BASE}/api/folder?root=all&path=admin/portal_preview_tests&type=code&sort=type", timeout=10).read().decode("utf-8")
    )
    require(
        "api-folder-listing",
        api_admin_folder["root"]["id"] == "all"
        and api_admin_folder["path"] == "admin/portal_preview_tests"
        and api_admin_folder["filters"]["type"] == "code"
        and any(entry["name"] == "sample-code.py" and entry["url"].startswith("/app?") and "file=admin%2Fportal_preview_tests%2Fsample-code.py" in entry["url"] for entry in api_admin_folder["entries"]),
    )
    require("api-folder-hides-server-paths", "/home/" not in json.dumps(api_admin_folder, ensure_ascii=False))
    api_file = json.loads(
        opener.open(f"{BASE}/api/file?root=all&path={sample_path('sample-code.py')}", timeout=10).read().decode("utf-8")
    )
    require(
        "api-file-detail",
        api_file["name"] == "sample-code.py"
        and api_file["kind"] == "code"
        and api_file["download_url"].startswith("/download?")
        and api_file["context"]["scope"] == "관리자 전체",
    )
    require("api-file-hides-server-paths", "/home/" not in json.dumps(api_file, ensure_ascii=False))
    api_admin_summary = json.loads(opener.open(f"{BASE}/api/admin/summary", timeout=10).read().decode("utf-8"))
    require(
        "api-admin-summary",
        api_admin_summary["member_count"] >= 7
        and "team-alpha" in api_admin_summary["teams"]
        and "maintenance" in api_admin_summary,
    )
    api_user1 = login("user1")
    api_upload_name = f"portal-api-upload-{int(time.time() * 1000)}.txt"
    api_upload = api_multipart_upload(
        api_user1,
        {"root": "personal", "path": "research"},
        api_upload_name,
        b"api upload selftest",
    )
    api_upload_path = f"research/{api_upload_name}"
    api_upload_target = Path("/home/portal/workspaces/team-alpha/user1/research") / api_upload_name
    require(
        "api-upload-json",
        api_upload["ok"] is True
        and api_upload["action"] == "upload"
        and api_upload["path"] == api_upload_path
        and api_upload_target.exists(),
    )
    api_status = post_json(
        api_user1,
        "/api/actions/status",
        {"root": "personal", "path": api_upload_path, "file_status": "revision_needed"},
    )
    require(
        "api-status-json",
        api_status["ok"] is True
        and api_status["status"] == "revision_needed"
        and api_status["status_label"] == "수정 필요",
    )
    api_missing_csrf_request = urllib.request.Request(
        f"{BASE}/api/actions/status",
        data=json.dumps({"root": "personal", "path": api_upload_path, "file_status": "review_needed"}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Cookie": cookie_header(api_user1),
        },
        method="POST",
    )
    api_missing_csrf_status, api_missing_csrf_response = response_status(api_missing_csrf_request)
    api_missing_csrf = json.loads(api_missing_csrf_response.read().decode("utf-8"))
    require("api-action-csrf-required", api_missing_csrf_status == 403 and api_missing_csrf.get("error") == "csrf_denied")
    api_renamed_name = f"portal-api-renamed-{int(time.time() * 1000)}.txt"
    api_rename = post_json(
        api_user1,
        "/api/actions/rename",
        {"root": "personal", "path": api_upload_path, "new_name": api_renamed_name},
    )
    api_renamed_path = f"research/{api_renamed_name}"
    api_renamed_target = api_upload_target.with_name(api_renamed_name)
    require(
        "api-rename-json",
        api_rename["ok"] is True
        and api_rename["path"] == api_renamed_path
        and not api_upload_target.exists()
        and api_renamed_target.exists(),
    )
    api_share = post_json(
        api_user1,
        "/api/actions/share",
        {"root": "personal", "path": api_renamed_path, "shared_target": "research"},
    )
    api_shared_target = Path("/home/portal/workspaces/team-alpha/shared/research") / api_renamed_name
    require(
        "api-share-json",
        api_share["ok"] is True
        and api_share["root"] == "team_shared"
        and api_share["path"].startswith("research/")
        and not api_renamed_target.exists()
        and api_shared_target.exists(),
    )
    api_shared_file = json.loads(
        api_user1.open(f"{BASE}/api/file?root=team_shared&path={urllib.parse.quote(api_share['path'])}", timeout=10).read().decode("utf-8")
    )
    require("api-shared-owner-can-archive", api_shared_file["can_archive"] is True)
    api_user2 = login("user2")
    api_shared_peer_file = json.loads(
        api_user2.open(f"{BASE}/api/file?root=team_shared&path={urllib.parse.quote(api_share['path'])}", timeout=10).read().decode("utf-8")
    )
    require("api-shared-peer-cannot-archive", api_shared_peer_file["can_archive"] is False)
    peer_archive_request = urllib.request.Request(
        f"{BASE}/api/actions/archive",
        data=json.dumps({"root": "team_shared", "path": api_share["path"], "csrf_token": csrf_token(api_user2)}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf_token(api_user2),
            "Cookie": cookie_header(api_user2),
        },
        method="POST",
    )
    peer_archive_status, peer_archive_response = response_status(peer_archive_request)
    peer_archive_payload = json.loads(peer_archive_response.read().decode("utf-8"))
    require("api-shared-peer-archive-blocked", peer_archive_status == 403 and peer_archive_payload.get("error") == "archive_delete")
    api_shared_archive = post_json(
        api_user1,
        "/api/actions/archive",
        {"root": "team_shared", "path": api_share["path"]},
    )
    api_shared_archive_destination = Path("/home/portal/workspaces/team-alpha/user1") / api_shared_archive["archive_path"]
    require(
        "api-shared-owner-archive-json",
        api_shared_archive["ok"] is True
        and api_shared_archive["action"] == "archive"
        and not api_shared_target.exists()
        and api_shared_archive_destination.exists(),
    )
    api_shared_restore = post_json(opener, "/api/actions/restore", {"owner": "user1", "archive_path": api_shared_archive["archive_path"]})
    require(
        "api-shared-owner-archive-managed",
        api_shared_restore["ok"] is True
        and api_renamed_target.exists()
        and not api_shared_archive_destination.exists(),
    )
    api_renamed_target.unlink(missing_ok=True)
    api_archive_name = f"portal-api-archive-{int(time.time() * 1000)}.txt"
    api_archive_target = Path("/home/portal/workspaces/team-alpha/user1/research") / api_archive_name
    api_archive_target.write_text("api archive selftest", encoding="utf-8")
    api_archive = post_json(
        api_user1,
        "/api/actions/archive",
        {"root": "personal", "path": f"research/{api_archive_name}"},
    )
    api_archive_destination = Path("/home/portal/workspaces/team-alpha/user1") / api_archive["archive_path"]
    require(
        "api-archive-json",
        api_archive["ok"] is True
        and api_archive["action"] == "archive"
        and not api_archive_target.exists()
        and api_archive_destination.exists(),
    )
    api_admin_archive = json.loads(opener.open(f"{BASE}/api/admin/archive", timeout=10).read().decode("utf-8"))
    require(
        "api-admin-archive",
        api_admin_archive["total"] >= 1
        and any(entry["owner"] == "user1" and entry["archive_path"] == api_archive["archive_path"] for entry in api_admin_archive["entries"]),
    )
    api_archive_entry = next(entry for entry in api_admin_archive["entries"] if entry["owner"] == "user1" and entry["archive_path"] == api_archive["archive_path"])
    require(
        "api-admin-archive-actions",
        api_archive_entry["view_url"].startswith("/admin/archive/view?")
        and api_archive_entry["preview_url"].startswith("/admin/archive/preview?")
        and api_archive_entry["download_url"].startswith("/admin/archive/download?"),
    )
    require("api-admin-archive-hides-server-paths", "/home/" not in json.dumps(api_admin_archive, ensure_ascii=False))
    archive_query = f"owner=user1&archive_path={urllib.parse.quote(api_archive['archive_path'])}"
    archive_view = opener.open(f"{BASE}/admin/archive/view?{archive_query}", timeout=10).read().decode("utf-8", "replace")
    require("admin-archive-view-content", api_archive_name in archive_view and "api archive selftest" in archive_view)
    archive_preview = opener.open(f"{BASE}/admin/archive/preview?{archive_query}", timeout=10).read().decode("utf-8", "replace")
    require("admin-archive-preview-content", api_archive_name in archive_preview and "api archive selftest" in archive_preview)
    archive_download = opener.open(f"{BASE}/admin/archive/download?{archive_query}", timeout=10).read()
    require("admin-archive-download-content", b"api archive selftest" in archive_download)
    api_restore = post_json(opener, "/api/actions/restore", {"owner": "user1", "archive_path": api_archive["archive_path"]})
    require(
        "api-restore-json",
        api_restore["ok"] is True
        and api_restore["action"] == "restore"
        and api_archive_target.exists()
        and not api_archive_destination.exists(),
    )
    require("api-restore-hides-server-paths", "/home/" not in json.dumps(api_restore, ensure_ascii=False))
    pending_share_dir = Path("/home/portal/workspaces/team-alpha/user1/research")
    pending_share_dir.mkdir(parents=True, exist_ok=True)
    for stale_pending in pending_share_dir.glob("portal-pending-share-check-*.md"):
        stale_pending.unlink(missing_ok=True)
    pending_share_name = f"portal-pending-share-check-{int(time.time() * 1000)}.md"
    pending_share_target = pending_share_dir / pending_share_name
    pending_share_target.write_text("# pending share check\n\nadmin dashboard should point this to research share.\n", encoding="utf-8")
    legacy_opener = urllib.request.build_opener(NoRedirect)
    legacy_request = urllib.request.Request(f"{BASE}/legacy", headers={"Cookie": cookie_header(opener)})
    try:
        legacy_opener.open(legacy_request, timeout=10)
        legacy_status = "allowed"
        legacy_location = ""
    except urllib.error.HTTPError as exc:
        legacy_status = str(exc.code)
        legacy_location = exc.headers.get("Location", "")
    require("legacy-home-redirects-to-app", legacy_status == "303" and legacy_location == "/app")

    admin_response = opener.open(f"{BASE}/admin", timeout=30)
    admin_body = read_text_response(admin_response)
    if is_react_shell(admin_body):
        require_react_shell("admin-overview-page", admin_response, admin_body, view="admin-overview", root="all")
        require("admin-overview-teams", "team-alpha" in api_admin_summary["teams"] and "team-beta" in api_admin_summary["teams"])
        require("admin-overview-members", api_admin_summary["member_count"] >= 7)
    else:
        admin_rendered = admin_body.split("</style>", 1)[-1]
        require("admin-overview-page", "admin-overview" in admin_rendered and "관리자 대시보드" in admin_rendered)
        require("admin-overview-teams", "team-alpha" in admin_rendered and "team-beta" in admin_rendered)
        require("admin-overview-members", "사용자1" in admin_rendered and "사용자5" in admin_rendered and "7명" in admin_rendered)
        require("admin-overview-links", "/browse?root=all" in admin_rendered and "개인 폴더" in admin_rendered and "공유 폴더 열기" in admin_rendered)
        require("admin-overview-audit-section", "최근 작업 기록" in admin_rendered and ("audit-table" in admin_rendered or "아직 기록된 포털 작업" in admin_rendered))
        require("admin-overview-command-row", "admin-command-row" in admin_rendered and "전체 작업공간" in admin_rendered and "전체 산출물 검색" in admin_rendered and "사용자별 폴더" in admin_rendered)
        require("admin-overview-priority-panel", "admin-focus-grid" in admin_rendered and "최근 권한 차단" in admin_rendered and "산출물 없음" in admin_rendered)
        require("admin-overview-ops-summary", "운영 작업 기록" in admin_rendered and "/admin/archive" in admin_rendered and "보관함 관리" in admin_rendered)
        require("admin-overview-activity-links", "/admin/activity" in admin_rendered and "작업 기록 검색" in admin_rendered and "활동 보기" in admin_rendered)
        require("admin-overview-flow-cards", "최근 업로드" in admin_rendered and "최근 팀 공유" in admin_rendered and "최근 보관" in admin_rendered and "미리보기 실패" in admin_rendered and "action=upload" in admin_rendered and "action=move_to_shared" in admin_rendered and "action=archive" in admin_rendered and "action=preview_failed" in admin_rendered)
        require("admin-overview-flow-card-latest", "최근 항목 없음" in admin_rendered or "activity-card" in admin_rendered and "작업 기록" in admin_rendered)
        require("admin-overview-team-activity", "팀별 작업 현황" in admin_rendered and "team-alpha" in admin_rendered and "team-beta" in admin_rendered and "업로드" in admin_rendered and "팀 공유" in admin_rendered and "상태 변경" in admin_rendered and "보관" in admin_rendered and "권한 차단" in admin_rendered and "공유 대기" in admin_rendered and "큰/오래된 파일" in admin_rendered and "/admin/activity?team=team-alpha" in admin_rendered)
        require("admin-overview-pending-share", "공유 대기 산출물" in admin_rendered and pending_share_name in admin_rendered and "리서치 공유" in admin_rendered)
        require("admin-overview-attention-sections", "큰 파일" in admin_rendered and "오래된 작업물" in admin_rendered and "실패 기록 보기" in admin_rendered and "20.0 MB 이상" in admin_rendered and "14일 이상 수정 없음" in admin_rendered)
        require("admin-overview-preview-failure-summary", "미리보기 실패 원인 요약" in admin_rendered and ("최근 미리보기 실패 기록이 없습니다." in admin_rendered or "reason-list" in admin_rendered))
        require("admin-overview-system-status", "시스템 상태" in admin_rendered and "감사로그 크기" in admin_rendered and "미리보기 캐시" in admin_rendered)
        require("admin-overview-table-scroll", "admin-table-scroll" in admin_rendered)

    admin_search_query = urllib.parse.urlencode({
        "q": pending_share_name,
        "owner": "user1",
        "team": "team-alpha",
        "scope": "개인 작업공간",
    })
    admin_search_response = opener.open(f"{BASE}/admin/search?{admin_search_query}", timeout=30)
    admin_search_body = read_text_response(admin_search_response)
    if is_react_shell(admin_search_body):
        require_react_shell("admin-file-search-page", admin_search_response, admin_search_body, view="admin-search", root="all")
    else:
        admin_search_rendered = admin_search_body.split("</style>", 1)[-1]
        require("admin-file-search-page", "전체 산출물 검색" in admin_search_rendered and "admin-file-search-table" in admin_search_rendered and "검색 결과" in admin_search_rendered)
        require("admin-file-search-finds-owner-file", pending_share_name in admin_search_rendered and "사용자1" in admin_search_rendered and "team-alpha" in admin_search_rendered and "개인 작업공간" in admin_search_rendered)
        require("admin-file-search-actions", "/app?root=all" in admin_search_rendered and "file=" in admin_search_rendered and "/download?root=all" in admin_search_rendered and "폴더" in admin_search_rendered)
        require("global-nav-admin-search-active", 'class="nav-link active" href="/admin/search" aria-current="page">전체 산출물' in admin_search_rendered)
    api_admin_search = json.loads(opener.open(f"{BASE}/api/admin/search?{admin_search_query}", timeout=10).read().decode("utf-8"))
    require(
        "api-admin-search",
        api_admin_search["filters"]["q"] == pending_share_name
        and api_admin_search["filters"]["owner"] == "user1"
        and api_admin_search["total"] >= 1
        and any(entry["name"] == pending_share_name and entry["view_url"].startswith("/app?") and "file=" in entry["view_url"] for entry in api_admin_search["entries"]),
    )
    require("api-admin-search-hides-server-paths", "/home/" not in json.dumps(api_admin_search, ensure_ascii=False))
    pending_share_target.unlink(missing_ok=True)

    try:
        user_opener = login("user1")
        user_opener.open(f"{BASE}/admin", timeout=30)
        admin_forbidden = "allowed"
    except urllib.error.HTTPError as exc:
        admin_forbidden = str(exc.code)
    require("admin-overview-non-admin-forbidden", admin_forbidden == "403")
    try:
        user_opener.open(f"{BASE}/admin/archive", timeout=30)
        archive_forbidden = "allowed"
    except urllib.error.HTTPError as exc:
        archive_forbidden = str(exc.code)
    require("admin-archive-non-admin-forbidden", archive_forbidden == "403")
    try:
        user_opener.open(f"{BASE}/admin/activity", timeout=30)
        activity_forbidden = "allowed"
    except urllib.error.HTTPError as exc:
        activity_forbidden = str(exc.code)
    require("admin-activity-non-admin-forbidden", activity_forbidden == "403")
    try:
        user_opener.open(f"{BASE}/admin/search", timeout=30)
        file_search_forbidden = "allowed"
    except urllib.error.HTTPError as exc:
        file_search_forbidden = str(exc.code)
    require("admin-file-search-non-admin-forbidden", file_search_forbidden == "403")
    try:
        user_opener.open(f"{BASE}/admin/user?username=user1", timeout=30)
        report_forbidden = "allowed"
    except urllib.error.HTTPError as exc:
        report_forbidden = str(exc.code)
    require("admin-user-report-non-admin-forbidden", report_forbidden == "403")

    user_legacy_opener = urllib.request.build_opener(NoRedirect)
    user_legacy_request = urllib.request.Request(f"{BASE}/legacy", headers={"Cookie": cookie_header(user_opener)})
    try:
        user_legacy_opener.open(user_legacy_request, timeout=10)
        user_legacy_status = "allowed"
        user_legacy_location = ""
    except urllib.error.HTTPError as exc:
        user_legacy_status = str(exc.code)
        user_legacy_location = exc.headers.get("Location", "")
    require("user-legacy-home-redirects-to-app", user_legacy_status == "303" and user_legacy_location == "/app")
    user_app_body = user_opener.open(f"{BASE}/app", timeout=30).read().decode("utf-8", "replace")
    require("user-react-app-route", '<div id="root"></div>' in user_app_body and "/static/app/assets/" in user_app_body)

    bad_login = urllib.request.build_opener()
    rate_username = f"selftest-rate-{int(time.time() * 1000)}"
    rate_status = ""
    rate_body = ""
    for _idx in range(6):
        try:
            bad_login.open(
                f"{BASE}/login",
                data=urllib.parse.urlencode({"username": rate_username, "password": "bad-password"}).encode(),
                timeout=10,
            )
            rate_status = "200"
        except urllib.error.HTTPError as exc:
            rate_status = str(exc.code)
            rate_body = exc.read().decode("utf-8", "replace")
    require("login-rate-limit-after-failures", rate_status == "429")
    require("login-rate-limit-recovery-copy", "10분 후 다시 시도" in rate_body and "비밀번호 초기화" in rate_body)

    forwarded_ip = "203.0.113.45"
    forwarded_username = f"selftest-forwarded-{int(time.time() * 1000)}"
    forwarded_request = urllib.request.Request(
        f"{BASE}/login",
        data=urllib.parse.urlencode({"username": forwarded_username, "password": "bad-password"}).encode(),
        headers={"CF-Connecting-IP": forwarded_ip},
    )
    urllib.request.build_opener().open(forwarded_request, timeout=10).read()

    user1_opener = login("user1")
    delete_dir = Path("/home/portal/workspaces/team-alpha/user1/research")
    delete_dir.mkdir(parents=True, exist_ok=True)
    for stale_admin_search in delete_dir.glob("admin-search-check-*.md"):
        stale_admin_search.unlink(missing_ok=True)
    admin_search_name = f"admin-search-check-{int(time.time() * 1000)}.md"
    admin_search_target = delete_dir / admin_search_name
    admin_search_target.write_text("# admin search check\n\nThis file verifies admin-wide file search.\n", encoding="utf-8")
    post_form(user1_opener, "/set_file_status", {"root": "personal", "path": f"research/{admin_search_name}", "file_status": "review_needed"})
    delete_target = delete_dir / f"portal-delete-test-{int(time.time())}.txt"
    delete_target.write_text("portal archive delete selftest\n", encoding="utf-8")
    personal_response = user1_opener.open(
        f"{BASE}/browse?root=personal&path=research",
        timeout=30,
    )
    personal_body = read_text_response(personal_response)
    if is_react_shell(personal_body):
        require_react_shell("personal-list", personal_response, personal_body, root="personal", path="research")
        api_personal_folder = json.loads(user1_opener.open(f"{BASE}/api/folder?root=personal&path=research", timeout=10).read().decode("utf-8"))
        require("personal-list-hides-archive-action", all("archive_delete" not in json.dumps(entry, ensure_ascii=False) for entry in api_personal_folder["entries"]))
        require("personal-upload-api-path", api_personal_folder["root"]["id"] == "personal" and api_personal_folder["path"] == "research")
    else:
        personal_rendered = personal_body.split("</style>", 1)[-1]
        require("personal-list-hides-archive-action", "/archive_delete" not in personal_rendered and "보관함으로 이동" not in personal_rendered and "file-actions" not in personal_rendered)
        require("personal-upload-form-visible", "/upload_file" in personal_rendered and "조사 자료에 업로드" in personal_rendered and "저장 위치: 개인 작업공간 / 조사 자료" in personal_rendered and "실행 파일과 설치 파일" in personal_rendered)
        require("personal-forms-have-csrf", 'name="csrf_token"' in personal_rendered)
        require("global-nav-personal-active", 'class="nav-link active" href="/browse?root=personal" aria-current="page">내 산출물' in personal_rendered)
    delete_detail_body = user1_opener.open(
        f"{BASE}/view?root=personal&path={urllib.parse.quote('research/' + delete_target.name)}",
        timeout=30,
    ).read().decode("utf-8", "replace")
    delete_detail_rendered = delete_detail_body.split("</style>", 1)[-1]
    require("personal-archive-delete-action-visible", "/archive_delete" in delete_detail_rendered and "보관함으로 이동" in delete_detail_rendered and "삭제(보관)" not in delete_detail_rendered)

    personal_root_response = user1_opener.open(
        f"{BASE}/browse?root=personal",
        timeout=30,
    )
    personal_root_body = read_text_response(personal_root_response)
    if is_react_shell(personal_root_body):
        require_react_shell("personal-root", personal_root_response, personal_root_body, root="personal")
        api_personal_root = json.loads(user1_opener.open(f"{BASE}/api/folder?root=personal", timeout=10).read().decode("utf-8"))
        require("personal-root-upload-form-hidden", api_personal_root["path"] == "")
        require("personal-root-upload-targets", all(any(entry["name"] == folder and entry["is_dir"] for entry in api_personal_root["entries"]) for folder in ("dev", "research", "summary")))
    else:
        personal_root_rendered = personal_root_body.split("</style>", 1)[-1]
        require("personal-root-upload-form-hidden", "/upload_file" not in personal_root_rendered and "업로드 위치 선택" in personal_root_rendered and "파일을 올릴 위치를 선택하세요" in personal_root_rendered)
        require("personal-root-upload-targets", all(f"path={folder}" in personal_root_rendered for folder in ("dev", "research", "summary")) and "개발 산출물" in personal_root_rendered and "조사 자료" in personal_root_rendered and "요약/보고 자료" in personal_root_rendered and "팀 공유공간에는 직접 업로드하지 않습니다" in personal_root_rendered)

    archive_data = urllib.parse.urlencode({"root": "personal", "path": f"research/{delete_target.name}"}).encode()
    try:
        user1_opener.open(f"{BASE}/archive_delete", data=archive_data, timeout=30)
        csrf_status = "allowed"
    except urllib.error.HTTPError as exc:
        csrf_status = str(exc.code)
    require("csrf-missing-archive-blocked", csrf_status == "403")
    archive_response = post_form(user1_opener, "/archive_delete", {"root": "personal", "path": f"research/{delete_target.name}"})
    archive_body = archive_response.read().decode("utf-8", "replace")
    require("personal-archive-delete-redirect", "msg=archived" in archive_response.geturl() or "보관함으로 이동" in archive_body)
    if is_react_shell(archive_body):
        archive_query = urllib.parse.parse_qs(urllib.parse.urlparse(archive_response.geturl()).query)
        require(
            "personal-archive-delete-recovery-info",
            archive_query.get("archived_name", [""])[0] == delete_target.name
            and archive_query.get("archived_path", [""])[0] == f"research/{delete_target.name}"
            and bool(archive_query.get("archived_by", [""])[0]),
        )
    else:
        require("personal-archive-delete-recovery-info", delete_target.name in archive_body and f"research/{delete_target.name}" in archive_body and "복구가 필요하면 아래 정보를 관리자에게 보내주세요" in archive_body and "원래 위치" in archive_body and "요청자" in archive_body)
    require("personal-archive-delete-source-gone", not delete_target.exists())
    archive_root = Path("/home/portal/workspaces/team-alpha/user1/.archive/deleted")
    archived_matches = list(archive_root.rglob(delete_target.name))
    require("personal-archive-delete-destination", bool(archived_matches))

    archive_response_page = opener.open(f"{BASE}/admin/archive", timeout=30)
    archive_page = read_text_response(archive_response_page)
    if is_react_shell(archive_page):
        require_react_shell("admin-archive-page", archive_response_page, archive_page, view="admin-archive", root="all")
        archive_api_after_delete = json.loads(opener.open(f"{BASE}/api/admin/archive", timeout=10).read().decode("utf-8"))
        require("admin-archive-count-note", archive_api_after_delete["total"] >= 1)
        require("admin-archive-page-entry", any(entry.get("name") == delete_target.name for entry in archive_api_after_delete["entries"]))
    else:
        archive_rendered = archive_page.split("</style>", 1)[-1]
        require("admin-archive-page", "보관함 관리" in archive_rendered and "/restore_archive" in archive_rendered and delete_target.name in archive_rendered)
        require("admin-archive-count-note", "조건에 맞는 보관 항목" in archive_rendered and "표시합니다" in archive_rendered)
    archived_rel = archived_matches[0].relative_to(Path("/home/portal/workspaces/team-alpha/user1")).as_posix()
    restore_response = post_form(opener, "/restore_archive", {"owner": "user1", "archive_path": archived_rel})
    restore_body = restore_response.read().decode("utf-8", "replace")
    require("admin-archive-restore-redirect", "msg=restored" in restore_response.geturl() or "복구" in restore_body)
    require("admin-archive-restore-destination", delete_target.exists())
    require("admin-archive-restore-source-gone", not archived_matches[0].exists())

    upload_stamp = int(time.time() * 1000)
    upload_name = f"portal-upload-test-{upload_stamp}.txt"
    upload_response = multipart_upload(
        user1_opener,
        {"root": "personal", "path": "research"},
        upload_name,
        b"portal upload selftest\n",
    )
    upload_body = upload_response.read().decode("utf-8", "replace")
    upload_target = delete_dir / upload_name
    require("personal-upload-redirects-to-view", "msg=uploaded" in upload_response.geturl() or "개인공간에 업로드" in upload_body)
    require("personal-upload-destination-exists", upload_target.exists() and upload_target.read_text(encoding="utf-8") == "portal upload selftest\n")

    bad_content_request = urllib.request.Request(
        f"{BASE}/upload_file",
        data=b"not multipart",
        headers={"Content-Type": "text/plain"},
    )
    try:
        user1_opener.open(bad_content_request, timeout=10)
        bad_content_status = "allowed"
        bad_content_body = ""
    except urllib.error.HTTPError as exc:
        bad_content_status = str(exc.code)
        bad_content_body = exc.read().decode("utf-8", "replace")
    require("upload-bad-content-type-guidance", bad_content_status == "400" and "업로드 화면에서 다시 시도" in bad_content_body and "브라우저 화면을 사용하세요" in bad_content_body)

    oversize_status, oversize_body = oversized_upload_response(user1_opener)
    require("upload-oversize-guidance", oversize_status == 413 and "파일이 너무 큽니다" in oversize_body and "최대 용량" in oversize_body and "나눠서 다시 업로드" in oversize_body)

    status_response = post_form(user1_opener, "/set_file_status", {"root": "personal", "path": f"research/{upload_name}", "file_status": "review_needed"})
    status_body = status_response.read().decode("utf-8", "replace")
    status_view = user1_opener.open(
        f"{BASE}/view?root=personal&path={urllib.parse.quote('research/' + upload_name)}",
        timeout=30,
    ).read().decode("utf-8", "replace")
    status_rendered = status_view.split("</style>", 1)[-1]
    require("file-status-update-redirect", "msg=status_updated" in status_response.geturl() or "파일 상태를 변경했습니다." in status_body)
    require("file-status-update-visible", "검토 필요" in status_rendered and "/set_file_status" in status_rendered and "상태 변경" in status_rendered)
    require("personal-status-does-not-fake-shared", "팀 공유됨" not in status_rendered)

    duplicate_response = multipart_upload(
        user1_opener,
        {"root": "personal", "path": "research"},
        upload_name,
        b"portal upload duplicate selftest\n",
    )
    duplicate_response.read()
    duplicate_target = delete_dir / f"portal-upload-test-{upload_stamp}-1.txt"
    require("personal-upload-duplicate-does-not-overwrite", upload_target.read_text(encoding="utf-8") == "portal upload selftest\n" and duplicate_target.exists())

    blocked_root_name = f"portal-root-upload-blocked-{upload_stamp}.txt"
    blocked_root_target = Path("/home/portal/workspaces/team-alpha/user1") / blocked_root_name
    try:
        multipart_upload(user1_opener, {"root": "personal", "path": ""}, blocked_root_name, b"blocked root\n")
        root_upload_blocked = False
        root_upload_body = ""
    except urllib.error.HTTPError as exc:
        root_upload_body = exc.read().decode("utf-8", "replace")
        root_upload_blocked = exc.code == 403 and "업로드 위치 확인" in root_upload_body
    require("personal-root-upload-blocked", root_upload_blocked and "현재 위치에는 직접 업로드할 수 없습니다" in root_upload_body and "파일 성격에 맞는 폴더" in root_upload_body and not blocked_root_target.exists())

    blocked_shared_name = f"portal-shared-upload-blocked-{upload_stamp}.txt"
    blocked_shared_target = Path("/home/portal/workspaces/team-alpha/user1/shared") / blocked_shared_name
    try:
        multipart_upload(user1_opener, {"root": "personal", "path": "shared"}, blocked_shared_name, b"blocked shared\n")
        personal_shared_upload_blocked = False
        personal_shared_upload_body = ""
    except urllib.error.HTTPError as exc:
        personal_shared_upload_body = exc.read().decode("utf-8", "replace")
        personal_shared_upload_blocked = exc.code == 403 and "업로드 위치 확인" in personal_shared_upload_body
    require("personal-shared-upload-blocked", personal_shared_upload_blocked and "팀 공유공간에는 직접 업로드하지 않습니다" in personal_shared_upload_body and not blocked_shared_target.exists())

    try:
        post_form(user1_opener, "/archive_delete", {"root": "personal", "path": f"shared/{blocked_shared_name}"})
        personal_shared_archive_blocked = False
    except urllib.error.HTTPError as exc:
        personal_shared_archive_blocked = exc.code == 403
    require("personal-shared-subtree-archive-blocked", personal_shared_archive_blocked and not blocked_shared_target.parent.exists())

    try:
        multipart_upload(user1_opener, {"root": "team_shared", "path": "research"}, f"blocked-upload-{upload_stamp}.txt", b"blocked\n")
        shared_upload_status = "allowed"
        shared_upload_body = ""
    except urllib.error.HTTPError as exc:
        shared_upload_status = str(exc.code)
        shared_upload_body = exc.read().decode("utf-8", "replace")
    require("shared-upload-blocked", shared_upload_status == "403" and "팀 공유공간에는 직접 업로드하지 않습니다" in shared_upload_body)

    shared_browse_response = user1_opener.open(
        f"{BASE}/browse?root=team_shared&path=research",
        timeout=30,
    )
    shared_browse = read_text_response(shared_browse_response)
    if is_react_shell(shared_browse):
        require_react_shell("shared-folder", shared_browse_response, shared_browse, root="team_shared", path="research")
        api_shared_folder = json.loads(user1_opener.open(f"{BASE}/api/folder?root=team_shared&path=research", timeout=10).read().decode("utf-8"))
        require("shared-upload-form-hidden", api_shared_folder["root"]["id"] == "team_shared")
        require("shared-folder-context", api_shared_folder["path"] == "research" and "team_shared" in api_shared_folder["root"]["id"])
    else:
        shared_browse_rendered = shared_browse.split("</style>", 1)[-1]
        require("shared-upload-form-hidden", "/upload_file" not in shared_browse_rendered)
        require("shared-folder-context", "shared-workspace-panel" in shared_browse_rendered and "리서치 공유" in shared_browse_rendered and "팀원이 함께 보는 공유 폴더" in shared_browse_rendered and "팀 공유 전체" in shared_browse_rendered)

    shared_root_response = user1_opener.open(
        f"{BASE}/browse?root=team_shared",
        timeout=30,
    )
    shared_root_body = read_text_response(shared_root_response)
    if is_react_shell(shared_root_body):
        require_react_shell("shared-root", shared_root_response, shared_root_body, root="team_shared")
        api_shared_root = json.loads(user1_opener.open(f"{BASE}/api/folder?root=team_shared", timeout=10).read().decode("utf-8"))
        require("shared-root-context", all(any(entry["name"] == folder and entry["is_dir"] for entry in api_shared_root["entries"]) for folder in ("dev", "research", "summary")))
    else:
        shared_root_rendered = shared_root_body.split("</style>", 1)[-1]
        require("shared-root-context", "팀 공유공간" in shared_root_rendered and "직접 업로드하지 않고" in shared_root_rendered and "개발 공유" in shared_root_rendered and "리서치 공유" in shared_root_rendered and "요약 공유" in shared_root_rendered)

    unsafe_upload_cases = [f"secret-token-{upload_stamp}.txt", f"blocked-exe-{upload_stamp}.exe", "CON.txt", "name."]
    unsafe_bodies = []
    unsafe_all_blocked = True
    for unsafe_name in unsafe_upload_cases:
        try:
            multipart_upload(user1_opener, {"root": "personal", "path": "research"}, unsafe_name, b"secret\n")
            unsafe_all_blocked = False
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            unsafe_bodies.append(body)
            unsafe_all_blocked = unsafe_all_blocked and exc.code == 403
    require(
        "unsafe-upload-name-blocked",
        unsafe_all_blocked
        and all("파일 이름을 바꿔주세요" in body and "report-v1.pdf" in body and "실행 파일과 설치 파일" in body for body in unsafe_bodies)
        and not any((delete_dir / unsafe_name).exists() for unsafe_name in unsafe_upload_cases),
    )

    symlink_name = f"portal-symlink-leak-{upload_stamp}.txt"
    symlink_target = delete_dir / symlink_name
    try:
        symlink_target.unlink(missing_ok=True)
        symlink_target.symlink_to("/etc/hostname")
        zip_response = user1_opener.open(f"{BASE}/download?root=personal&path=research", timeout=30)
        zip_bytes = zip_response.read()
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zip_names = set(zf.namelist())
        require("zip-download-skips-symlink-files", symlink_name not in zip_names)
    finally:
        symlink_target.unlink(missing_ok=True)

    non_ascii_download = delete_dir / unicodedata.normalize("NFD", f"portal-download-test-한글-{upload_stamp}.txt")
    try:
        non_ascii_download.write_text("non ascii download selftest\n", encoding="utf-8")
        non_ascii_path = f"research/{non_ascii_download.name}"
        personal_download = user1_opener.open(f"{BASE}/download?root=personal&path={urllib.parse.quote(non_ascii_path)}", timeout=30)
        personal_disposition = personal_download.headers.get("Content-Disposition", "")
        require(
            "non-ascii-personal-download",
            b"non ascii download selftest" in personal_download.read()
            and "filename*=UTF-8''" in personal_disposition
            and "%ED%95%9C%EA%B8%80" in personal_disposition,
        )
        admin_download_path = f"team-alpha/user1/{non_ascii_path}"
        admin_download = opener.open(f"{BASE}/download?root=all&path={urllib.parse.quote(admin_download_path)}", timeout=30)
        admin_disposition = admin_download.headers.get("Content-Disposition", "")
        require(
            "non-ascii-admin-download",
            b"non ascii download selftest" in admin_download.read()
            and "filename*=UTF-8''" in admin_disposition
            and "%ED%95%9C%EA%B8%80" in admin_disposition,
        )
        composed_download_path = unicodedata.normalize("NFC", admin_download_path)
        composed_download = opener.open(f"{BASE}/download?root=all&path={urllib.parse.quote(composed_download_path)}", timeout=30)
        require(
            "non-ascii-normalized-path-download",
            b"non ascii download selftest" in composed_download.read()
            and "filename*=UTF-8''" in composed_download.headers.get("Content-Disposition", ""),
        )
    finally:
        non_ascii_download.unlink(missing_ok=True)

    manage_stamp = int(time.time() * 1000)
    manage_target = delete_dir / f"portal-manage-test-{manage_stamp}.md"
    renamed_name = f"portal-manage-renamed-{manage_stamp}.md"
    manage_target.write_text("# manage selftest\n\nrename and share move\n", encoding="utf-8")
    manage_view = user1_opener.open(
        f"{BASE}/view?root=personal&path={urllib.parse.quote('research/' + manage_target.name)}",
        timeout=30,
    ).read().decode("utf-8", "replace")
    manage_rendered = manage_view.split("</style>", 1)[-1]
    require("personal-manage-menu-visible", "/rename_item" in manage_rendered and "/move_to_shared" in manage_rendered and "팀 공유로 이동" in manage_rendered and "이름 변경" in manage_rendered and "이름/공유" not in manage_rendered)
    require("file-detail-status-visible", "파일 상태" in manage_rendered and "최근 작업" in manage_rendered)
    require("personal-scope-banner-visible", "file-scope-banner personal" in manage_rendered and "공개 범위: 개인 작업공간" in manage_rendered and "팀원에게 보이지 않습니다" in manage_rendered)
    require("personal-share-primary-action", "viewer-actions" in manage_rendered and "share-callout" in manage_rendered and "share-action-form" in manage_rendered and "button primary" in manage_rendered and "팀 공유로 이동" in manage_rendered)
    require("personal-share-callout-visible", "팀과 공유할 준비" in manage_rendered and "검토가 끝난 파일만" in manage_rendered and "추천 위치: 팀 리서치 공유" in manage_rendered and "이동 후 위치: 팀 공유공간 / research /" in manage_rendered)
    require("personal-share-default-target", '<option value="research" selected>' in manage_rendered and "이동 후 위치: 팀 공유공간 / research /" in manage_rendered)

    rename_response = post_form(user1_opener, "/rename_item", {"root": "personal", "path": f"research/{manage_target.name}", "new_name": renamed_name})
    rename_body = rename_response.read().decode("utf-8", "replace")
    renamed_target = delete_dir / renamed_name
    require("personal-rename-redirects-to-view", "msg=renamed" in rename_response.geturl() or "이름을 변경했습니다." in rename_body)
    require("personal-rename-source-gone", not manage_target.exists())
    require("personal-rename-destination-exists", renamed_target.exists())

    share_response = post_form(user1_opener, "/move_to_shared", {"root": "personal", "path": f"research/{renamed_name}", "shared_target": "research"})
    share_body = share_response.read().decode("utf-8", "replace")
    share_rendered = share_body.split("</style>", 1)[-1]
    shared_target = Path("/home/portal/workspaces/team-alpha/shared/research") / renamed_name
    require("personal-share-move-redirects-to-shared-view", "root=team_shared" in share_response.geturl() and ("msg=shared" in share_response.geturl() or "팀 공유로 이동" in share_body))
    require("personal-share-move-success-copy", "notice success" in share_rendered and "같은 팀원이 팀 공유공간에서 확인" in share_rendered and "개인 작업공간 목록에는 더 이상 표시" in share_rendered)
    require("shared-post-move-scope-visible", "file-scope-banner shared" in share_rendered and "공개 범위: 팀 공유공간" in share_rendered and "팀 공유됨" in share_rendered and "팀과 공유할 준비" not in share_rendered)
    require("personal-share-move-source-gone", not renamed_target.exists())
    require("personal-share-move-destination-exists", shared_target.exists())

    shared_status_response = post_form(
        user1_opener,
        "/set_file_status",
        {"root": "team_shared", "path": f"research/{renamed_name}", "file_status": "revision_needed"},
    )
    shared_status_body = shared_status_response.read().decode("utf-8", "replace")
    shared_status_view = user1_opener.open(
        f"{BASE}/view?root=team_shared&path={urllib.parse.quote('research/' + renamed_name)}",
        timeout=30,
    ).read().decode("utf-8", "replace")
    shared_status_rendered = shared_status_view.split("</style>", 1)[-1]
    require("shared-status-update-redirect", "msg=status_updated" in shared_status_response.geturl() or "파일 상태를 변경했습니다." in shared_status_body)
    require("shared-status-update-visible", "수정 필요" in shared_status_rendered and "status-revision_needed" in shared_status_rendered)
    require("shared-file-callout-visible", "팀 공유공간에 있는 파일입니다" in shared_status_rendered and "같은 팀원이 함께 확인" in shared_status_rendered)

    audit_events = []
    if AUDIT_LOG.exists():
        for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines()[-200:]:
            try:
                audit_events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    audit_actions = {event.get("action") for event in audit_events}
    require("audit-log-records-core-actions", {"upload", "rename", "move_to_shared", "archive", "restore", "permission_denied", "status_update", "csrf_denied", "login_success"} <= audit_actions)
    forwarded_events = [
        event
        for event in audit_events
        if event.get("actor") == forwarded_username and event.get("action") == "login_failed"
    ]
    require("audit-log-records-forwarded-ip", bool(forwarded_events) and forwarded_events[-1].get("client_ip") == forwarded_ip)
    require("audit-log-records-forwarded-ip-source", forwarded_events[-1].get("client_ip_source") == "CF-Connecting-IP")

    admin_activity_response = opener.open(
        f"{BASE}/admin/activity?actor=user1&action=status_update&team=team-alpha&q={urllib.parse.quote(upload_name)}",
        timeout=30,
    )
    admin_activity = read_text_response(admin_activity_response)
    if is_react_shell(admin_activity):
        require_react_shell("admin-activity-page", admin_activity_response, admin_activity, view="admin-activity", root="all")
    else:
        admin_activity_rendered = admin_activity.split("</style>", 1)[-1]
        require("admin-activity-page", "작업 기록 검색" in admin_activity_rendered and "admin-filter-form" in admin_activity_rendered)
        require("admin-activity-limit-note", "최근 1,000건 기준" in admin_activity_rendered and "최근 1,000건 안에서 검색합니다" in admin_activity_rendered)
        require("admin-activity-filters-status", "상태변경" in admin_activity_rendered and upload_name in admin_activity_rendered and "검색 결과" in admin_activity_rendered)
    api_admin_activity = json.loads(
        opener.open(
            f"{BASE}/api/admin/activity?actor=user1&action=status_update&team=team-alpha&q={urllib.parse.quote(upload_name)}",
            timeout=10,
        ).read().decode("utf-8")
    )
    require(
        "api-admin-activity",
        api_admin_activity["filters"]["actor"] == "user1"
        and api_admin_activity["filters"]["action"] == "status_update"
        and api_admin_activity["summary"]["total"] >= 1
        and any(entry["action"] == "status_update" and upload_name in entry["path"] for entry in api_admin_activity["entries"]),
    )
    require("api-admin-activity-hides-server-paths", "/home/" not in json.dumps(api_admin_activity, ensure_ascii=False))

    admin_file_search_status_response = opener.open(
        f"{BASE}/admin/search?q={urllib.parse.quote(admin_search_name)}&owner=user1&status=review_needed",
        timeout=30,
    )
    admin_file_search_status = read_text_response(admin_file_search_status_response)
    if is_react_shell(admin_file_search_status):
        require_react_shell("admin-file-search-status-filter", admin_file_search_status_response, admin_file_search_status, view="admin-search", root="all")
        api_admin_search_status = json.loads(opener.open(f"{BASE}/api/admin/search?q={urllib.parse.quote(admin_search_name)}&owner=user1&status=review_needed", timeout=10).read().decode("utf-8"))
        require("admin-file-search-controls", api_admin_search_status["filters"]["owner"] == "user1" and api_admin_search_status["filters"]["status"] == "review_needed")
    else:
        admin_file_search_status_rendered = admin_file_search_status.split("</style>", 1)[-1]
        require("admin-file-search-status-filter", admin_search_name in admin_file_search_status_rendered and "검토 필요" in admin_file_search_status_rendered and "status=review_needed" in admin_file_search_status_rendered)
        require("admin-file-search-controls", "전체 사용자" in admin_file_search_status_rendered and "전체 팀" in admin_file_search_status_rendered and "시작일" in admin_file_search_status_rendered and "종료일" in admin_file_search_status_rendered)
    admin_search_target.unlink(missing_ok=True)

    preview_failed_response = opener.open(
        f"{BASE}/admin/activity?action=preview_failed",
        timeout=30,
    )
    preview_failed_activity = read_text_response(preview_failed_response)
    if is_react_shell(preview_failed_activity):
        require_react_shell("admin-activity-preview-failed-filter", preview_failed_response, preview_failed_activity, view="admin-activity", root="all")
        api_preview_failed = json.loads(opener.open(f"{BASE}/api/admin/activity?action=preview_failed", timeout=10).read().decode("utf-8"))
        require("admin-activity-preview-failed-api", api_preview_failed["filters"]["action"] == "preview_failed")
    else:
        preview_failed_rendered = preview_failed_activity.split("</style>", 1)[-1]
        require("admin-activity-preview-failed-filter", "미리보기 실패" in preview_failed_rendered and ("조건에 맞는 작업 기록이 없습니다." in preview_failed_rendered or "audit-table" in preview_failed_rendered))

    admin_user_report_response = opener.open(
        f"{BASE}/admin/user?username=user1",
        timeout=30,
    )
    admin_user_report = read_text_response(admin_user_report_response)
    if is_react_shell(admin_user_report):
        require_react_shell("admin-user-report-page", admin_user_report_response, admin_user_report, view="admin-user", root="all")
    else:
        admin_user_report_rendered = admin_user_report.split("</style>", 1)[-1]
        require("admin-user-report-page", "사용자1 활동 보기" in admin_user_report_rendered and "작업 요약" in admin_user_report_rendered)
        require("admin-user-report-links", "개인 폴더 열기" in admin_user_report_rendered and "이 사용자 기록" in admin_user_report_rendered)
        require("admin-user-report-status-summary", "상태 변경" in admin_user_report_rendered and "최근 개인 파일" in admin_user_report_rendered)
    api_admin_user = json.loads(opener.open(f"{BASE}/api/admin/user?username=user1", timeout=10).read().decode("utf-8"))
    require(
        "api-admin-user",
        api_admin_user["user"]["username"] == "user1"
        and api_admin_user["personal"]["files"] >= 1
        and any(event["action"] == "status_update" and admin_search_name in event["path"] for event in api_admin_user["recent_events"]),
    )
    require("api-admin-user-hides-server-paths", "/home/" not in json.dumps(api_admin_user, ensure_ascii=False))

    admin_overview_after_response = opener.open(f"{BASE}/admin", timeout=30)
    admin_overview_after = read_text_response(admin_overview_after_response)
    if is_react_shell(admin_overview_after):
        require_react_shell("admin-overview-hides-selftest-events", admin_overview_after_response, admin_overview_after, view="admin-overview", root="all")
    else:
        admin_overview_rendered = admin_overview_after.split("</style>", 1)[-1]
        require(
            "admin-overview-hides-selftest-events",
            all(marker not in admin_overview_rendered for marker in ("selftest-", "portal-upload-test-", "portal_preview_tests")),
        )

    admin_activity_default_response = opener.open(f"{BASE}/admin/activity", timeout=30)
    admin_activity_default = read_text_response(admin_activity_default_response)
    if is_react_shell(admin_activity_default):
        require_react_shell("admin-activity-default-hides-selftest-events", admin_activity_default_response, admin_activity_default, view="admin-activity", root="all")
    else:
        admin_activity_default_rendered = admin_activity_default.split("</style>", 1)[-1]
        require(
            "admin-activity-default-hides-selftest-events",
            all(marker not in admin_activity_default_rendered for marker in ("selftest-", "portal-upload-test-", "portal_preview_tests")),
        )

    try:
        post_form(user1_opener, "/rename_item", {"root": "team_shared", "path": f"research/{renamed_name}", "new_name": f"blocked-{renamed_name}"})
        shared_rename_status = "allowed"
    except urllib.error.HTTPError as exc:
        shared_rename_status = str(exc.code)
    require("shared-rename-blocked", shared_rename_status == "403")

    try:
        post_form(user1_opener, "/archive_delete", {"root": "team_shared", "path": "research"})
        shared_archive_status = "allowed"
    except urllib.error.HTTPError as exc:
        shared_archive_status = str(exc.code)
    require("shared-archive-delete-blocked", shared_archive_status == "403")

    browse_response = opener.open(
        f"{BASE}/browse?root=all&path=admin/portal_preview_tests&selected=admin/portal_preview_tests/sample-docx.docx&sort=modified",
        timeout=30,
    )
    browse_url = browse_response.geturl()
    browse_body = read_text_response(browse_response)
    if is_react_shell(browse_body):
        parsed_browse = urllib.parse.urlparse(browse_url)
        browse_query = urllib.parse.parse_qs(parsed_browse.query)
        require("browse-selected-redirects-to-view", parsed_browse.path == "/app" and browse_query.get("file", [""])[0] == "admin/portal_preview_tests/sample-docx.docx")
        require("browse-selected-preserves-sort", browse_query.get("sort", [""])[0] == "modified")
        require("redirected-view-has-viewer-shell", is_react_shell(browse_body))
        require("redirected-view-has-no-inline-file-list", "file-row selected-row" not in browse_body and "viewer-file-nav" not in browse_body)
    else:
        browse_rendered = browse_body.split("</style>", 1)[-1]
        require("browse-selected-redirects-to-view", "/view?" in browse_url)
        require("browse-selected-preserves-sort", "sort=modified" in browse_url)
        require("redirected-view-has-viewer-shell", "viewer-shell" in browse_rendered)
        require("redirected-view-has-no-inline-file-list", "file-row selected-row" not in browse_rendered and "viewer-file-nav" not in browse_rendered)

    folder_response = opener.open(
        f"{BASE}/browse?root=all&path=admin/portal_preview_tests",
        timeout=30,
    )
    folder_body = read_text_response(folder_response)
    if is_react_shell(folder_body):
        require_react_shell("browse-has-file-table", folder_response, folder_body, root="all", path="admin/portal_preview_tests")
        api_folder_current = json.loads(opener.open(f"{BASE}/api/folder?root=all&path=admin/portal_preview_tests", timeout=10).read().decode("utf-8"))
        require("browse-has-kind-column", any(entry["name"] == "sample-docx.docx" for entry in api_folder_current["entries"]))
        require("browse-has-breadcrumbs", api_folder_current["path"] == "admin/portal_preview_tests")
        require("browse-has-type-badges", any(entry["kind"] == "code" for entry in api_folder_current["entries"]))
        require("browse-has-list-controls", api_folder_current["entry_count"] >= len(SAMPLES))
        require("browse-has-sort-select", api_folder_current["filters"]["sort"] == "name")
        require("browse-has-clickable-file-names", any(entry["url"].startswith("/app?") and "file=" in entry["url"] for entry in api_folder_current["entries"]))
        require("browse-has-no-row-action-buttons", "/archive_delete" not in json.dumps(api_folder_current, ensure_ascii=False))
        require("browse-has-root-badge", api_folder_current["root"]["id"] == "all")
        require("browse-has-no-viewer-shell", "viewer-shell" not in folder_body)
        require("browse-has-no-preview-empty", "preview-empty" not in folder_body)
    else:
        folder_rendered = folder_body.split("</style>", 1)[-1]
        require("browse-has-file-table", "file-table" in folder_rendered)
        require("browse-has-kind-column", "종류" in folder_rendered)
        require("browse-has-breadcrumbs", "breadcrumbs" in folder_rendered)
        require("browse-has-type-badges", "type-badge" in folder_rendered)
        require("browse-has-list-controls", "list-controls" in folder_rendered)
        require("browse-has-sort-select", "sort-select" in folder_rendered and "이름순" in folder_rendered)
        require("browse-has-clickable-file-names", "file-main" in folder_rendered and "/app?root=all" in folder_rendered and "file=" in folder_rendered)
        require("browse-has-no-row-action-buttons", "file-actions" not in folder_rendered and ">보기</a>" not in folder_rendered and "원본 다운로드" not in folder_rendered)
        require("browse-has-root-badge", "root-badge" in folder_rendered)
        require("browse-has-no-viewer-shell", "viewer-shell" not in folder_rendered)
        require("browse-has-no-preview-empty", "preview-empty" not in folder_rendered)

    root_folder_response = opener.open(
        f"{BASE}/browse?root=all",
        timeout=30,
    )
    root_folder_body = read_text_response(root_folder_response)
    if is_react_shell(root_folder_body):
        require_react_shell("browse-root-folder", root_folder_response, root_folder_body, root="all")
        api_root_folder = json.loads(opener.open(f"{BASE}/api/folder?root=all", timeout=10).read().decode("utf-8"))
        require("browse-folder-has-clickable-folder-names", any(entry["is_dir"] and entry["url"].startswith("/app?") for entry in api_root_folder["entries"]))
        require("browse-folder-download-only-toolbar", "/archive_delete" not in json.dumps(api_root_folder, ensure_ascii=False))
    else:
        root_folder_rendered = root_folder_body.split("</style>", 1)[-1]
        require("browse-folder-has-clickable-folder-names", "file-main" in root_folder_rendered and "/browse?root=" in root_folder_rendered)
        require("browse-folder-download-only-toolbar", "현재 폴더 다운로드" in root_folder_rendered and "file-actions" not in root_folder_rendered)

    sort_type_response = opener.open(
        f"{BASE}/browse?root=all&path=admin/portal_preview_tests&sort=type",
        timeout=30,
    )
    sort_type_body = read_text_response(sort_type_response)
    if is_react_shell(sort_type_body):
        api_sort_type = json.loads(opener.open(f"{BASE}/api/folder?root=all&path=admin/portal_preview_tests&sort=type", timeout=10).read().decode("utf-8"))
        sort_names = [entry["name"] for entry in api_sort_type["entries"]]
        require("browse-sort-select-type-selected", api_sort_type["filters"]["sort"] == "type")
        require("browse-sort-type-orders-code-before-doc", sort_names.index("sample-code.py") < sort_names.index("sample-docx.docx"))
    else:
        sort_type_rendered = sort_type_body.split("</style>", 1)[-1]
        require("browse-sort-select-type-selected", '<option value="type" selected>' in sort_type_rendered)
        require("browse-sort-type-orders-code-before-doc", sort_type_rendered.find("sample-code.py") < sort_type_rendered.find("sample-docx.docx"))

    filtered_response = opener.open(
        f"{BASE}/browse?root=all&path=admin/portal_preview_tests&q=sample-page",
        timeout=30,
    )
    filtered_body = read_text_response(filtered_response)
    if is_react_shell(filtered_body):
        api_filtered = json.loads(opener.open(f"{BASE}/api/folder?root=all&path=admin/portal_preview_tests&q=sample-page", timeout=10).read().decode("utf-8"))
        require("browse-search-keeps-target", any(entry["name"] == "sample-page.html" for entry in api_filtered["entries"]))
        require("browse-search-hides-other-files", all(entry["name"] != "sample-code.py" for entry in api_filtered["entries"]))
    else:
        filtered_rendered = filtered_body.split("</style>", 1)[-1]
        require("browse-search-keeps-target", "sample-page.html" in filtered_rendered)
        require("browse-search-hides-other-files", "sample-code.py" not in filtered_rendered)

    empty_response = opener.open(
        f"{BASE}/browse?root=all&path=admin/portal_preview_tests&q=no-such-portal-file",
        timeout=30,
    )
    empty_body = read_text_response(empty_response)
    if is_react_shell(empty_body):
        api_empty = json.loads(opener.open(f"{BASE}/api/folder?root=all&path=admin/portal_preview_tests&q=no-such-portal-file", timeout=10).read().decode("utf-8"))
        require("browse-search-empty-state", api_empty["entry_count"] == 0)
        require("browse-search-empty-state-copy", api_empty["filters"]["q"] == "no-such-portal-file")
        require("browse-empty-keeps-controls", api_empty["path"] == "admin/portal_preview_tests")
    else:
        empty_rendered = empty_body.split("</style>", 1)[-1]
        require("browse-search-empty-state", "empty-state" in empty_rendered)
        require("browse-search-empty-state-copy", "검색 조건에 맞는 파일이 없습니다." in empty_rendered)
        require("browse-empty-keeps-controls", "list-controls" in empty_rendered)

    personal_empty_dir = Path("/home/portal/workspaces/team-alpha/user1/research/portal-empty-selftest")
    personal_empty_dir.mkdir(parents=True, exist_ok=True)
    personal_empty_response = user1_opener.open(
        f"{BASE}/browse?root=personal&path=research/portal-empty-selftest",
        timeout=30,
    )
    personal_empty_body = read_text_response(personal_empty_response)
    if is_react_shell(personal_empty_body):
        api_personal_empty = json.loads(user1_opener.open(f"{BASE}/api/folder?root=personal&path=research/portal-empty-selftest", timeout=10).read().decode("utf-8"))
        require("personal-empty-upload-copy", api_personal_empty["entry_count"] == 0)
    else:
        personal_empty_rendered = personal_empty_body.split("</style>", 1)[-1]
        require("personal-empty-upload-copy", "파일을 업로드하거나 Hermes 봇" in personal_empty_rendered)
    personal_empty_dir.rmdir()

    pdf_filter_response = opener.open(
        f"{BASE}/browse?root=all&path=admin/portal_preview_tests&type=pdf",
        timeout=30,
    )
    pdf_filter_body = read_text_response(pdf_filter_response)
    if is_react_shell(pdf_filter_body):
        api_pdf_filter = json.loads(opener.open(f"{BASE}/api/folder?root=all&path=admin/portal_preview_tests&type=pdf", timeout=10).read().decode("utf-8"))
        require("browse-type-filter-pdf", any(entry["name"] == "sample-pdf.pdf" for entry in api_pdf_filter["entries"]) and all(entry["name"] != "sample-code.py" for entry in api_pdf_filter["entries"]))
    else:
        pdf_filter_rendered = pdf_filter_body.split("</style>", 1)[-1]
        require("browse-type-filter-pdf", "sample-pdf.pdf" in pdf_filter_rendered and "sample-code.py" not in pdf_filter_rendered)

    combo_filter_response = opener.open(
        f"{BASE}/browse?root=all&path=admin/portal_preview_tests&q=sample&type=pdf&sort=modified",
        timeout=30,
    )
    combo_filter_body = read_text_response(combo_filter_response)
    if is_react_shell(combo_filter_body):
        api_combo_filter = json.loads(opener.open(f"{BASE}/api/folder?root=all&path=admin/portal_preview_tests&q=sample&type=pdf&sort=modified", timeout=10).read().decode("utf-8"))
        require("browse-combined-filter-pdf", any(entry["name"] == "sample-pdf.pdf" for entry in api_combo_filter["entries"]) and all(entry["name"] != "sample-code.py" for entry in api_combo_filter["entries"]))
        require("browse-filter-preserves-sort-in-chips", api_combo_filter["filters"]["sort"] == "modified")
    else:
        combo_filter_rendered = combo_filter_body.split("</style>", 1)[-1]
        require("browse-combined-filter-pdf", "sample-pdf.pdf" in combo_filter_rendered and "sample-code.py" not in combo_filter_rendered)
        require("browse-filter-preserves-sort-in-chips", "sort=modified" in combo_filter_rendered)

    status_filter_response = user1_opener.open(
        f"{BASE}/browse?root=personal&path=research&status=review_needed",
        timeout=30,
    )
    status_filter_body = read_text_response(status_filter_response)
    if is_react_shell(status_filter_body):
        api_status_filter = json.loads(user1_opener.open(f"{BASE}/api/folder?root=personal&path=research&status=review_needed", timeout=10).read().decode("utf-8"))
        require(
            "browse-status-filter-review-needed",
            api_status_filter["filters"]["status"] == "review_needed"
            and all(entry["name"] != upload_name for entry in api_status_filter["entries"]),
        )
    else:
        status_filter_rendered = status_filter_body.split("</style>", 1)[-1]
        require("browse-status-filter-review-needed", upload_name not in status_filter_rendered and "상태" in status_filter_rendered)

    sample_recent = Path("/home/portal/workspaces/admin/portal_preview_tests/sample-page.html")
    sample_old = Path("/home/portal/workspaces/admin/portal_preview_tests/sample-code.py")
    now = time.time()
    os.utime(sample_recent, (now, now))
    old = now - 10 * 24 * 60 * 60
    os.utime(sample_old, (old, old))
    today = time.strftime("%Y-%m-%d")
    date_filter_response = opener.open(
        f"{BASE}/browse?root=all&path=admin/portal_preview_tests&date_from={today}",
        timeout=30,
    )
    date_filter_body = read_text_response(date_filter_response)
    if is_react_shell(date_filter_body):
        api_date_filter = json.loads(opener.open(f"{BASE}/api/folder?root=all&path=admin/portal_preview_tests&date_from={today}", timeout=10).read().decode("utf-8"))
        require("browse-date-filter-inputs", api_date_filter["filters"]["date_from"] == today)
        require("browse-date-filter-recent-only", any(entry["name"] == "sample-page.html" for entry in api_date_filter["entries"]) and all(entry["name"] != "sample-code.py" for entry in api_date_filter["entries"]))
    else:
        date_filter_rendered = date_filter_body.split("</style>", 1)[-1]
        require("browse-date-filter-inputs", 'name="date_from"' in date_filter_rendered and 'type="date"' in date_filter_rendered)
        require("browse-date-filter-recent-only", "sample-page.html" in date_filter_rendered and "sample-code.py" not in date_filter_rendered)

    stateful_view_response = opener.open(
        f"{BASE}/view?root=all&path=admin/portal_preview_tests/sample-code.py&q=sample&type=code&sort=modified",
        timeout=30,
    )
    stateful_view_rendered = stateful_view_response.read().decode("utf-8", "replace").split("</style>", 1)[-1]
    require("view-does-not-render-folder-file-list", "viewer-file-nav" not in stateful_view_rendered and "sample-style.css" not in stateful_view_rendered and "sample-docx.docx" not in stateful_view_rendered)
    require("view-folder-link-keeps-state", "q=sample" in stateful_view_rendered and "type=code" in stateful_view_rendered and "sort=modified" in stateful_view_rendered)

    advanced_state_view = user1_opener.open(
        f"{BASE}/view?root=personal&path={urllib.parse.quote('research/' + upload_name)}&status=review_needed&date_from={today}&sort=modified",
        timeout=30,
    ).read().decode("utf-8", "replace")
    advanced_state_rendered = advanced_state_view.split("</style>", 1)[-1]
    require("view-folder-link-keeps-advanced-state", "status=review_needed" in advanced_state_rendered and f"date_from={today}" in advanced_state_rendered and "sort=modified" in advanced_state_rendered)

    view_response = opener.open(
        f"{BASE}/view?root=all&path=admin/portal_preview_tests/sample-pptx.pptx",
        timeout=30,
    )
    view_body = view_response.read().decode("utf-8", "replace")
    view_rendered = view_body.split("</style>", 1)[-1]
    print(
        "view-route",
        "view-url=" + str("/view?" in view_response.geturl()),
        "viewer-shell=" + str("viewer-shell" in view_rendered),
        "sidebar=" + str("viewer-sidebar" in view_rendered),
        "folder-link=" + str("폴더 열기" in view_rendered),
    )
    require("view-has-viewer-shell", "viewer-shell" in view_rendered)
    require("view-has-no-sidebar-list", "viewer-sidebar" not in view_rendered and "viewer-sidebar-toggle" not in view_rendered and "viewer-file-nav" not in view_rendered)
    require("view-has-no-sidebar-copy", "목록 숨기기" not in view_rendered and "파일 목록" not in view_rendered and "접기" not in view_rendered)
    require("view-has-viewer-title", "viewer-title" in view_rendered)
    require("view-has-folder-link", "폴더 열기" in view_rendered)
    require("view-has-download-label", "다운로드" in view_rendered)
    viewer_actions_fragment = view_rendered.split('<div class="viewer-actions">', 1)[-1].split("</div>", 1)[0]
    require("view-primary-actions-stay-focused", "다운로드" in viewer_actions_fragment and "폴더 열기" not in viewer_actions_fragment and "이름 변경" not in viewer_actions_fragment and "보관함으로 이동" not in viewer_actions_fragment)
    require("view-preview-has-no-inner-toolbar", "<div class='toolbar'>" not in view_rendered.split('viewer-canvas">', 1)[-1])

    try:
        opener.open(
            f"{BASE}/api/folder?root=all&path=admin/portal/preview_cache",
            timeout=30,
        )
        hidden_status = "allowed"
    except urllib.error.HTTPError as exc:
        hidden_status = str(exc.code)
    print("hidden-cache", hidden_status)
    require("hidden-cache-403", hidden_status == "403")

    try:
        opener.open(
            f"{BASE}/asset?root=all&path={sample_path('sample-page.html')}",
            timeout=30,
        )
        html_asset_status = "allowed"
    except urllib.error.HTTPError as exc:
        html_asset_status = str(exc.code)
    require("html-asset-direct-blocked", html_asset_status == "403")

    raw_html_response = opener.open(
        f"{BASE}/raw?root=all&path={sample_path('sample-page.html')}",
        timeout=30,
    )
    raw_html_response.read()
    raw_html_disposition = str(raw_html_response.headers.get("Content-Disposition", "")).lower()
    raw_html_type = str(raw_html_response.headers.get("Content-Type", "")).lower()
    require("raw-html-download-only", "attachment" in raw_html_disposition and raw_html_type.startswith("text/plain"))

    for filename in SAMPLES:
        body = opener.open(
            f"{BASE}/preview?root=all&path={sample_path(filename)}",
            timeout=30,
        ).read().decode("utf-8", "replace")
        rendered = body.split("</style>", 1)[-1]
        print(
            filename,
            "document-viewer=" + str("document-viewer" in rendered),
            "raw-pdf-iframe=" + str("<iframe src='/raw" in rendered or "<iframe src='/converted" in rendered),
            "html-preview=" + str("html-preview" in rendered),
            "markdown=" + str("<article class='markdown-body'>" in rendered),
            "code-viewer=" + str("code-viewer" in rendered),
        )
        if filename.endswith(".pdf"):
            require("pdf-preview-regression", "document-viewer" in rendered)
        elif filename.endswith(".docx"):
            require("docx-preview-regression", "document-viewer" in rendered or "텍스트 미리보기" in rendered)
        elif filename.endswith(".pptx"):
            require("pptx-preview-regression", "document-viewer" in rendered or "텍스트 미리보기" in rendered)
        elif filename.endswith(".html"):
            require("html-preview-regression", "html-preview" in rendered)
            require("html-preview-uses-srcdoc", "srcdoc=" in rendered and "<iframe sandbox" in rendered)
            require("html-source-code-viewer", "code-viewer" in rendered and "HTML" in rendered and "code-line-number" in rendered)
        elif filename.endswith(".md"):
            require("md-preview-regression", "<article class='markdown-body'>" in rendered)
            require("md-code-block-line-numbers", "markdown-code-block" in rendered and "code-line-number" in rendered and "PYTHON" in rendered)
            require("md-task-list", "task-list-item" in rendered and "task-checkbox" in rendered and "checked" in rendered)
            require("md-relative-link", "/view?root=all" in rendered and "sample-style.css" in rendered)
            require("md-relative-image", "markdown-image" in rendered and "/asset_path/all/admin/portal_preview_tests/sample-diagram.svg" in rendered)
        elif filename.endswith(".py"):
            require("code-preview-regression", "code-viewer" in rendered and "code-line-number" in rendered)
            require("code-preview-copy-button", "data-copy-source" in rendered and "복사" in rendered)
        elif filename.endswith(".css"):
            require("css-code-preview-regression", "code-viewer" in rendered and "code-line-number" in rendered)
            require("css-code-preview-copy-button", "data-copy-source" in rendered and "복사" in rendered)

    asset_path_response = opener.open(
        f"{BASE}/asset_path/all/admin/portal_preview_tests/sample-style.css",
        timeout=30,
    )
    asset_path_body = asset_path_response.read().decode("utf-8", "replace")
    require("asset-path-css-route", asset_path_response.status == 200 and "color" in asset_path_body)

    try:
        opener.open(
            f"{BASE}/asset_path/all/admin/portal_preview_tests/sample-page.html",
            timeout=30,
        )
        asset_path_html_status = "allowed"
    except urllib.error.HTTPError as exc:
        asset_path_html_status = str(exc.code)
    require("asset-path-html-blocked", asset_path_html_status == "403")

    for filename in ("sample-xlsx.xlsx",):
        body = opener.open(
            f"{BASE}/preview?root=all&path={sample_path(filename)}",
            timeout=30,
        ).read().decode("utf-8", "replace")
        rendered = body.split("</style>", 1)[-1]
        print(
            "xlsx-preview",
            filename,
            "table=" + str("<table" in rendered),
            "table-scroll=" + str("table-scroll" in rendered),
            "sheet-grid=" + str("sheet-grid" in rendered),
            "sheet-tab=" + str("sheet-tab" in rendered),
            "pdf-error=" + str("PDF 변환 실패" in rendered),
            "sheet-note=" + str("선택한 시트 표 미리보기" in rendered),
        )
        require(f"xlsx-preview-regression-{filename}", "<table" in rendered and "선택한 시트 표 미리보기" in rendered)
        require(f"xlsx-table-scroll-{filename}", "table-scroll" in rendered)
        require(f"xlsx-sheet-grid-{filename}", "sheet-grid" in rendered and "sheet-row-header" in rendered and "sheet-col-header" in rendered)
        require(f"xlsx-sheet-tab-{filename}", "sheet-tab active" in rendered)
        if filename == "sample-xlsx.xlsx":
            require(f"xlsx-sheet-tabs-linkable-{filename}", "sheet=1" in rendered and "요약" in rendered)

            second_body = opener.open(
                f"{BASE}/preview?root=all&path={sample_path(filename)}&sheet=1",
                timeout=30,
            ).read().decode("utf-8", "replace")
            second_rendered = second_body.split("</style>", 1)[-1]
            require(f"xlsx-second-sheet-selected-{filename}", "선택한 시트 표 미리보기: 요약" in second_rendered and "전체 작업" in second_rendered)

    xlsx_view_body = opener.open(
        f"{BASE}/view?root=all&path={sample_path('sample-xlsx.xlsx')}&q=sample&type=sheet&sort=modified&sheet=1",
        timeout=30,
    ).read().decode("utf-8", "replace")
    xlsx_view_rendered = xlsx_view_body.split("</style>", 1)[-1]
    require("xlsx-view-sheet-tabs-preserve-state", "sheet=0" in xlsx_view_rendered and "q=sample" in xlsx_view_rendered and "type=sheet" in xlsx_view_rendered and "sort=modified" in xlsx_view_rendered)

    page_checks = [
        ("pdf_page", "sample-pdf.pdf"),
        ("converted_page", "sample-pptx.pptx"),
        ("converted_page", "sample-docx.docx"),
    ]
    for route, filename in page_checks:
        response = opener.open(
            f"{BASE}/{route}?root=all&path={sample_path(filename)}&page=1",
            timeout=30,
        )
        signature = response.read(8)
        print(
            route,
            filename,
            "status=" + str(response.status),
            "type=" + str(response.headers.get("Content-Type")),
            "png=" + str(signature == b"\x89PNG\r\n\x1a\n"),
        )
        require(f"{route}-{filename}-png", response.status == 200 and signature == b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    main()
