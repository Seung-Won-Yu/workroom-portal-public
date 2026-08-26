#!/usr/bin/env python3
import datetime as dt
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from workroom.core.scopes import normalized_rel_path, root_by_id, safe_name
from workroom.core.settings import (
    AGENT_JOB_LOG_DIR,
    AGENT_JOB_MAX_PROMPT_CHARS,
    AGENT_JOBS_PATH,
    HERMES_JOB_TIMEOUT_SECONDS,
    PERSONAL_UPLOAD_DIRS,
)

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback for local inspection only.
    fcntl = None


AGENT_ROLES = {
    "research": {
        "profile": "researchbot",
        "label": "리서치 요청",
        "folder": "research",
        "description": "자료 조사, 비교, 출처 정리, 기술 검토",
        "placeholder": "예: 내 리서치 자료나 팀 공유 자료를 바탕으로 경쟁 서비스 5개를 비교하고, 바로 의사결정할 수 있게 결론/근거/출처/다음 액션으로 정리해줘.",
        "output_hint": "짧은 질문은 대화로 답하고, 조사 요청은 핵심 결론, 비교표, 출처, 다음 액션이 보이는 리서치 문서로 저장합니다.",
        "templates": [
            "이 주제에 대해 신뢰할 수 있는 자료를 조사하고 핵심 결론, 비교표, 출처, 다음 액션을 정리해줘.",
            "선택한 참고자료를 기준으로 장단점과 리스크를 비교하고 팀이 선택할 추천안을 제시해줘.",
            "기술 검토 보고서 형태로 가능성, 제약, 구현 난이도, 확인해야 할 질문을 정리해줘.",
        ],
        "default_skills": ["llm-wiki", "ocr-and-documents"],
        "skill_rules": [
            {
                "keywords": ["논문", "paper", "arxiv", "학술", "academic", "연구"],
                "skills": ["arxiv", "research-paper-writing"],
            },
            {
                "keywords": ["pdf", "문서", "첨부", "파일", "보고서"],
                "skills": ["nano-pdf"],
            },
            {
                "keywords": ["블로그", "rss", "트렌드", "모니터", "최신 동향"],
                "skills": ["blogwatcher"],
            },
        ],
        "worker_guidance": [
            "조사 목적을 먼저 한 문장으로 재정의하세요.",
            "확인된 사실과 추론을 구분하고, 외부 자료를 사용했다면 출처 이름과 링크를 함께 남기세요.",
            "결론을 먼저 쓰고, 비교표/근거/리스크/다음 액션 순서로 정리하세요.",
            "결과 파일명은 research-YYYYMMDD-topic.md 형태를 우선 사용하세요.",
        ],
    },
    "dev": {
        "profile": "devbot",
        "label": "개발 요청",
        "folder": "dev",
        "description": "코드 수정, 실행, 테스트, 디버깅",
        "placeholder": "예: 선택한 기획/리서치 자료를 기준으로 구현 범위를 작게 나누고, 필요한 코드 수정과 테스트까지 진행해줘.",
        "output_hint": "짧은 질문은 대화로 답하고, 구현 요청은 코드/스크립트 산출물과 변경 요약, 검증 결과, 남은 리스크로 정리합니다.",
        "templates": [
            "현재 폴더의 자료를 읽고 구현 계획을 작게 나눈 뒤 필요한 코드와 실행 방법을 만들어줘.",
            "이 오류의 원인을 재현하고 수정한 뒤 실행/테스트 결과를 남겨줘.",
            "선택한 참고자료를 기준으로 기능 명세, 파일 구조, 테스트 체크리스트를 만들어줘.",
        ],
        "default_skills": ["systematic-debugging", "test-driven-development", "writing-plans"],
        "skill_rules": [
            {
                "keywords": ["코드베이스", "레포", "repository", "구조 분석", "규모", "파일 구조"],
                "skills": ["codebase-inspection"],
            },
            {
                "keywords": ["리뷰", "review", "pr", "pull request", "변경 검토"],
                "skills": ["github-code-review"],
            },
            {
                "keywords": ["계획", "설계", "분할", "명세", "plan"],
                "skills": ["plan"],
            },
            {
                "keywords": ["실험", "검증", "spike", "프로토타입"],
                "skills": ["spike"],
            },
            {
                "keywords": ["python", "파이썬", "디버거"],
                "skills": ["python-debugpy"],
            },
            {
                "keywords": ["node", "javascript", "typescript", "브라우저 디버깅"],
                "skills": ["node-inspect-debugger"],
            },
        ],
        "worker_guidance": [
            "작업 전 관련 파일과 요구사항을 먼저 확인하고, 변경 범위를 작게 유지하세요.",
            "코드나 스크립트를 만들었다면 실행 방법과 검증 결과를 반드시 기록하세요.",
            "실패하거나 확인하지 못한 테스트가 있으면 숨기지 말고 이유와 다음 조치를 적으세요.",
            "결과 파일명은 dev-YYYYMMDD-topic.md 또는 실제 산출물 이름을 우선 사용하세요.",
        ],
    },
    "summary": {
        "profile": "summarybot",
        "label": "요약/보고 요청",
        "folder": "summary",
        "description": "회의록, 요구사항, 보고서, 액션아이템 정리",
        "placeholder": "예: 선택한 리서치 자료를 읽고 팀장에게 공유할 1페이지 요약, 결정사항, 액션아이템, 리스크로 정리해줘.",
        "output_hint": "짧은 질문은 대화로 답하고, 정리 요청은 요약문, 결정사항, 액션아이템, 리스크 중심의 보고 문서로 저장합니다.",
        "templates": [
            "참고자료를 읽고 1페이지 보고서로 핵심 요약, 결정사항, 액션아이템, 리스크를 정리해줘.",
            "회의/대화 내용을 요구사항, 해야 할 일, 담당자, 마감 기준으로 정리해줘.",
            "리서치 결과를 비전문가도 이해할 수 있게 짧은 보고서와 공유 메시지로 바꿔줘.",
        ],
        "default_skills": ["ocr-and-documents", "writing-plans"],
        "skill_rules": [
            {
                "keywords": ["ppt", "pptx", "슬라이드", "발표", "발표자료", "deck"],
                "skills": ["powerpoint"],
            },
            {
                "keywords": ["구글", "google", "gmail", "drive", "docs", "sheets"],
                "skills": ["google-workspace"],
            },
            {
                "keywords": ["notion", "노션"],
                "skills": ["notion"],
            },
            {
                "keywords": ["pdf", "문서", "첨부", "스캔"],
                "skills": ["nano-pdf"],
            },
            {
                "keywords": ["인포그래픽", "시각화", "visual", "한눈에"],
                "skills": ["baoyu-infographic"],
            },
        ],
        "worker_guidance": [
            "중복 설명을 줄이고 결론, 결정사항, 액션아이템을 먼저 보이게 작성하세요.",
            "액션아이템은 담당자/기한이 없으면 미정으로 표시하고, 확인 질문을 별도로 모으세요.",
            "원문에서 확인되지 않은 내용은 추정이라고 표시하세요.",
            "결과 파일명은 summary-YYYYMMDD-topic.md 형태를 우선 사용하세요.",
        ],
    },
    "admin": {
        "profile": "adminbot",
        "label": "Adminbot 요청",
        "folder": "admin",
        "admin_only": True,
        "description": "Hermes 운영, 웹 권한, 봇 설정 점검",
        "placeholder": "예: Hermes 봇 역할, 웹 계정 권한, 개인 작업공간 흐름을 점검하고 운영 변경안을 정리해줘.",
        "output_hint": "짧은 질문은 대화로 답하고, 운영 요청은 관리자 점검 문서로 저장합니다.",
        "templates": [
            "현재 포털과 Hermes 봇 운영 흐름을 점검하고, 권한/개인 작업공간/폴더 기준으로 개선안을 정리해줘.",
            "사용자 10명, 관리자 3명 기준으로 Hermes 봇 역할과 접근 권한 세팅안을 만들어줘.",
            "웹 요청이 실패하거나 산출물이 꼬이지 않도록 운영 점검 체크리스트를 작성해줘.",
        ],
        "default_skills": ["hermes-agent", "hermes-agent-skill-authoring", "native-mcp"],
        "skill_rules": [
            {
                "keywords": ["kanban", "분해", "라우팅", "여러 봇", "작업 분배", "이어받기"],
                "skills": ["kanban-orchestrator"],
            },
            {
                "keywords": ["webhook", "웹훅", "자동화", "연동"],
                "skills": ["webhook-subscriptions"],
            },
            {
                "keywords": ["github", "저장소", "repo", "repository"],
                "skills": ["github-repo-management"],
            },
        ],
        "worker_guidance": [
            "운영 변경은 실행 전 목적, 영향 범위, 되돌리는 방법을 먼저 정리하세요.",
            "권한, 토큰, 비밀번호 같은 민감정보는 출력하지 말고 확인 절차만 남기세요.",
            "사용자/관리자/봇별 책임과 폴더 흐름을 분리해 작성하세요.",
            "결과 파일명은 admin-YYYYMMDD-topic.md 형태를 우선 사용하세요.",
        ],
    },
}

MAX_AGENT_REFERENCES = 5

DANGEROUS_AGENT_REQUEST_MESSAGE = (
    "위험하거나 권한 상승이 필요한 요청은 웹 포털에서 바로 실행할 수 없습니다. "
    "삭제, 시스템 설정 변경, 비밀정보 조회, 외부 전송, 배포/권한 변경은 관리자 승인 후 안전한 점검 요청으로 바꿔주세요."
)

DANGEROUS_AGENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsudo\b|\bsu\s+-|\bset-executionpolicy\b|관리자\s*권한|root\s*권한", re.I), "privilege_escalation"),
    (re.compile(r"\brm\s+-[^\n]*r[^\n]*f|\brm\s+-[^\n]*f[^\n]*r", re.I), "recursive_delete"),
    (re.compile(r"\bremove-item\b[^\n]*(?:-recurse|-force)|\bdel\s+/[sq]|\brmdir\s+/s", re.I), "recursive_delete"),
    (re.compile(r"\bformat\b|\bmkfs\b|\bshutdown\b|\breboot\b|\btaskkill\b|\bkillall\b|\bpkill\b", re.I), "system_control"),
    (re.compile(r"\bchmod\s+777(?=\D|$)|\bchown\b|\bicacls\b|\btakeown\b", re.I), "permission_change"),
    (re.compile(r"\b(?:curl|wget)\b[^\n|;]*(?:\|\s*(?:sh|bash|powershell|pwsh)|>\s*/)", re.I), "remote_shell"),
    (re.compile(r"\b(?:ssh|scp|rsync)\b|\bgh\s+auth\b|\bgit\s+push\b|\bnpm\s+publish\b|\bdocker\s+run\b", re.I), "external_or_publish"),
    (re.compile(r"(?:portal_initial_passwords\.txt|portal_config\.json|agent_jobs\.jsonl|audit_events\.jsonl)", re.I), "portal_sensitive_file"),
    (
        re.compile(
            r"(?:show|print|read|cat|copy|send|upload|exfiltrate|보여|출력|읽|복사|전송|업로드).{0,60}"
            r"(?:password|token|secret|credential|private[_ -]?key|\.env|id_rsa|비밀번호|토큰|시크릿|개인키)"
            r"|(?:password|token|secret|credential|private[_ -]?key|\.env|id_rsa|비밀번호|토큰|시크릿|개인키).{0,60}"
            r"(?:show|print|read|cat|copy|send|upload|exfiltrate|보여|출력|읽|복사|전송|업로드)",
            re.I,
        ),
        "secret_access",
    ),
]


def selected_skills(role: str, prompt: str, reference_path: str = "") -> list[str]:
    meta = AGENT_ROLES.get(role, {})
    text = f"{prompt}\n{reference_path}".lower()
    skills: list[str] = []
    for skill in meta.get("default_skills", []):
        if skill not in skills:
            skills.append(skill)
    for rule in meta.get("skill_rules", []):
        keywords = [str(keyword).lower() for keyword in rule.get("keywords", [])]
        if any(keyword and keyword in text for keyword in keywords):
            for skill in rule.get("skills", []):
                if skill not in skills:
                    skills.append(skill)
    return skills[:6]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def local_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


@contextmanager
def job_file_lock(path: Path = AGENT_JOBS_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        if fcntl:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def read_jobs(path: Path = AGENT_JOBS_PATH) -> list[dict]:
    if not path.exists():
        return []
    jobs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            jobs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return jobs


def write_jobs(jobs: list[dict], path: Path = AGENT_JOBS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        for job in jobs:
            tmp.write(json.dumps(job, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp_path, path)


def is_admin_user(user: dict | None) -> bool:
    return bool(user and user.get("is_admin") or str((user or {}).get("username", "")) == "admin")


def role_options(user: dict | None = None) -> list[dict]:
    return [
        {
            "role": role,
            "profile": meta["profile"],
            "label": meta["label"],
            "description": meta["description"],
            "folder": meta["folder"],
            "placeholder": meta.get("placeholder", ""),
            "output_hint": meta.get("output_hint", ""),
            "templates": meta.get("templates", []),
        }
        for role, meta in AGENT_ROLES.items()
        if not meta.get("admin_only") or is_admin_user(user)
    ]


def status_label(status: str) -> str:
    return {
        "queued": "대기중",
        "running": "실행중",
        "done": "완료",
        "failed": "실패",
        "cancelled": "취소됨",
    }.get(status, status or "-")


def default_session_title(prompt: str) -> str:
    title = " ".join(str(prompt or "").strip().split())
    if not title:
        return "새 작업"
    return title[:42] + ("..." if len(title) > 42 else "")


def agent_request_guard(role: str, prompt: str, reference_path: str = "") -> str:
    text = f"{role}\n{prompt}\n{reference_path}"
    for pattern, _reason in DANGEROUS_AGENT_PATTERNS:
        if pattern.search(text):
            return DANGEROUS_AGENT_REQUEST_MESSAGE
    return ""


def normalized_session_id(value: str = "") -> str:
    cleaned = "".join(ch for ch in str(value or "").strip() if ch.isalnum() or ch in {"-", "_"})
    return cleaned[:48] or uuid.uuid4().hex[:12]


def job_public_payload(job: dict) -> dict:
    references = job.get("references")
    public_references = []
    if isinstance(references, list):
        for item in references:
            if isinstance(item, dict):
                root = str(item.get("root") or "")
                path = str(item.get("path") or "")
                if root and path:
                    public_references.append({"root": root, "path": path})
    elif job.get("reference_root") and job.get("reference_path"):
        public_references.append({
            "root": str(job.get("reference_root") or ""),
            "path": str(job.get("reference_path") or ""),
        })
    return {
        "id": job.get("id", ""),
        "session_id": job.get("session_id") or job.get("id", ""),
        "session_title": job.get("session_title") or default_session_title(str(job.get("prompt", ""))),
        "hidden": bool(job.get("hidden_at")),
        "status": job.get("status", ""),
        "status_label": status_label(str(job.get("status", ""))),
        "role": job.get("role", ""),
        "role_label": AGENT_ROLES.get(str(job.get("role", "")), {}).get("label", str(job.get("role", ""))),
        "profile": job.get("profile", ""),
        "prompt": job.get("prompt", ""),
        "created_at": job.get("created_at", ""),
        "updated_at": job.get("updated_at", ""),
        "started_at": job.get("started_at", ""),
        "finished_at": job.get("finished_at", ""),
        "username": job.get("username", ""),
        "user_name": job.get("user_name", ""),
        "team": job.get("team", ""),
        "output_root": job.get("output_root", "personal"),
        "output_path": job.get("output_path", ""),
        "reference_root": job.get("reference_root", ""),
        "reference_path": job.get("reference_path", ""),
        "references": public_references,
        "summary": job.get("summary", ""),
        "assistant_reply": job.get("assistant_reply", ""),
        "hermes_session_id": job.get("hermes_session_id", ""),
        "error": job.get("error", ""),
        "log_path": job.get("log_path", ""),
    }


def jobs_for_user(user: dict, limit: int = 30, include_all_admin: bool = False) -> list[dict]:
    username = str(user.get("username", ""))
    with job_file_lock():
        jobs = read_jobs()
    if username != "admin" or not include_all_admin:
        jobs = [job for job in jobs if job.get("username") == username]
    jobs = [job for job in jobs if not job.get("hidden_at")]
    jobs.sort(key=lambda job: str(job.get("created_at", "")), reverse=True)
    return [job_public_payload(job) for job in jobs[:limit]]


def resolve_agent_reference(user: dict, reference_root: str, reference_path: str) -> Path:
    reference_path = normalized_rel_path(reference_path)
    if reference_root not in {"personal", "team_shared"}:
        raise PermissionError("참고자료 위치를 사용할 수 없습니다.")
    source_root = root_by_id(user, reference_root)
    if not source_root:
        raise PermissionError("참고자료 위치를 열 수 없습니다.")
    source_root_path = Path(source_root["path"]).resolve()
    source = (source_root_path / reference_path).resolve()
    if (
        not reference_path
        or not source.exists()
        or not source.is_file()
        or source_root_path not in source.parents
        or not safe_name(source.relative_to(source_root_path))
    ):
        raise PermissionError("참고자료 파일을 찾을 수 없습니다.")
    if reference_root == "personal":
        parts = [part for part in reference_path.split("/") if part]
        if not parts or parts[0] not in PERSONAL_UPLOAD_DIRS:
            raise PermissionError("개인 참고자료는 개발/리서치/요약 폴더에서만 선택할 수 있습니다.")
    return source


def normalized_agent_references(user: dict, references: object, reference_root: str = "", reference_path: str = "") -> list[dict]:
    raw_items: list[dict] = []
    if isinstance(references, list):
        for item in references:
            if isinstance(item, dict):
                raw_items.append({
                    "root": str(item.get("root") or ""),
                    "path": str(item.get("path") or ""),
                })
    elif reference_root or reference_path:
        raw_items.append({"root": reference_root, "path": reference_path})

    cleaned: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_items:
        root = str(item.get("root") or "").strip()
        path = normalized_rel_path(str(item.get("path") or ""))
        if not root and not path:
            continue
        key = (root, path)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"root": root, "path": path})

    if len(cleaned) > MAX_AGENT_REFERENCES:
        raise ValueError(f"참고자료는 최대 {MAX_AGENT_REFERENCES}개까지 선택할 수 있습니다.")

    resolved: list[dict] = []
    for item in cleaned:
        abs_path = resolve_agent_reference(user, item["root"], item["path"])
        resolved.append({
            "root": item["root"],
            "path": item["path"],
            "abs_path": str(abs_path),
        })
    return resolved


def create_job(
    user: dict,
    role: str,
    prompt: str,
    reference_root: str = "",
    reference_path: str = "",
    session_id: str = "",
    session_title: str = "",
    references: object = None,
) -> dict:
    role = role.strip()
    if role not in AGENT_ROLES:
        raise ValueError("지원하지 않는 봇 역할입니다.")
    if AGENT_ROLES[role].get("admin_only") and not is_admin_user(user):
        raise PermissionError("관리자만 사용할 수 있는 봇 역할입니다.")
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("요청 내용을 입력해주세요.")
    if len(prompt) > AGENT_JOB_MAX_PROMPT_CHARS:
        raise ValueError(f"요청 내용은 {AGENT_JOB_MAX_PROMPT_CHARS:,}자 이하로 입력해주세요.")
    normalized_references = normalized_agent_references(user, references, reference_root, reference_path)
    reference_paths_text = "\n".join(str(item.get("path") or "") for item in normalized_references)
    guard_message = agent_request_guard(role, prompt, reference_paths_text)
    if guard_message:
        raise PermissionError(guard_message)

    personal = root_by_id(user, "personal")
    if not personal:
        raise PermissionError("개인 작업공간이 있는 사용자만 봇 요청을 만들 수 있습니다.")
    personal_root = Path(personal["path"]).resolve()
    role_meta = AGENT_ROLES[role]
    output_dir = (personal_root / role_meta["folder"]).resolve()
    if personal_root not in output_dir.parents:
        raise PermissionError("봇 실행 위치가 개인 작업공간 밖입니다.")
    output_dir.mkdir(parents=True, exist_ok=True)

    primary_reference = normalized_references[0] if normalized_references else {}
    reference_root = str(primary_reference.get("root") or "")
    reference_path = str(primary_reference.get("path") or "")
    reference_abs_path = str(primary_reference.get("abs_path") or "")

    now = utc_now()
    session_id = normalized_session_id(session_id)
    session_title = default_session_title(session_title or prompt)
    job = {
        "id": uuid.uuid4().hex[:12],
        "session_id": session_id,
        "session_title": session_title,
        "status": "queued",
        "role": role,
        "role_label": role_meta["label"],
        "profile": role_meta["profile"],
        "prompt": prompt,
        "created_at": now,
        "updated_at": now,
        "username": user.get("username", ""),
        "user_name": user.get("name", ""),
        "team": user.get("team", ""),
        "cwd": str(output_dir),
        "output_root": "personal",
        "output_folder": role_meta["folder"],
        "output_path": "",
        "reference_root": reference_root,
        "reference_path": reference_path,
        "reference_abs_path": reference_abs_path,
        "references": normalized_references,
        "skills": selected_skills(role, prompt, reference_paths_text),
        "timeout_seconds": HERMES_JOB_TIMEOUT_SECONDS,
        "summary": "",
        "assistant_reply": "",
        "hermes_session_id": "",
        "error": "",
        "log_path": "",
    }
    with job_file_lock():
        jobs = read_jobs()
        jobs.append(job)
        write_jobs(jobs)
    return job_public_payload(job)


def claim_next_job() -> dict | None:
    with job_file_lock():
        jobs = read_jobs()
        for job in jobs:
            if job.get("status") == "queued" and not job.get("hidden_at"):
                now = utc_now()
                job["status"] = "running"
                job["started_at"] = now
                job["updated_at"] = now
                write_jobs(jobs)
                return dict(job)
    return None


def update_job(job_id: str, **updates) -> dict | None:
    with job_file_lock():
        jobs = read_jobs()
        for job in jobs:
            if job.get("id") == job_id:
                job.update(updates)
                job["updated_at"] = utc_now()
                write_jobs(jobs)
                return dict(job)
    return None


def cancel_job(user: dict, job_id: str) -> dict:
    username = str(user.get("username", ""))
    with job_file_lock():
        jobs = read_jobs()
        for job in jobs:
            if job.get("id") != job_id:
                continue
            if username != "admin" and job.get("username") != username:
                raise PermissionError("이 작업을 취소할 수 없습니다.")
            if job.get("status") != "queued":
                raise ValueError("대기중인 작업만 취소할 수 있습니다.")
            job["status"] = "cancelled"
            job["updated_at"] = utc_now()
            write_jobs(jobs)
            return job_public_payload(job)
    raise FileNotFoundError("작업을 찾을 수 없습니다.")


def hide_session(user: dict, session_id: str) -> dict:
    username = str(user.get("username", ""))
    session_id = str(session_id or "").strip()
    if not session_id:
        raise ValueError("대화 ID가 없습니다.")
    now = utc_now()
    count = 0
    with job_file_lock():
        jobs = read_jobs()
        for job in jobs:
            job_session_id = job.get("session_id") or job.get("id")
            if job_session_id != session_id:
                continue
            if username != "admin" and job.get("username") != username:
                raise PermissionError("이 대화를 삭제할 수 없습니다.")
            job["hidden_at"] = now
            job["hidden_by"] = username
            if job.get("status") == "queued":
                job["status"] = "cancelled"
            job["updated_at"] = now
            count += 1
        if count:
            write_jobs(jobs)
            return {"session_id": session_id, "hidden_count": count}
    raise FileNotFoundError("대화를 찾을 수 없습니다.")


def result_file_path(job: dict) -> Path:
    cwd = Path(str(job.get("cwd", ""))).resolve()
    role = str(job.get("role", "agent"))
    return cwd / f"portal-agent-{role}-{local_stamp()}-{job.get('id', 'job')}.md"


def job_log_path(job: dict) -> Path:
    AGENT_JOB_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return AGENT_JOB_LOG_DIR / f"{job.get('id', 'job')}.log"
