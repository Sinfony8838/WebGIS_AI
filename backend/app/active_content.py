"""Response policy for authorized, untrusted uploaded and generated files.

Call this only from file-serving endpoints, after their ownership/path checks.
Application HTML and trusted presentation markup must not use this policy.
"""
from pathlib import Path

from starlette.responses import FileResponse


HTML_CONTENT_SECURITY_POLICY = "; ".join((
    "sandbox allow-scripts",
    "default-src 'none'",
    "script-src 'unsafe-inline'",
    "style-src 'unsafe-inline'",
    "img-src data: blob:",
    "font-src data:",
    "media-src data: blob:",
    "connect-src 'none'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-src 'none'",
))
SVG_CONTENT_SECURITY_POLICY = "sandbox; script-src 'none'; object-src 'none'"


def apply_file_policy(response: FileResponse, path: Path | str) -> FileResponse:
    """Keep self-contained HTML interactive without granting the app's origin.

    SVG stays an image, including its inline styling, but cannot run scripts
    when opened directly as a document. The existing FileResponse owns bytes,
    ranges, conditional requests and disposition; unrelated headers survive.
    """
    suffix = Path(path).suffix.lower()
    if suffix in {".html", ".htm"}:
        response.media_type = "text/html"
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.headers["Content-Security-Policy"] = HTML_CONTENT_SECURITY_POLICY
    elif suffix == ".svg":
        response.media_type = "image/svg+xml"
        response.headers["Content-Type"] = "image/svg+xml"
        response.headers["Content-Security-Policy"] = SVG_CONTENT_SECURITY_POLICY
    else:
        return response
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
