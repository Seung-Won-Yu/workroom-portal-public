#!/usr/bin/env python3
import cgi
import datetime as dt
import html
import os
from pathlib import Path
import posixpath
import shutil
import tempfile

from workroom.core.scopes import (
    archive_destination,
    archive_root_path,
    can_archive_personal_path,
    can_upload_to_folder,
    cleanup_empty_archive_dirs,
    format_size,
    normalized_rel_path,
    restore_rel_from_archive_rel,
    root_by_id,
    safe_archive_rel_path,
    safe_entry_name,
    safe_name,
    safe_upload_name,
    unique_peer_path,
)
from workroom.core.settings import FILE_STATUS_LABELS, MAX_UPLOAD_BYTES, SHARED_MOVE_TARGETS
from workroom.core.urls import portal_url


class PortalActionsMixin:
    def archive_delete(self, user: dict, form: dict):
        root_id = form.get("root", [""])[0]
        rel_path = form.get("path", [""])[0]
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if (
            not root
            or not target
            or not target.exists()
            or not can_archive_personal_path(root, rel_path)
        ):
            self.audit_event(user, "permission_denied", root, rel_path, target, status="denied", reason="archive_delete")
            self.send_html(
                "보관 불가",
                "<div class='card'><h2>보관 불가</h2><p>개인공간의 산출물만 웹포털에서 보관함으로 이동할 수 있습니다. 실제 삭제는 관리자 복구 절차에서 처리합니다.</p></div>",
                403,
                user.get("name"),
            )
            return

        root_path = Path(root["path"]).resolve()
        destination = archive_destination(root_path, rel_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(destination))
        self.audit_event(
            user,
            "archive",
            root,
            rel_path,
            target,
            before_path=normalized_rel_path(rel_path),
            before_path_abs=target,
            archive_path=destination.relative_to(root_path).as_posix(),
            archive_path_abs=destination,
        )

        parent = posixpath.dirname(normalized_rel_path(rel_path))
        parent_path = "" if parent in ("", ".") else parent
        self.redirect(
            portal_url(
                "/browse",
                {
                    "root": root_id,
                    "path": parent_path,
                    "msg": "archived",
                    "archived_name": target.name,
                    "archived_path": normalized_rel_path(rel_path),
                    "archived_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "archived_by": user.get("name", user.get("username", "")),
                },
            )
        )

    def restore_archive(self, user: dict, form: dict):
        if user.get("username") != "admin":
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>관리자만 복구할 수 있습니다.</p></div>", 403, user.get("name"))
            return
        owner_name = form.get("owner", [""])[0].strip()
        archive_rel_raw = form.get("archive_path", [""])[0].strip()
        owner = self.portal.user(owner_name)
        archive_rel = safe_archive_rel_path(archive_rel_raw)
        personal = root_by_id(owner, "personal") if owner else None
        if not owner or not archive_rel or not personal:
            self.audit_event(user, "permission_denied", None, archive_rel_raw, None, status="denied", reason="restore_archive_invalid")
            self.send_html("복구 불가", "<div class='card'><h2>복구 불가</h2><p>보관 항목 정보를 확인할 수 없습니다.</p></div>", 400, user.get("name"))
            return

        personal_root = Path(personal["path"]).resolve()
        archive_root = archive_root_path(personal_root).resolve()
        archive_target = (personal_root / archive_rel).resolve()
        if (
            not archive_target.exists()
            or archive_root != archive_target
            and archive_root not in archive_target.parents
        ):
            self.audit_event(user, "permission_denied", personal, archive_rel, archive_target, status="denied", reason="restore_archive_missing")
            self.send_html("복구 불가", "<div class='card'><h2>복구 불가</h2><p>보관함 안에서 대상 파일을 찾을 수 없습니다.</p></div>", 404, user.get("name"))
            return

        restore_rel = restore_rel_from_archive_rel(archive_rel)
        restore_path = (personal_root / restore_rel).resolve()
        if personal_root not in restore_path.parents or not safe_name(restore_path.relative_to(personal_root)):
            self.audit_event(user, "permission_denied", personal, archive_rel, archive_target, status="denied", reason="restore_destination")
            self.send_html("복구 불가", "<div class='card'><h2>복구 불가</h2><p>복구 위치가 허용되지 않습니다.</p></div>", 403, user.get("name"))
            return

        restore_path.parent.mkdir(parents=True, exist_ok=True)
        destination = unique_peer_path(restore_path, archive_target.is_dir())
        shutil.move(str(archive_target), str(destination))
        cleanup_empty_archive_dirs(archive_target.parent, archive_root)
        restored_rel = destination.relative_to(personal_root).as_posix()
        self.audit_event(
            user,
            "restore",
            personal,
            restored_rel,
            destination,
            owner=owner["username"],
            owner_name=owner.get("name", owner["username"]),
            before_path=archive_rel,
            before_path_abs=archive_target,
            after_path=restored_rel,
            after_path_abs=destination,
        )
        self.redirect(portal_url("/admin/archive", {"msg": "restored"}))

    def rename_item(self, user: dict, form: dict):
        root_id = form.get("root", [""])[0]
        rel_path = form.get("path", [""])[0]
        new_name = form.get("new_name", [""])[0].strip()
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if (
            not root
            or not target
            or not target.exists()
            or not can_archive_personal_path(root, rel_path)
            or not safe_entry_name(new_name)
        ):
            self.audit_event(user, "permission_denied", root, rel_path, target, status="denied", reason="rename_item")
            self.send_html(
                "이름변경 불가",
                "<div class='card'><h2>이름변경 불가</h2><p>개인공간 산출물만 안전한 이름으로 변경할 수 있습니다.</p></div>",
                403,
                user.get("name"),
            )
            return

        destination = (target.parent / new_name).resolve()
        root_path = Path(root["path"]).resolve()
        if root_path not in destination.parents or destination.exists() or not safe_name(destination.relative_to(root_path)):
            self.audit_event(user, "permission_denied", root, rel_path, target, status="denied", reason="rename_conflict")
            self.send_html(
                "이름변경 불가",
                "<div class='card'><h2>이름변경 불가</h2><p>같은 이름이 이미 있거나 허용되지 않은 위치입니다.</p></div>",
                409,
                user.get("name"),
            )
            return

        was_file = target.is_file()
        target.rename(destination)
        new_rel = destination.relative_to(root_path).as_posix()
        self.audit_event(
            user,
            "rename",
            root,
            new_rel,
            destination,
            before_path=normalized_rel_path(rel_path),
            before_path_abs=target,
            after_path=new_rel,
            after_path_abs=destination,
        )
        if was_file:
            self.redirect(portal_url("/view", {"root": root_id, "path": new_rel, "msg": "renamed"}))
        else:
            self.redirect(portal_url("/browse", {"root": root_id, "path": new_rel, "msg": "renamed"}))

    def move_to_shared(self, user: dict, form: dict):
        root_id = form.get("root", [""])[0]
        rel_path = form.get("path", [""])[0]
        shared_target = form.get("shared_target", [""])[0].strip()
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        shared_root = self.portal.root_for(user, "team_shared")
        if (
            not root
            or not target
            or not target.exists()
            or root.get("id") != "personal"
            or not can_archive_personal_path(root, rel_path)
            or shared_target not in SHARED_MOVE_TARGETS
            or not shared_root
        ):
            self.audit_event(user, "permission_denied", root, rel_path, target, status="denied", reason="move_to_shared")
            self.send_html(
                "공유 이동 불가",
                "<div class='card'><h2>공유 이동 불가</h2><p>개인공간 산출물만 같은 팀 공유로 이동할 수 있습니다.</p></div>",
                403,
                user.get("name"),
            )
            return

        shared_root_path = Path(shared_root["path"]).resolve()
        destination_dir = (shared_root_path / shared_target).resolve()
        if shared_root_path != destination_dir and shared_root_path not in destination_dir.parents:
            self.audit_event(user, "permission_denied", root, rel_path, target, status="denied", reason="move_target")
            self.send_html("공유 이동 불가", "<div class='card'><h2>공유 이동 불가</h2><p>허용되지 않은 공유 위치입니다.</p></div>", 403, user.get("name"))
            return

        destination_dir.mkdir(parents=True, exist_ok=True)
        was_file = target.is_file()
        destination = unique_peer_path(destination_dir / target.name, target.is_dir())
        shutil.move(str(target), str(destination))
        new_rel = destination.relative_to(shared_root_path).as_posix()
        self.audit_event(
            user,
            "move_to_shared",
            shared_root,
            new_rel,
            destination,
            before_root_id=root.get("id", ""),
            before_root_label=root.get("label", ""),
            before_path=normalized_rel_path(rel_path),
            before_path_abs=target,
            after_root_id=shared_root.get("id", ""),
            after_root_label=shared_root.get("label", ""),
            after_path=new_rel,
            after_path_abs=destination,
        )
        if was_file:
            self.redirect(portal_url("/view", {"root": "team_shared", "path": new_rel, "msg": "shared"}))
        else:
            self.redirect(portal_url("/browse", {"root": "team_shared", "path": new_rel, "msg": "shared"}))

    def set_file_status(self, user: dict, form: dict):
        root_id = form.get("root", [""])[0]
        rel_path = form.get("path", [""])[0]
        status_key = form.get("file_status", [""])[0].strip()
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if (
            not root
            or not target
            or not target.exists()
            or not target.is_file()
            or status_key not in FILE_STATUS_LABELS
        ):
            self.audit_event(user, "permission_denied", root, rel_path, target, status="denied", reason="set_file_status", requested_status=status_key)
            self.send_html(
                "상태 변경 불가",
                "<div class='card'><h2>상태 변경 불가</h2><p>허용되지 않은 파일이거나 사용할 수 없는 상태입니다.</p></div>",
                403,
                user.get("name"),
            )
            return
        self.audit_event(
            user,
            "status_update",
            root,
            rel_path,
            target,
            file_status=status_key,
            file_status_label=FILE_STATUS_LABELS[status_key],
        )
        self.redirect(portal_url("/view", {"root": root_id, "path": rel_path, "msg": "status_updated"}))

    def upload_error_card_html(self, title: str, message: str, actions: list[str], guide: str = "", detail: str = "") -> str:
        action_items = "".join(f"<li>{html.escape(action)}</li>" for action in actions)
        detail_html = f"<p class='muted'>{html.escape(detail)}</p>" if detail else ""
        return f"""<div class="card upload-error-card">
          <h2>{html.escape(title)}</h2>
          <p>{html.escape(message)}</p>
          <ul class="upload-error-actions">{action_items}</ul>
          {detail_html}
        </div>{guide}"""

    def upload_size_error_html(self) -> str:
        return self.upload_error_card_html(
            "파일이 너무 큽니다",
            f"한 번에 업로드할 수 있는 최대 용량은 {format_size(MAX_UPLOAD_BYTES)}입니다.",
            [
                "파일을 압축하거나 여러 개로 나눠서 다시 업로드하세요.",
                "반드시 큰 파일을 공유해야 한다면 관리자에게 공유 방법을 문의하세요.",
            ],
        )

    def upload_file(self, user: dict):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self.send_html(
                "업로드 불가",
                self.upload_error_card_html(
                    "파일을 다시 선택해주세요",
                    "업로드할 파일이 전달되지 않았습니다.",
                    [
                        "파일 선택 버튼으로 파일을 다시 고른 뒤 업로드하세요.",
                        "계속 실패하면 브라우저를 새로고침한 뒤 다시 시도하세요.",
                    ],
                ),
                400,
                user.get("name"),
            )
            return
        if length > MAX_UPLOAD_BYTES:
            self.send_html(
                "업로드 용량 초과",
                self.upload_size_error_html(),
                413,
                user.get("name"),
            )
            return
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            self.send_html(
                "업로드 불가",
                self.upload_error_card_html(
                    "업로드 화면에서 다시 시도해주세요",
                    "현재 요청 형식으로는 파일을 받을 수 없습니다.",
                    [
                        "포털의 업로드 폼에서 파일을 다시 선택한 뒤 업로드하세요.",
                        "외부 도구나 복사한 요청으로 업로드하지 말고 브라우저 화면을 사용하세요.",
                    ],
                ),
                400,
                user.get("name"),
            )
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(length),
            },
        )
        if not self.verify_csrf_value(user, form.getfirst("csrf_token", "")):
            return
        root_id = form.getfirst("root", "")
        rel_path = form.getfirst("path", "")
        root, folder = self.portal.resolve_path(user, root_id, rel_path)
        if not root or not folder or not can_upload_to_folder(root, folder, rel_path):
            reason = "upload_folder_scope" if root and root.get("id") == "personal" else "upload_file"
            guide = self.upload_location_guide_html(root) if root and root.get("id") == "personal" else ""
            self.audit_event(user, "permission_denied", root, rel_path, folder, status="denied", reason=reason)
            self.send_html(
                "업로드 위치 확인",
                self.upload_error_card_html(
                    "업로드 위치 확인",
                    "현재 위치에는 직접 업로드할 수 없습니다.",
                    [
                        "개인 작업공간의 개발 산출물, 조사 자료, 요약/보고 자료 중 파일 성격에 맞는 폴더를 먼저 여세요.",
                        "팀 공유공간에는 직접 업로드하지 않습니다. 개인 작업공간에서 확인한 뒤 팀 공유로 이동하세요.",
                    ],
                    guide,
                ),
                403,
                user.get("name"),
            )
            return
        if "file" not in form:
            self.send_html(
                "업로드 불가",
                self.upload_error_card_html(
                    "파일을 다시 선택해주세요",
                    "선택된 파일이 없습니다.",
                    [
                        "파일 선택 버튼으로 업로드할 파일을 고른 뒤 다시 시도하세요.",
                        "파일을 고른 뒤 업로드 버튼을 눌렀는지 확인하세요.",
                    ],
                ),
                400,
                user.get("name"),
            )
            return
        upload_item = form["file"]
        if isinstance(upload_item, list):
            upload_item = upload_item[0]
        filename = upload_item.filename or ""
        if not filename or filename != Path(filename).name or not safe_upload_name(filename):
            self.audit_event(user, "permission_denied", root, rel_path, folder, status="denied", reason="unsafe_upload_name", filename=filename)
            self.send_html(
                "파일명 확인",
                self.upload_error_card_html(
                    "파일 이름을 바꿔주세요",
                    "파일명이 안전하지 않거나 허용되지 않는 형식입니다.",
                    [
                        "파일명을 report-v1.pdf처럼 단순하게 바꾼 뒤 다시 업로드하세요.",
                        "끝 공백/마침표, Windows 예약어(CON, AUX, NUL 등), 숨김 파일명, token/secret/password 같은 보안성 이름은 사용할 수 없습니다.",
                        "실행 파일과 설치 파일(.exe, .bat, .cmd, .msi, .jar 등)은 업로드할 수 없습니다.",
                    ],
                ),
                403,
                user.get("name"),
            )
            return

        root_path = Path(root["path"]).resolve()
        destination = unique_peer_path((folder / filename).resolve(), is_dir=False)
        if root_path not in destination.parents or not safe_name(destination.relative_to(root_path)):
            self.audit_event(user, "permission_denied", root, rel_path, folder, status="denied", reason="upload_destination", filename=filename)
            self.send_html(
                "업로드 위치 확인",
                self.upload_error_card_html(
                    "저장 위치를 다시 확인해주세요",
                    "허용되지 않은 저장 위치입니다.",
                    [
                        "개발 산출물, 조사 자료, 요약/보고 자료 중 파일 성격에 맞는 위치에서 다시 업로드하세요.",
                        "계속 실패하면 관리자에게 파일명과 업로드하려던 위치를 알려주세요.",
                    ],
                    self.upload_location_guide_html(root),
                ),
                403,
                user.get("name"),
            )
            return

        fd, tmp_name = tempfile.mkstemp(prefix="portal-upload-", dir=str(folder))
        tmp_path = Path(tmp_name)
        os.close(fd)
        try:
            written = 0
            with tmp_path.open("wb") as out:
                while True:
                    chunk = upload_item.file.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise ValueError("upload too large")
                    out.write(chunk)
            shutil.move(str(tmp_path), str(destination))
        except ValueError:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            self.send_html(
                "업로드 용량 초과",
                self.upload_size_error_html(),
                413,
                user.get("name"),
            )
            return
        except OSError as exc:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            self.send_html(
                "업로드 실패",
                self.upload_error_card_html(
                    "저장 중 문제가 발생했습니다",
                    "파일을 저장하는 중 문제가 발생했습니다.",
                    [
                        "파일명을 더 짧고 단순하게 바꾼 뒤 다시 업로드하세요.",
                        "파일을 다시 선택해서 업로드하세요.",
                        "계속 실패하면 관리자에게 파일명과 업로드 위치를 알려주세요.",
                    ],
                    detail=f"상세 오류: {exc}",
                ),
                500,
                user.get("name"),
            )
            return

        new_rel = destination.relative_to(root_path).as_posix()
        self.audit_event(
            user,
            "upload",
            root,
            new_rel,
            destination,
            after_path=new_rel,
            after_path_abs=destination,
            file_size=destination.stat().st_size,
        )
        self.redirect(portal_url("/view", {"root": root_id, "path": new_rel, "msg": "uploaded"}))

