#!/usr/bin/env python3
import hashlib
import html
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET

from workroom.core.settings import (
    MAX_DOCX_CHARS,
    MAX_RENDERED_PAGES,
    MAX_XLSX_COLS,
    MAX_XLSX_ROWS,
    PAGE_CACHE_DIR,
    PDF_RENDER_DPI,
    PREVIEW_CACHE_DIR,
)
from workroom.core.urls import portal_url


def xml_text(element: ET.Element) -> str:
    return "".join(element.itertext()).strip()


def docx_text_preview(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            raw = zf.read("word/document.xml")
    except Exception as exc:
        return f"DOCX 텍스트를 읽을 수 없습니다: {exc}"

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return f"DOCX XML을 해석할 수 없습니다: {exc}"

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    lines = []
    for paragraph in root.findall(".//w:p", ns):
        pieces = [node.text or "" for node in paragraph.findall(".//w:t", ns)]
        text = "".join(pieces).strip()
        if text:
            lines.append(text)
    result = "\n\n".join(lines)
    if len(result) > MAX_DOCX_CHARS:
        result = result[:MAX_DOCX_CHARS] + "\n\n...[미리보기 일부만 표시됨]"
    return result or "표시할 텍스트가 없습니다."


def column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return max(0, index - 1)


def column_name(index: int) -> str:
    index += 1
    letters = []
    while index:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(ord("A") + remainder))
    return "".join(reversed(letters))


def xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    values = []
    for item in root.findall(".//x:si", ns):
        texts = [node.text or "" for node in item.findall(".//x:t", ns)]
        values.append("".join(texts))
    return values


def workbook_sheet_path(target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return "xl/" + target


def workbook_sheets_info(zf: zipfile.ZipFile) -> list[dict]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    wb_ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    targets_by_id = {}
    for rel in rels.findall(".//r:Relationship", rel_ns):
        rel_id = rel.attrib.get("Id", "")
        target = rel.attrib.get("Target", "")
        if rel_id and target:
            targets_by_id[rel_id] = workbook_sheet_path(target)

    sheets = []
    for index, sheet in enumerate(workbook.findall(".//x:sheet", wb_ns)):
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
        sheets.append(
            {
                "index": index,
                "name": sheet.attrib.get("name", f"Sheet{index + 1}"),
                "path": targets_by_id.get(rel_id, f"xl/worksheets/sheet{index + 1}.xml"),
            }
        )
    return sheets or [{"index": 0, "name": "Sheet1", "path": "xl/worksheets/sheet1.xml"}]


def xlsx_cell_value(cell: ET.Element, shared: list[str], ns: dict[str, str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        inline = cell.find(".//x:t", ns)
        return inline.text if inline is not None and inline.text is not None else ""

    value_node = cell.find("x:v", ns)
    formula_node = cell.find("x:f", ns)
    if value_node is None or value_node.text is None:
        if formula_node is not None and formula_node.text:
            return "=" + formula_node.text
        return ""

    raw_value = value_node.text
    if cell_type == "s":
        try:
            return shared[int(raw_value)]
        except (ValueError, IndexError):
            return raw_value
    if cell_type == "b":
        return "TRUE" if raw_value == "1" else "FALSE"
    return raw_value


def xlsx_grid_preview(path: Path, sheet_index: int = 0) -> dict:
    try:
        with zipfile.ZipFile(path) as zf:
            shared = xlsx_shared_strings(zf)
            sheets = workbook_sheets_info(zf)
            if sheet_index < 0 or sheet_index >= len(sheets):
                sheet_index = 0
            selected_sheet = sheets[sheet_index]
            root = ET.fromstring(zf.read(str(selected_sheet["path"])))
    except Exception as exc:
        return {
            "sheet_name": f"XLSX 시트를 읽을 수 없습니다: {exc}",
            "sheet_index": 0,
            "sheets": [],
            "rows": [],
            "col_count": 0,
            "truncated": False,
        }

    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows = []
    max_used_col = 0
    truncated = False
    source_rows = root.findall(".//x:sheetData/x:row", ns)
    for row_position, row in enumerate(source_rows, start=1):
        if len(rows) >= MAX_XLSX_ROWS:
            truncated = True
            break
        try:
            row_number = int(row.attrib.get("r", row_position))
        except ValueError:
            row_number = row_position
        values_by_col = {}
        has_value = False
        for cell in row.findall("x:c", ns):
            idx = column_index(cell.attrib.get("r", "A1"))
            if idx >= MAX_XLSX_COLS:
                truncated = True
                continue
            value = xlsx_cell_value(cell, shared, ns)
            if value:
                has_value = True
                max_used_col = max(max_used_col, idx + 1)
            values_by_col[idx] = value
        if has_value:
            rows.append((row_number, values_by_col))

    col_count = min(max_used_col, MAX_XLSX_COLS)
    normalized_rows = []
    for row_number, values_by_col in rows:
        normalized_rows.append((row_number, [values_by_col.get(index, "") for index in range(col_count)]))

    return {
        "sheet_name": str(selected_sheet["name"]),
        "sheet_index": sheet_index,
        "sheets": [{"index": int(sheet["index"]), "name": str(sheet["name"])} for sheet in sheets],
        "rows": normalized_rows,
        "col_count": col_count,
        "truncated": truncated,
    }


def pptx_slide_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            slide_names = sorted(
                name
                for name in zf.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
            if not slide_names:
                return "슬라이드 텍스트를 찾을 수 없습니다."
            root = ET.fromstring(zf.read(slide_names[0]))
    except Exception as exc:
        return f"PPTX 슬라이드를 읽을 수 없습니다: {exc}"

    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    lines = []
    for node in root.findall(".//a:t", ns):
        text = (node.text or "").strip()
        if text:
            lines.append(text)
    return "\n".join(lines) or "첫 슬라이드에서 표시할 텍스트가 없습니다."


def pptx_thumbnail(path: Path) -> tuple[bytes, str] | None:
    try:
        with zipfile.ZipFile(path) as zf:
            for name in ("docProps/thumbnail.jpeg", "docProps/thumbnail.jpg", "docProps/thumbnail.png"):
                try:
                    data = zf.read(name)
                except KeyError:
                    continue
                mime = "image/png" if name.endswith(".png") else "image/jpeg"
                return data, mime
    except Exception:
        return None
    return None


def table_html(rows: list[list[str]]) -> str:
    if not rows:
        return "<div class='card'><p class='muted'>표시할 셀 데이터가 없습니다.</p></div>"
    body = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(value)}</td>" for value in row)
        body.append(f"<tr>{cells}</tr>")
    return f"<div class='table-scroll'><table><tbody>{''.join(body)}</tbody></table></div>"


def xlsx_preview_html(
    grid: dict,
    root_id: str = "",
    rel_path: str = "",
    route: str = "/view",
    extra_params: dict[str, str] | None = None,
) -> str:
    sheet_name = str(grid.get("sheet_name", "Sheet1"))
    selected_sheet = int(grid.get("sheet_index", 0) or 0)
    sheets = grid.get("sheets", []) or [{"index": selected_sheet, "name": sheet_name}]
    tabs = []
    for sheet in sheets:
        try:
            index = int(sheet.get("index", 0))
        except (TypeError, ValueError):
            index = 0
        label = str(sheet.get("name", f"Sheet{index + 1}"))
        active = " active" if index == selected_sheet else ""
        if root_id and rel_path:
            params = {"root": root_id, "path": rel_path, "sheet": str(index)}
            if extra_params:
                params.update(extra_params)
            tab_url = portal_url(route, params)
            tabs.append(f'<a class="sheet-tab{active}" href="{html.escape(tab_url, quote=True)}">{html.escape(label)}</a>')
        else:
            tabs.append(f'<span class="sheet-tab{active}">{html.escape(label)}</span>')
    tabs_html = "".join(tabs)
    rows = grid.get("rows", [])
    col_count = int(grid.get("col_count", 0) or 0)
    truncated = bool(grid.get("truncated", False))
    if not rows or col_count <= 0:
        return f"""<section class="xlsx-preview">
          <div class="sheet-tabs">{tabs_html}</div>
          <div class="card"><p class="muted">표시할 셀 데이터가 없습니다.</p></div>
        </section>"""

    headers = "".join(f"<th class='sheet-col-header'>{column_name(index)}</th>" for index in range(col_count))
    body = []
    for row_number, values in rows:
        cells = "".join(f"<td class='sheet-cell'>{html.escape(value)}</td>" for value in values)
        body.append(f"<tr><th class='sheet-row-header'>{row_number}</th>{cells}</tr>")
    note = ""
    if truncated:
        note = f"<p class='viewer-note'>앞 {MAX_XLSX_ROWS}행, {MAX_XLSX_COLS}열까지만 미리보기로 표시합니다. 전체는 원본 다운로드로 확인하세요.</p>"
    return f"""<section class="xlsx-preview">
      <div class="sheet-tabs">{tabs_html}</div>
      <div class="table-scroll sheet-grid-scroll">
        <table class="sheet-grid">
          <thead><tr><th class="sheet-corner"></th>{headers}</tr></thead>
          <tbody>{''.join(body)}</tbody>
        </table>
      </div>
      {note}
    </section>"""


def code_preview_html(content: str, label: str) -> str:
    lines = content.splitlines()
    if not lines:
        lines = [""]
    source_id = "copy-" + hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]
    rows = []
    for index, line in enumerate(lines, start=1):
        rows.append(
            f"""<tr>
              <td class="code-line-number">{index}</td>
              <td class="code-line-code"><code>{html.escape(line)}</code></td>
            </tr>"""
        )
    line_count = len(lines)
    line_label = "1 line" if line_count == 1 else f"{line_count} lines"
    return f"""<section class="code-viewer">
      <div class="code-toolbar">
        <span>{html.escape(label)} · {line_label}</span>
        <button class="button small code-copy" type="button" data-copy-source="{source_id}">복사</button>
      </div>
      <div class="code-scroll">
        <table class="code-table"><tbody>{''.join(rows)}</tbody></table>
      </div>
      <textarea class="copy-source" id="{source_id}" readonly>{html.escape(content)}</textarea>
    </section>"""


def office_cache_key(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def convert_office_to_pdf(path: Path) -> tuple[Path | None, str | None]:
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if not binary:
        return None, "LibreOffice가 설치되어 있지 않습니다."

    PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached_pdf = PREVIEW_CACHE_DIR / f"{office_cache_key(path)}.pdf"
    if cached_pdf.exists() and cached_pdf.stat().st_size > 0:
        return cached_pdf, None

    with tempfile.TemporaryDirectory(prefix="portal-office-") as tmp:
        tmp_dir = Path(tmp)
        cmd = [
            binary,
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_dir),
            str(path),
        ]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return None, "LibreOffice 변환 시간이 초과되었습니다."
        except OSError as exc:
            return None, f"LibreOffice 실행 실패: {exc}"

        pdfs = list(tmp_dir.glob("*.pdf"))
        if result.returncode != 0 or not pdfs:
            error = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
            return None, error or "PDF 변환 결과가 생성되지 않았습니다."
        shutil.move(str(pdfs[0]), cached_pdf)
    return cached_pdf, None


def pdf_cache_key(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|dpi={PDF_RENDER_DPI}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def render_pdf_pages(path: Path) -> tuple[list[Path], str | None]:
    binary = shutil.which("pdftoppm")
    if not binary:
        return [], "poppler-utils(pdftoppm)가 설치되어 있지 않습니다."

    PAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = pdf_cache_key(path)
    page_dir = PAGE_CACHE_DIR / key
    existing = sorted(page_dir.glob("page-*.png"))
    if existing:
        return existing, None

    tmp_dir = PAGE_CACHE_DIR / f"{key}.tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    prefix = tmp_dir / "page"
    cmd = [
        binary,
        "-png",
        "-r",
        str(PDF_RENDER_DPI),
        "-f",
        "1",
        "-l",
        str(MAX_RENDERED_PAGES),
        str(path),
        str(prefix),
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return [], "PDF 이미지 변환 시간이 초과되었습니다."
    except OSError as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return [], f"pdftoppm 실행 실패: {exc}"

    pages = sorted(tmp_dir.glob("page-*.png"))
    if result.returncode != 0 or not pages:
        error = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return [], error or "PDF 페이지 이미지가 생성되지 않았습니다."

    tmp_dir.rename(page_dir)
    return sorted(page_dir.glob("page-*.png")), None

def page_gallery_html(root_q: str, rel_q: str, pages: list[Path], converted: bool, route: str | None = None, extra_params: dict[str, str] | None = None) -> str:
    route_name = "converted_page" if converted else "pdf_page"
    route_path = route or f"/{route_name}"
    images = []
    for index, _page in enumerate(pages, start=1):
        if extra_params:
            params = {"root": urllib.parse.unquote(root_q), "path": urllib.parse.unquote(rel_q), "page": str(index)}
            params.update(extra_params)
            image_src = portal_url(route_path, params)
        else:
            image_src = f"/{route_name}?root={root_q}&path={rel_q}&page={index}"
        images.append(
            f"""<figure class="page-preview">
              <div class="page-sheet">
                <img loading="lazy" src="{html.escape(image_src, quote=True)}" alt="page {index}">
              </div>
              <figcaption>페이지 {index}</figcaption>
            </figure>"""
        )
    more = ""
    if len(pages) >= MAX_RENDERED_PAGES:
        more = f"<p class='muted'>앞 {MAX_RENDERED_PAGES}페이지만 미리보기로 표시합니다. 전체는 원본 다운로드로 확인하세요.</p>"
    return "<section class='document-viewer'><div class='page-gallery'>" + "".join(images) + "</div>" + more + "</section>"


def markdown_target_url(url: str, root_id: str = "", rel_path: str = "", as_image: bool = False) -> str:
    clean_url = html.unescape(url.strip())
    if not clean_url:
        return ""
    if clean_url.startswith("#"):
        return clean_url
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", clean_url):
        if clean_url.startswith(("http://", "https://")):
            return clean_url
        return ""
    if clean_url.startswith(("/", "\\")) or not root_id:
        return ""

    parsed = urllib.parse.urlsplit(clean_url)
    raw_path = urllib.parse.unquote(parsed.path)
    parent = posixpath.dirname(rel_path)
    joined = posixpath.normpath(posixpath.join("" if parent == "." else parent, raw_path))
    if joined in ("", ".") or joined.startswith("../"):
        return ""
    joined = joined.lstrip("/")
    if as_image:
        asset_url = f"/asset_path/{urllib.parse.quote(root_id)}/{urllib.parse.quote(joined)}"
        if parsed.query:
            asset_url += "?" + parsed.query
        if parsed.fragment:
            asset_url += "#" + urllib.parse.quote(parsed.fragment)
        return asset_url
    return portal_url("/view", {"root": root_id, "path": joined})


def html_preview_srcdoc(source: str, root_id: str, rel_path: str) -> str:
    root_q = urllib.parse.quote(root_id)
    parent = posixpath.dirname(rel_path)
    if parent and parent != ".":
        base_href = f"/asset_path/{root_q}/{urllib.parse.quote(parent.strip('/'))}/"
    else:
        base_href = f"/asset_path/{root_q}/"
    base_tag = f'<base href="{html.escape(base_href, quote=True)}">'
    match = re.search(r"<head\b[^>]*>", source, flags=re.IGNORECASE)
    if match:
        return source[: match.end()] + base_tag + source[match.end() :]
    return base_tag + source


def markdown_link_html(label: str, url: str, root_id: str, rel_path: str) -> str:
    href = markdown_target_url(url, root_id, rel_path, as_image=False)
    if not href:
        return f"{label} ({html.escape(html.unescape(url))})"
    if href.startswith(("http://", "https://")):
        return f'<a href="{html.escape(href, quote=True)}" target="_blank" rel="noopener noreferrer">{label}</a>'
    return f'<a href="{html.escape(href, quote=True)}">{label}</a>'


def markdown_image_html(alt: str, url: str, root_id: str, rel_path: str) -> str:
    src = markdown_target_url(url, root_id, rel_path, as_image=True)
    if not src:
        return f'<span class="muted">이미지를 표시할 수 없습니다: {html.escape(html.unescape(url))}</span>'
    return f'<img class="markdown-image" src="{html.escape(src, quote=True)}" alt="{alt}">'


def inline_markdown(text: str, root_id: str = "", rel_path: str = "") -> str:
    escaped = html.escape(text)
    escaped = re.sub(
        r"!\[([^\]]*)\]\(([^)\s]+)\)",
        lambda match: markdown_image_html(match.group(1), match.group(2), root_id, rel_path),
        escaped,
    )
    escaped = re.sub(
        r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)",
        lambda match: markdown_link_html(match.group(1), match.group(2), root_id, rel_path),
        escaped,
    )
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    return escaped


def render_markdown(text: str, root_id: str = "", rel_path: str = "") -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    blocks = []
    paragraph = []
    list_items = []
    list_tag = "ul"
    quote_lines = []
    code_lines = []
    code_label = "CODE"
    in_code = False
    table_buffer = []

    def flush_paragraph():
        nonlocal paragraph
        if paragraph:
            blocks.append("<p>" + inline_markdown(" ".join(paragraph).strip(), root_id, rel_path) + "</p>")
            paragraph = []

    def flush_list():
        nonlocal list_items, list_tag
        if list_items:
            blocks.append(f"<{list_tag}>" + "".join(list_items) + f"</{list_tag}>")
            list_items = []
            list_tag = "ul"

    def flush_quote():
        nonlocal quote_lines
        if quote_lines:
            content = "<br>".join(inline_markdown(line, root_id, rel_path) for line in quote_lines)
            blocks.append(f"<blockquote>{content}</blockquote>")
            quote_lines = []

    def flush_table():
        nonlocal table_buffer
        if len(table_buffer) >= 2 and "|" in table_buffer[0]:
            header = [cell.strip() for cell in table_buffer[0].strip().strip("|").split("|")]
            separator = [cell.strip() for cell in table_buffer[1].strip().strip("|").split("|")]
            if all(set(cell.replace(":", "")) <= {"-"} and "-" in cell for cell in separator):
                rows = [
                    [cell.strip() for cell in row.strip().strip("|").split("|")]
                    for row in table_buffer[2:]
                    if "|" in row
                ]
                head = "".join(f"<th>{inline_markdown(cell, root_id, rel_path)}</th>" for cell in header)
                body_rows = []
                for row in rows:
                    cells = "".join(f"<td>{inline_markdown(cell, root_id, rel_path)}</td>" for cell in row)
                    body_rows.append(f"<tr>{cells}</tr>")
                blocks.append(
                    "<div style='overflow:auto'><table><thead><tr>"
                    + head
                    + "</tr></thead><tbody>"
                    + "".join(body_rows)
                    + "</tbody></table></div>"
                )
                table_buffer = []
                return
        if table_buffer:
            blocks.append("<p>" + inline_markdown(" ".join(table_buffer), root_id, rel_path) + "</p>")
            table_buffer = []

    def add_list_item(tag: str, item_html: str):
        nonlocal list_tag
        if list_items and list_tag != tag:
            flush_list()
        list_tag = tag
        list_items.append(item_html)

    def flush_all():
        flush_table()
        flush_paragraph()
        flush_list()
        flush_quote()

    for line in lines:
        stripped = line.strip()
        fence = re.match(r"^(?:```|\\`\\`\\`)\s*([A-Za-z0-9_+.#-]*)", stripped)
        if fence:
            if in_code:
                blocks.append('<div class="markdown-code-block">' + code_preview_html("\n".join(code_lines), code_label) + "</div>")
                code_lines = []
                code_label = "CODE"
                in_code = False
            else:
                flush_all()
                in_code = True
                code_label = (fence.group(1) or "code").upper()[:12]
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not stripped:
            flush_all()
            continue
        if stripped.startswith("|") and "|" in stripped[1:]:
            flush_paragraph()
            flush_list()
            flush_quote()
            table_buffer.append(stripped)
            continue
        flush_table()
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            flush_all()
            level = min(len(heading.group(1)), 4)
            blocks.append(f"<h{level}>{inline_markdown(heading.group(2), root_id, rel_path)}</h{level}>")
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            flush_list()
            quote_lines.append(stripped.lstrip(">").strip())
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        if bullet:
            flush_paragraph()
            flush_quote()
            task = re.match(r"^\[([ xX])\]\s+(.+)$", bullet.group(1))
            if task:
                checked = " checked" if task.group(1).lower() == "x" else ""
                item = (
                    f'<li class="task-list-item"><input class="task-checkbox" type="checkbox" disabled{checked}>'
                    + inline_markdown(task.group(2), root_id, rel_path)
                    + "</li>"
                )
                add_list_item("ul", item)
            else:
                add_list_item("ul", f"<li>{inline_markdown(bullet.group(1), root_id, rel_path)}</li>")
            continue
        numbered = re.match(r"^\d+\.\s+(.+)$", stripped)
        if numbered:
            flush_paragraph()
            flush_quote()
            add_list_item("ol", f"<li>{inline_markdown(numbered.group(1), root_id, rel_path)}</li>")
            continue
        flush_list()
        flush_quote()
        paragraph.append(stripped)

    if in_code:
        blocks.append('<div class="markdown-code-block">' + code_preview_html("\n".join(code_lines), code_label) + "</div>")
    flush_all()
    return "<article class='markdown-body'>" + "\n".join(blocks) + "</article>"
