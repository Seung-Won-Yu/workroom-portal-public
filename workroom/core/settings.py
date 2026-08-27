#!/usr/bin/env python3
import os
from pathlib import Path

# 배포 루트 — 환경변수로 바꿀 수 있다 (기본은 리눅스 서비스 계정 경로).
WORKROOM_HOME = Path(os.environ.get("WORKROOM_HOME", "/home/portal/workspaces"))
PORTAL_HOME = Path(os.environ.get("WORKROOM_PORTAL_HOME", str(WORKROOM_HOME / "admin" / "portal")))


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".log",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".sh",
    ".ps1",
}

SECRET_NAMES = {
    ".env",
    "auth.json",
    "auth.lock",
    "id_rsa",
    "id_ed25519",
    "known_hosts",
}

SECRET_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".crt", ".cer"}
SECRET_SUBSTRINGS = ("token", "secret", "credential", "password", "private_key")
MAX_PREVIEW_BYTES = 512 * 1024
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_ZIP_FILES = 1000
MAX_ZIP_SOURCE_BYTES = 300 * 1024 * 1024
LOGIN_RATE_WINDOW_SECONDS = 10 * 60
LOGIN_RATE_MAX_FAILURES = 5
MAX_RECENT_FILES = 40
MAX_SCAN_FILES = 3000
MAX_ADMIN_FILE_SEARCH_RESULTS = 120
HIDDEN_DIR_NAMES = {".archive", "planning", "portal", "preview_cache", "page_cache"}
OPERATIONAL_RECENT_PREFIXES = (
    "admin/cloudflared/",
    "admin/logs/",
    "admin/portal/",
    "admin/scripts/",
)
OPERATIONAL_RECENT_FILES = {"AGENTS.md"}
SELFTEST_PATH_MARKERS = (
    "portal_preview_tests",
    "portal-api-archive-",
    "portal-api-renamed-",
    "portal-api-upload-",
    "portal-delete-test-",
    "portal-empty-selftest",
    "portal-manage-renamed-",
    "portal-manage-test-",
    "portal-root-upload-blocked-",
    "portal-shared-upload-blocked-",
    "portal-symlink-leak-",
    "portal-upload-test-",
    "safe-rm-test",
    "selftest-",
    "uiux-sample-",
)
SELFTEST_ACTOR_PREFIXES = ("selftest-",)
ACTIVE_CONTENT_EXTENSIONS = {".html", ".htm", ".js", ".mjs"}
PROTECTED_PERSONAL_DIRS = {"dev", "research", "summary", "planning"}
PERSONAL_UPLOAD_DIRS = {
    "dev": "개발 산출물",
    "research": "조사 자료",
    "summary": "요약/보고 자료",
}
PERSONAL_UPLOAD_HINTS = {
    "dev": "코드, 스크립트, 자동화 결과물",
    "research": "리서치, 참고 문서, 수집 자료",
    "summary": "요약본, 보고서, 발표 자료",
}
SHARED_MOVE_TARGETS = {
    "research": "팀 리서치 공유",
    "dev": "팀 개발 공유",
    "summary": "팀 요약 공유",
    "handoff": "팀 인수인계 공유",
}
BLOCKED_UPLOAD_EXTENSIONS = {
    ".app",
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".dylib",
    ".exe",
    ".jar",
    ".msi",
    ".scr",
    ".so",
}
WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{idx}" for idx in range(1, 10)),
    *(f"lpt{idx}" for idx in range(1, 10)),
}
MAX_DOCX_CHARS = 40_000
MAX_XLSX_ROWS = 80
MAX_XLSX_COLS = 24
OFFICE_PREVIEW_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".odp", ".ods"}
PREVIEW_CACHE_DIR = PORTAL_HOME / "preview_cache"
PAGE_CACHE_DIR = PORTAL_HOME / "page_cache"
AUDIT_LOG_PATH = PORTAL_HOME / "audit_events.jsonl"
PDF_RENDER_DPI = 130
MAX_RENDERED_PAGES = 12
MAX_AUDIT_DISPLAY = 12
MAX_ARCHIVE_DISPLAY = 80
LARGE_FILE_BYTES = 20 * 1024 * 1024
STALE_FILE_DAYS = 14
CACHE_RETENTION_DAYS = 7
CACHE_MAX_BYTES = 500 * 1024 * 1024
AUDIT_ROTATE_BYTES = 20 * 1024 * 1024
AUDIT_ROTATION_KEEP = 5

AGENT_JOBS_PATH = Path(os.environ.get(
    "WORKROOM_AGENT_JOBS_PATH", str(PORTAL_HOME / "agent_jobs.jsonl")
))
AGENT_JOB_LOG_DIR = Path(os.environ.get(
    "WORKROOM_AGENT_JOB_LOG_DIR", str(PORTAL_HOME / "agent_job_logs")
))
# 에이전트 실행 바이너리 — 환경에 맞게 지정한다.
HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
HERMES_JOB_TIMEOUT_SECONDS = int(os.environ.get("HERMES_JOB_TIMEOUT_SECONDS", "900"))
HERMES_JOB_POLL_SECONDS = float(os.environ.get("HERMES_JOB_POLL_SECONDS", "2"))
AGENT_JOB_MAX_PROMPT_CHARS = 8000


AUDIT_ACTION_LABELS = {
    "archive": "보관",
    "csrf_denied": "요청 차단",
    "download": "다운로드",
    "login_failed": "로그인 실패",
    "login_rate_limited": "로그인 제한",
    "login_success": "로그인 성공",
    "logout": "로그아웃",
    "copy_to_agent_shared": "봇 공유자료",
    "copy_to_personal": "내 작업공간 복사",
    "agent_job_created": "봇 요청",
    "agent_job_completed": "봇 완료",
    "agent_job_failed": "봇 실패",
    "admin_audit_cleaned": "로그 정리",
    "archive_bulk_purged": "보관 일괄삭제",
    "portal_user_created": "계정 생성",
    "portal_user_disabled": "계정 비활성화",
    "portal_user_enabled": "계정 활성화",
    "portal_password_changed": "비밀번호 변경",
    "portal_password_reset": "비밀번호 초기화",
    "move_to_shared": "팀 공유",
    "permission_denied": "권한 차단",
    "preview_failed": "미리보기 실패",
    "preview_open": "미리보기",
    "rename": "이름변경",
    "restore": "복구",
    "archive_purged": "영구삭제",
    "status_update": "상태변경",
    "upload": "업로드",
    "zip_download": "묶음 다운로드",
    "zip_download_denied": "묶음 다운로드 제한",
}


FILE_STATUS_LABELS = {
    "active": "작업중",
    "new": "새 작업물",
    "review_needed": "검토 필요",
    "revision_needed": "수정 필요",
    "organized": "정리됨",
    "shared": "팀 공유됨",
}
