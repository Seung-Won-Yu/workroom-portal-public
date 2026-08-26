import html
import mimetypes
from pathlib import Path


STATIC_DIR = Path(__file__).with_name("static")
APP_DIST_DIR = STATIC_DIR / "app"
STATIC_ASSETS = {
    "/static/portal.css": ("text/css; charset=utf-8", STATIC_DIR / "portal.css"),
    "/static/preview.css": ("text/css; charset=utf-8", STATIC_DIR / "preview.css"),
}


def static_asset_response(request_path: str) -> tuple[str, bytes] | None:
    if request_path.startswith("/static/app/"):
        rel_path = request_path.removeprefix("/static/app/").strip("/")
        target = (APP_DIST_DIR / rel_path).resolve()
        try:
            target.relative_to(APP_DIST_DIR.resolve())
        except ValueError:
            return None
        if not target.is_file():
            return None
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        try:
            return content_type, target.read_bytes()
        except OSError:
            return None
    asset = STATIC_ASSETS.get(request_path)
    if not asset:
        return None
    content_type, path = asset
    try:
        return content_type, path.read_bytes()
    except OSError:
        return None


def html_page(title: str, body: str, user_name: str | None = None, nav_html: str = "") -> bytes:
    user_block = ""
    if user_name:
        user_block = f"""
        <div class="userbar">
          <span>{html.escape(user_name)}</span>
          <a href="/logout">로그아웃</a>
        </div>
        """
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="/static/portal.css">
</head>
<body>
  <header>
    <div class="header-left">
      <h1><a class="brand-link" href="/app">Workroom Portal Portal</a></h1>
      {nav_html}
    </div>
    {user_block}
  </header>
  <main>
    {body}
  </main>
  <script>
    document.addEventListener("click", async (event) => {{
      const button = event.target.closest("[data-copy-source]");
      if (!button) return;
      const source = document.getElementById(button.dataset.copySource);
      if (!source) return;
      const original = button.textContent;
      try {{
        await navigator.clipboard.writeText(source.value);
      }} catch (_error) {{
        source.focus();
        source.select();
        document.execCommand("copy");
      }}
      button.textContent = "복사됨";
      window.setTimeout(() => {{
        button.textContent = original;
      }}, 1200);
    }});
  </script>
</body>
</html>""".encode("utf-8")


def react_app_page() -> bytes | None:
    try:
        return (APP_DIST_DIR / "index.html").read_bytes()
    except OSError:
        return None


def preview_page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="/static/preview.css">
</head>
<body><main>{body}</main>
  <script>
    document.addEventListener("click", async (event) => {{
      const button = event.target.closest("[data-copy-source]");
      if (!button) return;
      const source = document.getElementById(button.dataset.copySource);
      if (!source) return;
      const original = button.textContent;
      try {{
        await navigator.clipboard.writeText(source.value);
      }} catch (_error) {{
        source.focus();
        source.select();
        document.execCommand("copy");
      }}
      button.textContent = "복사됨";
      window.setTimeout(() => {{
        button.textContent = original;
      }}, 1200);
    }});
  </script>
</body>
</html>""".encode("utf-8")
