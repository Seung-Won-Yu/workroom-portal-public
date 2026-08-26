#!/usr/bin/env python3
"""Maintenance helper for the Workroom Portal portal.

The command is intentionally conservative:
- dry-run is the default
- user outputs are archived only when they match known QA/test names
- queued/running agent jobs are never changed
- generated caches may be deleted only with --apply
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


PORTAL_DIR = Path("/home/portal/workspaces/admin/portal")
DEFAULT_CONFIG = PORTAL_DIR / "portal_config.json"
DEFAULT_HERMES_PROFILES = Path("/home/portal/.hermes/profiles")
ACTIVE_JOB_STATUSES = {"queued", "running"}
TEST_NAME_MARKERS = (
    "portal-api-",
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
SKIP_DIR_NAMES = {
    ".archive",
    ".git",
    "__pycache__",
    "node_modules",
    "page_cache",
    "portal",
    "preview_cache",
}


@dataclass
class Candidate:
    source: Path
    action: str
    reason: str
    destination: Path | None = None
    bytes: int = 0


@dataclass
class Report:
    apply: bool
    stamp: str
    test_artifacts: list[Candidate] = field(default_factory=list)
    cache_items: list[Candidate] = field(default_factory=list)
    request_dumps: list[Candidate] = field(default_factory=list)
    session_files: list[Candidate] = field(default_factory=list)
    job_records_archived: int = 0
    job_records_kept: int = 0
    active_jobs_skipped: int = 0
    job_logs: list[Candidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean and archive portal operational files.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--portal-dir", type=Path, default=PORTAL_DIR)
    parser.add_argument("--hermes-profiles", type=Path, default=DEFAULT_HERMES_PROFILES)
    parser.add_argument("--apply", action="store_true", help="Apply the cleanup. Default is dry-run.")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable report.")
    parser.add_argument("--job-retention-days", type=int, default=30)
    parser.add_argument("--session-retention-days", type=int, default=30)
    parser.add_argument("--request-dump-retention-days", type=int, default=7)
    parser.add_argument("--cache-retention-days", type=int, default=7)
    parser.add_argument("--test-artifact-days", type=int, default=0)
    return parser.parse_args()


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def cutoff(days: int) -> float:
    return (now_utc() - dt.timedelta(days=days)).timestamp()


def path_size(path: Path) -> int:
    try:
        if path.is_file() or path.is_symlink():
            return path.stat().st_size
        total = 0
        for current, _dirs, files in os.walk(path):
            for name in files:
                item = Path(current) / name
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
        return total
    except OSError:
        return 0


def safe_load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for idx in range(1, 10_000):
        candidate = parent / f"{stem}-{idx}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find unique destination for {path}")


def move_candidate(candidate: Candidate, apply: bool) -> None:
    if not apply or candidate.destination is None:
        return
    candidate.destination.parent.mkdir(parents=True, exist_ok=True)
    destination = unique_destination(candidate.destination)
    shutil.move(str(candidate.source), str(destination))
    candidate.destination = destination


def delete_candidate(candidate: Candidate, apply: bool) -> None:
    if not apply:
        return
    try:
        if candidate.source.is_dir():
            shutil.rmtree(candidate.source)
        else:
            candidate.source.unlink()
    except FileNotFoundError:
        return


def iter_workspace_roots(config_path: Path) -> list[Path]:
    config = safe_load_json(config_path)
    roots: dict[str, Path] = {}
    users = config.get("users", {})
    if isinstance(users, dict):
        iterable = users.values()
    elif isinstance(users, list):
        iterable = users
    else:
        iterable = []
    for user in iterable:
        for root in user.get("roots", []):
            root_path = Path(str(root.get("path", ""))).expanduser()
            if root_path.is_absolute() and root_path.exists():
                roots[str(root_path.resolve())] = root_path.resolve()
    all_roots = sorted(roots.values(), key=lambda item: len(str(item)), reverse=True)
    specific_roots: list[Path] = []
    for root in all_roots:
        if any(is_parent(root, other) for other in all_roots if other != root):
            continue
        specific_roots.append(root)
    return sorted(specific_roots, key=lambda item: str(item))


def is_parent(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def is_test_artifact(path: Path) -> bool:
    text = "/".join(path.parts).lower()
    name = path.name.lower()
    return any(marker in name or marker in text for marker in TEST_NAME_MARKERS)


def archive_destination_for_workspace(root: Path, source: Path, stamp: str) -> Path:
    try:
        relative = source.relative_to(root)
    except ValueError:
        relative = Path(source.name)
    return root / ".archive" / "deleted" / stamp / "maintenance" / relative


def find_test_artifacts(roots: Iterable[Path], stamp: str, min_age_days: int) -> list[Candidate]:
    candidates: list[Candidate] = []
    min_mtime = cutoff(min_age_days)
    for root in roots:
        if not root.exists():
            continue
        for current, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
            current_path = Path(current)
            for name in filenames:
                source = current_path / name
                if not is_test_artifact(source):
                    continue
                try:
                    if source.stat().st_mtime > min_mtime:
                        continue
                except OSError:
                    continue
                candidates.append(
                    Candidate(
                        source=source,
                        action="archive",
                        reason="known portal QA/test artifact",
                        destination=archive_destination_for_workspace(root, source, stamp),
                        bytes=path_size(source),
                    )
                )
    return candidates


def find_cache_items(portal_dir: Path, retention_days: int) -> list[Candidate]:
    candidates: list[Candidate] = []
    min_mtime = cutoff(retention_days)
    for cache_name in ("preview_cache", "page_cache"):
        cache_dir = portal_dir / cache_name
        if not cache_dir.exists():
            continue
        for item in cache_dir.iterdir():
            try:
                if item.stat().st_mtime > min_mtime:
                    continue
            except OSError:
                continue
            candidates.append(
                Candidate(
                    source=item,
                    action="delete",
                    reason=f"{cache_name} older than {retention_days} days",
                    bytes=path_size(item),
                )
            )
    return candidates


def archive_destination_for_operations(portal_dir: Path, stamp: str, *parts: str) -> Path:
    return portal_dir / "log_archive" / "maintenance" / stamp / Path(*parts)


def find_hermes_session_files(
    hermes_profiles: Path,
    portal_dir: Path,
    stamp: str,
    session_days: int,
    dump_days: int,
) -> tuple[list[Candidate], list[Candidate]]:
    request_dumps: list[Candidate] = []
    session_files: list[Candidate] = []
    if not hermes_profiles.exists():
        return request_dumps, session_files
    session_cutoff = cutoff(session_days)
    dump_cutoff = cutoff(dump_days)
    for profile_dir in sorted(hermes_profiles.iterdir()):
        sessions_dir = profile_dir / "sessions"
        if not sessions_dir.is_dir():
            continue
        for item in sessions_dir.iterdir():
            if not item.is_file():
                continue
            try:
                mtime = item.stat().st_mtime
            except OSError:
                continue
            if item.name.startswith("request_dump_") and mtime <= dump_cutoff:
                request_dumps.append(
                    Candidate(
                        source=item,
                        action="archive",
                        reason=f"Hermes request dump older than {dump_days} days",
                        destination=archive_destination_for_operations(
                            portal_dir,
                            stamp,
                            "hermes_profiles",
                            profile_dir.name,
                            "sessions",
                            item.name,
                        ),
                        bytes=path_size(item),
                    )
                )
            elif item.name.startswith("session_") and item.suffix == ".json" and mtime <= session_cutoff:
                session_files.append(
                    Candidate(
                        source=item,
                        action="archive",
                        reason=f"Hermes session older than {session_days} days",
                        destination=archive_destination_for_operations(
                            portal_dir,
                            stamp,
                            "hermes_profiles",
                            profile_dir.name,
                            "sessions",
                            item.name,
                        ),
                        bytes=path_size(item),
                    )
                )
    return request_dumps, session_files


def parse_job_timestamp(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except ValueError:
        return None


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"_raw": line, "status": "unknown"})
    return rows


def write_jsonl_atomic(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        tmp_path = Path(handle.name)
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    tmp_path.replace(path)


def compact_agent_jobs(portal_dir: Path, stamp: str, retention_days: int, apply: bool, report: Report) -> None:
    jobs_path = portal_dir / "agent_jobs.jsonl"
    jobs = read_jsonl(jobs_path)
    if not jobs:
        return
    keep: list[dict] = []
    archive: list[dict] = []
    threshold = now_utc() - dt.timedelta(days=retention_days)
    for job in jobs:
        status = str(job.get("status", "")).lower()
        if status in ACTIVE_JOB_STATUSES:
            keep.append(job)
            report.active_jobs_skipped += 1
            continue
        finished = parse_job_timestamp(job.get("finished_at") or job.get("updated_at") or job.get("created_at"))
        if finished is not None and finished < threshold:
            archive.append(job)
        else:
            keep.append(job)
    report.job_records_archived = len(archive)
    report.job_records_kept = len(keep)
    if apply and archive:
        archive_path = archive_destination_for_operations(portal_dir, stamp, "agent_jobs.archived.jsonl")
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with archive_path.open("w", encoding="utf-8") as handle:
            for row in archive:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        backup_path = archive_destination_for_operations(portal_dir, stamp, "agent_jobs.before.jsonl")
        shutil.copy2(jobs_path, backup_path)
        write_jsonl_atomic(jobs_path, keep)


def find_agent_logs(portal_dir: Path, stamp: str, retention_days: int) -> list[Candidate]:
    log_dir = portal_dir / "agent_job_logs"
    candidates: list[Candidate] = []
    if not log_dir.exists():
        return candidates
    min_mtime = cutoff(retention_days)
    for item in log_dir.iterdir():
        if not item.is_file():
            continue
        try:
            if item.stat().st_mtime > min_mtime:
                continue
        except OSError:
            continue
        candidates.append(
            Candidate(
                source=item,
                action="archive",
                reason=f"agent job log older than {retention_days} days",
                destination=archive_destination_for_operations(portal_dir, stamp, "agent_job_logs", item.name),
                bytes=path_size(item),
            )
        )
    return candidates


def candidate_to_dict(candidate: Candidate) -> dict:
    return {
        "source": str(candidate.source),
        "action": candidate.action,
        "reason": candidate.reason,
        "destination": str(candidate.destination) if candidate.destination else None,
        "bytes": candidate.bytes,
    }


def report_to_dict(report: Report) -> dict:
    return {
        "mode": "apply" if report.apply else "dry-run",
        "stamp": report.stamp,
        "test_artifacts": [candidate_to_dict(item) for item in report.test_artifacts],
        "cache_items": [candidate_to_dict(item) for item in report.cache_items],
        "request_dumps": [candidate_to_dict(item) for item in report.request_dumps],
        "session_files": [candidate_to_dict(item) for item in report.session_files],
        "agent_job_logs": [candidate_to_dict(item) for item in report.job_logs],
        "job_records": {
            "archived": report.job_records_archived,
            "kept": report.job_records_kept,
            "active_skipped": report.active_jobs_skipped,
        },
        "warnings": report.warnings,
    }


def total_bytes(candidates: Iterable[Candidate]) -> int:
    return sum(item.bytes for item in candidates)


def print_human_report(report: Report) -> None:
    mode = "APPLY" if report.apply else "DRY RUN"
    print(f"Workroom portal maintenance - {mode}")
    print(f"stamp: {report.stamp}")
    print()
    rows = (
        ("test artifacts to archive", len(report.test_artifacts), total_bytes(report.test_artifacts)),
        ("cache items to delete", len(report.cache_items), total_bytes(report.cache_items)),
        ("request dumps to archive", len(report.request_dumps), total_bytes(report.request_dumps)),
        ("old session files to archive", len(report.session_files), total_bytes(report.session_files)),
        ("agent job logs to archive", len(report.job_logs), total_bytes(report.job_logs)),
    )
    for label, count, bytes_ in rows:
        print(f"- {label}: {count} ({bytes_} bytes)")
    print(
        "- job records: "
        f"archive {report.job_records_archived}, keep {report.job_records_kept}, "
        f"active skipped {report.active_jobs_skipped}"
    )
    if report.warnings:
        print()
        print("Warnings:")
        for warning in report.warnings:
            print(f"- {warning}")
    if not report.apply:
        print()
        print("No files changed. Re-run with --apply to execute this plan.")


def main() -> int:
    args = parse_args()
    stamp = now_utc().astimezone().strftime("%Y%m%d-%H%M%S")
    report = Report(apply=args.apply, stamp=stamp)
    if not args.config.exists():
        report.warnings.append(f"config not found: {args.config}")
    roots = iter_workspace_roots(args.config)
    report.test_artifacts = find_test_artifacts(roots, stamp, args.test_artifact_days)
    report.cache_items = find_cache_items(args.portal_dir, args.cache_retention_days)
    request_dumps, session_files = find_hermes_session_files(
        args.hermes_profiles,
        args.portal_dir,
        stamp,
        args.session_retention_days,
        args.request_dump_retention_days,
    )
    report.request_dumps = request_dumps
    report.session_files = session_files
    report.job_logs = find_agent_logs(args.portal_dir, stamp, args.job_retention_days)
    compact_agent_jobs(args.portal_dir, stamp, args.job_retention_days, args.apply, report)

    for candidate in report.test_artifacts + report.request_dumps + report.session_files + report.job_logs:
        move_candidate(candidate, args.apply)
    for candidate in report.cache_items:
        delete_candidate(candidate, args.apply)

    if args.json:
        print(json.dumps(report_to_dict(report), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_human_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
