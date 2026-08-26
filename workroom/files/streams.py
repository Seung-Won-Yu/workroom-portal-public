#!/usr/bin/env python3
import datetime as dt
import html
import os
from pathlib import Path
import shutil
import stat as stat_module
import tempfile
import urllib.parse
import unicodedata
import zipfile

from workroom.core.scopes import content_type_for, format_size, safe_name
from workroom.files.preview import convert_office_to_pdf, pptx_thumbnail, render_pdf_pages
from workroom.core.settings import (
    ACTIVE_CONTENT_EXTENSIONS,
    MAX_ZIP_FILES,
    MAX_ZIP_SOURCE_BYTES,
    OFFICE_PREVIEW_EXTENSIONS,
)
from workroom.web.ui import preview_page


class FileStreamMixin:
    def preview_file(self, user: dict, query: dict):
        root_id = query.get("root", [""])[0]
        rel_path = query.get("path", [""])[0]
        try:
            xlsx_sheet = int(query.get("sheet", ["0"])[0])
        except (TypeError, ValueError):
            xlsx_sheet = 0
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if not root or not target or not target.exists() or not target.is_file():
            data = preview_page("접근 불가", "<div class='card'><h2>접근 불가</h2><p>허용되지 않은 파일입니다.</p></div>")
        else:
            data = preview_page(
                target.name,
                self.file_preview_body(
                    root,
                    target,
                    rel_path,
                    include_folder_link=False,
                    show_toolbar=False,
                    show_heading=False,
                    xlsx_sheet=xlsx_sheet,
                    xlsx_route="/preview",
                ),
            )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def converted_file(self, user: dict, query: dict):
        root_id = query.get("root", [""])[0]
        rel_path = query.get("path", [""])[0]
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if (
            not root
            or not target
            or not target.exists()
            or not target.is_file()
            or target.suffix.lower() not in OFFICE_PREVIEW_EXTENSIONS
        ):
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>허용되지 않은 파일입니다.</p></div>", 403, user.get("name"))
            return
        pdf_path, error = convert_office_to_pdf(target)
        if not pdf_path:
            self.audit_event(user, "preview_failed", root, rel_path, target, status="failed", reason="office_pdf_convert", error=error or "")
            self.send_html("변환 실패", f"<div class='card'><h2>변환 실패</h2><p>{html.escape(error or 'PDF 변환에 실패했습니다.')}</p></div>", 500, user.get("name"))
            return
        self.stream_file(pdf_path, download_name=f"{target.stem}.pdf", inline=True)

    def page_from_query(self, query: dict) -> int:
        try:
            page = int(query.get("page", ["1"])[0])
        except (TypeError, ValueError):
            page = 1
        return max(1, page)

    def stream_png_page(self, pages: list[Path], page: int):
        if page < 1 or page > len(pages):
            self.send_html("페이지 없음", "<div class='card'><h2>페이지 없음</h2><p>없는 페이지입니다.</p></div>", 404)
            return
        path = pages[page - 1]
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "private, max-age=3600")
        self.end_headers()
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def pdf_page(self, user: dict, query: dict):
        root_id = query.get("root", [""])[0]
        rel_path = query.get("path", [""])[0]
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if not root or not target or not target.exists() or not target.is_file() or target.suffix.lower() != ".pdf":
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>허용되지 않은 파일입니다.</p></div>", 403, user.get("name"))
            return
        pages, error = render_pdf_pages(target)
        if not pages:
            self.audit_event(user, "preview_failed", root, rel_path, target, status="failed", reason="pdf_page_render", error=error or "")
            self.send_html("변환 실패", f"<div class='card'><h2>변환 실패</h2><p>{html.escape(error or 'PDF 페이지 변환에 실패했습니다.')}</p></div>", 500, user.get("name"))
            return
        self.stream_png_page(pages, self.page_from_query(query))

    def converted_page(self, user: dict, query: dict):
        root_id = query.get("root", [""])[0]
        rel_path = query.get("path", [""])[0]
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if (
            not root
            or not target
            or not target.exists()
            or not target.is_file()
            or target.suffix.lower() not in OFFICE_PREVIEW_EXTENSIONS
        ):
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>허용되지 않은 파일입니다.</p></div>", 403, user.get("name"))
            return
        pdf_path, error = convert_office_to_pdf(target)
        if not pdf_path:
            self.audit_event(user, "preview_failed", root, rel_path, target, status="failed", reason="office_pdf_convert", error=error or "")
            self.send_html("변환 실패", f"<div class='card'><h2>변환 실패</h2><p>{html.escape(error or 'PDF 변환에 실패했습니다.')}</p></div>", 500, user.get("name"))
            return
        pages, page_error = render_pdf_pages(pdf_path)
        if not pages:
            self.audit_event(user, "preview_failed", root, rel_path, target, status="failed", reason="office_page_render", error=page_error or "")
            self.send_html("변환 실패", f"<div class='card'><h2>변환 실패</h2><p>{html.escape(page_error or '페이지 이미지 변환에 실패했습니다.')}</p></div>", 500, user.get("name"))
            return
        self.stream_png_page(pages, self.page_from_query(query))

    def raw_file(self, user: dict, query: dict):
        root_id = query.get("root", [""])[0]
        rel_path = query.get("path", [""])[0]
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if not root or not target or not target.exists() or not target.is_file():
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>허용되지 않은 파일입니다.</p></div>", 403, user.get("name"))
            return
        suffix = target.suffix.lower()
        if suffix in ACTIVE_CONTENT_EXTENSIONS or suffix == ".svg":
            self.stream_file(
                target,
                download_name=target.name,
                inline=False,
                content_type_override="text/plain; charset=utf-8",
                extra_headers={"X-Content-Type-Options": "nosniff"},
            )
            return
        self.stream_file(target, download_name=target.name, inline=True, extra_headers={"X-Content-Type-Options": "nosniff"})

    def asset_file(self, user: dict, query: dict):
        root_id = query.get("root", [""])[0]
        rel_path = query.get("path", [""])[0]
        self.stream_asset(user, root_id, rel_path)

    def asset_path_file(self, user: dict, request_path: str):
        prefix = "/asset_path/"
        encoded = request_path[len(prefix):]
        if "/" not in encoded:
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>허용되지 않은 에셋입니다.</p></div>", 403, user.get("name"))
            return
        root_id, rel_path = encoded.split("/", 1)
        self.stream_asset(user, urllib.parse.unquote(root_id), urllib.parse.unquote(rel_path))

    def stream_asset(self, user: dict, root_id: str, rel_path: str):
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if not root or not target or not target.exists() or not target.is_file():
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>허용되지 않은 파일입니다.</p></div>", 403, user.get("name"))
            return
        suffix = target.suffix.lower()
        if suffix in ACTIVE_CONTENT_EXTENSIONS:
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>실행 가능한 웹 파일은 직접 열 수 없습니다. 파일 보기 화면의 안전한 미리보기를 사용하세요.</p></div>", 403, user.get("name"))
            return
        allowed = suffix in {".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico"}
        if not allowed:
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>허용되지 않은 에셋입니다.</p></div>", 403, user.get("name"))
            return
        extra_headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"}
        if suffix == ".svg":
            extra_headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"
        self.stream_file(target, download_name=target.name, inline=True, extra_headers=extra_headers)

    def thumbnail(self, user: dict, query: dict):
        root_id = query.get("root", [""])[0]
        rel_path = query.get("path", [""])[0]
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if not root or not target or not target.exists() or not target.is_file() or target.suffix.lower() != ".pptx":
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>허용되지 않은 파일입니다.</p></div>", 403, user.get("name"))
            return
        thumb = pptx_thumbnail(target)
        if not thumb:
            self.audit_event(user, "preview_failed", root, rel_path, target, status="failed", reason="pptx_thumbnail_missing")
            self.send_html("썸네일 없음", "<div class='card'><h2>썸네일 없음</h2><p>이 PPTX에는 내장 썸네일이 없습니다.</p></div>", 404, user.get("name"))
            return
        data, mime = thumb
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.end_headers()
        self.wfile.write(data)

    def download(self, user: dict, query: dict):
        root_id = query.get("root", [""])[0]
        rel_path = query.get("path", [""])[0]
        root, target = self.portal.resolve_path(user, root_id, rel_path)
        if not root or not target or not target.exists():
            self.audit_event(user, "permission_denied", root, rel_path, target, status="denied", reason="download")
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>허용되지 않은 파일입니다.</p></div>", 403, user.get("name"))
            return
        if target.is_dir():
            self.download_zip(user, root, rel_path, target)
        elif target.is_file():
            self.audit_event(user, "download", root, rel_path, target, file_size=target.stat().st_size)
            self.stream_file(target, download_name=target.name)
        else:
            self.send_html("접근 불가", "<div class='card'><h2>접근 불가</h2><p>지원하지 않는 항목입니다.</p></div>", 403, user.get("name"))

    def stream_file(
        self,
        path: Path,
        download_name: str,
        inline: bool = False,
        content_type_override: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
        mime = content_type_override or content_type_for(path)
        self.send_response(200)
        self.send_header("Content-Type", mime)
        disposition = "inline" if inline else "attachment"
        self.send_header("Content-Disposition", self.content_disposition_header(disposition, download_name))
        self.send_header("Content-Length", str(path.stat().st_size))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def content_disposition_header(self, disposition: str, download_name: str) -> str:
        clean_name = download_name.replace("\\", "_").replace("/", "_").replace("\r", "_").replace("\n", "_")
        clean_name = unicodedata.normalize("NFC", clean_name)
        ascii_name = clean_name.encode("ascii", errors="ignore").decode("ascii").replace('"', "_")
        if not ascii_name or ascii_name.startswith("."):
            ascii_name = "download" + Path(clean_name).suffix.encode("ascii", errors="ignore").decode("ascii")
        encoded_name = urllib.parse.quote(clean_name, safe="")
        return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"

    def download_zip(self, user: dict, root: dict, rel_path: str, target: Path):
        root_path = Path(root["path"]).resolve()
        base_name = target.name or root["id"]
        files_to_zip: list[tuple[Path, str, os.stat_result]] = []
        total_source_bytes = 0
        for current, dirs, files in os.walk(target):
            safe_dirs = []
            for dirname in dirs:
                directory = Path(current) / dirname
                try:
                    resolved_dir = directory.resolve()
                    rel_dir = resolved_dir.relative_to(root_path)
                    if directory.is_symlink() or not safe_name(Path(dirname)) or not safe_name(rel_dir):
                        continue
                except (OSError, ValueError):
                    continue
                safe_dirs.append(dirname)
            dirs[:] = safe_dirs
            for filename in files:
                source = Path(current) / filename
                try:
                    if source.is_symlink():
                        continue
                    resolved_source = source.resolve()
                    rel_to_root = resolved_source.relative_to(root_path)
                    if not safe_name(rel_to_root):
                        continue
                    source_stat = source.lstat()
                    if not stat_module.S_ISREG(source_stat.st_mode):
                        continue
                except (OSError, ValueError):
                    continue
                archive_name = source.relative_to(target).as_posix()
                total_source_bytes += source_stat.st_size
                files_to_zip.append((source, archive_name, source_stat))
                if len(files_to_zip) > MAX_ZIP_FILES or total_source_bytes > MAX_ZIP_SOURCE_BYTES:
                    self.audit_event(
                        user,
                        "zip_download_denied",
                        root,
                        rel_path,
                        target,
                        status="denied",
                        file_count=len(files_to_zip),
                        source_bytes=total_source_bytes,
                    )
                    self.send_html(
                        "ZIP 제한",
                        f"<div class='card'><h2>ZIP 제한</h2><p>한 번에 ZIP으로 받을 수 있는 범위는 파일 {MAX_ZIP_FILES}개, 원본 {format_size(MAX_ZIP_SOURCE_BYTES)}까지입니다. 하위 폴더 단위로 나눠 받아주세요.</p></div>",
                        413,
                        user.get("name"),
                    )
                    return

        fd, tmp_name = tempfile.mkstemp(prefix="workroom-", suffix=".zip")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                written_count = 0
                for source, archive_name, expected_stat in files_to_zip:
                    fd = None
                    try:
                        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                        fd = os.open(source, flags)
                        current_stat = os.fstat(fd)
                        if (
                            not stat_module.S_ISREG(current_stat.st_mode)
                            or current_stat.st_dev != expected_stat.st_dev
                            or current_stat.st_ino != expected_stat.st_ino
                            or current_stat.st_size != expected_stat.st_size
                            or current_stat.st_mtime_ns != expected_stat.st_mtime_ns
                        ):
                            continue
                        timestamp = dt.datetime.fromtimestamp(current_stat.st_mtime)
                        timestamp = max(timestamp, dt.datetime(1980, 1, 1))
                        info = zipfile.ZipInfo(archive_name, timestamp.timetuple()[:6])
                        info.external_attr = (current_stat.st_mode & 0xFFFF) << 16
                        info.compress_type = zipfile.ZIP_DEFLATED
                        with os.fdopen(fd, "rb") as source_file:
                            fd = None
                            with zf.open(info, "w") as zip_file:
                                shutil.copyfileobj(source_file, zip_file, 1024 * 1024)
                        written_count += 1
                    except OSError:
                        continue
                    finally:
                        if fd is not None:
                            try:
                                os.close(fd)
                            except OSError:
                                pass
            self.audit_event(
                user,
                "zip_download",
                root,
                rel_path,
                target,
                file_count=written_count,
                source_bytes=total_source_bytes,
                zip_size=tmp_path.stat().st_size,
            )
            self.stream_file(tmp_path, download_name=f"{base_name}.zip")
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass
