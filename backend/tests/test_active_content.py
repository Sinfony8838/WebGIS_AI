"""Tiny local files only; no application runtime, credentials or production data."""
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from backend.app.active_content import (
    HTML_CONTENT_SECURITY_POLICY,
    SVG_CONTENT_SECURITY_POLICY,
    apply_file_policy,
)
from backend.app.private_file_cache import PrivateFileCacheMiddleware


@pytest.mark.parametrize("suffix", [".html", ".htm", ".HTML", ".HTM"])
def test_html_has_an_opaque_origin_and_only_self_contained_resources(suffix):
    response = apply_file_policy(FileResponse(f"material{suffix}"), f"material{suffix}")
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["x-content-type-options"] == "nosniff"
    directives = {
        parts[0]: parts[1:]
        for directive in response.headers["content-security-policy"].split(";")
        if (parts := directive.split())
    }
    assert directives["sandbox"] == ["allow-scripts"]
    assert directives["script-src"] == ["'unsafe-inline'"]
    assert directives["style-src"] == ["'unsafe-inline'"]
    assert directives["img-src"] == ["data:", "blob:"]
    assert directives["font-src"] == ["data:"]
    assert directives["media-src"] == ["data:", "blob:"]
    for name in ("default-src", "connect-src", "object-src", "base-uri", "form-action", "frame-src"):
        assert directives[name] == ["'none'"]


@pytest.mark.parametrize("suffix", [".svg", ".SVG"])
def test_svg_stays_an_image_with_inline_css_but_no_document_scripts(suffix):
    response = apply_file_policy(FileResponse(f"map{suffix}"), f"map{suffix}")
    assert response.media_type == "image/svg+xml"
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.headers["content-security-policy"] == SVG_CONTENT_SECURITY_POLICY
    assert "style-src" not in SVG_CONTENT_SECURITY_POLICY
    assert "default-src" not in SVG_CONTENT_SECURITY_POLICY
    assert "content-disposition" not in response.headers


def test_policy_preserves_existing_file_response_and_unrelated_headers():
    response = FileResponse("material.html", status_code=206, headers={
        "Cache-Control": "private, no-store",
        "Vary": "Cookie, Authorization",
        "Content-Range": "bytes 0-9/20",
        "Content-Disposition": 'attachment; filename="material.html"',
    })
    original = dict(response.headers)
    assert apply_file_policy(response, Path("material.html")) is response
    assert response.status_code == 206
    for name in ("cache-control", "vary", "content-range", "content-disposition", "accept-ranges"):
        assert response.headers[name] == original[name]


@pytest.mark.parametrize("suffix", [".png", ".gif", ".pdf", ".geojson", ".docx", ".txt"])
def test_non_active_files_are_unchanged(suffix):
    response = FileResponse(f"material{suffix}", headers={"Cache-Control": "private, no-store"})
    original = list(response.raw_headers)
    media_type = response.media_type
    assert apply_file_policy(response, f"material{suffix}") is response
    assert response.raw_headers == original
    assert response.media_type == media_type


@pytest.mark.parametrize("suffix,policy", [
    (".html", HTML_CONTENT_SECURITY_POLICY),
    (".svg", SVG_CONTENT_SECURITY_POLICY),
    (".txt", None),
])
def test_served_bytes_range_head_and_private_cache_survive_policy(tmp_path, suffix, policy):
    data = b"0123456789abcdef0123456789abcdef"
    path = tmp_path / f"material{suffix}"
    path.write_bytes(data)

    async def file_endpoint(request):
        return apply_file_policy(FileResponse(path), path)

    app = Starlette(routes=[Route("/files/material", file_endpoint, methods=["GET", "HEAD"])])
    app.add_middleware(PrivateFileCacheMiddleware)
    with TestClient(app) as client:
        complete = client.get("/files/material")
        partial = client.get("/files/material", headers={
            "Range": "bytes=2-9", "If-Range": complete.headers["etag"],
        })
        head = client.head("/files/material")
    assert complete.status_code == 200
    assert complete.content == data
    assert partial.status_code == 206
    assert partial.content == data[2:10]
    assert partial.headers["content-range"] == f"bytes 2-9/{len(data)}"
    assert partial.headers["content-length"] == "8"
    assert partial.headers["etag"] == complete.headers["etag"]
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == str(len(data))
    for response in (complete, partial, head):
        assert response.headers["cache-control"] == "private, no-store, max-age=0"
        assert response.headers["accept-ranges"] == "bytes"
        assert response.headers.get("content-security-policy") == policy
