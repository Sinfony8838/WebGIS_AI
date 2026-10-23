"""Wire/parser boundaries against independent apps; never import main/runtime."""
import asyncio
import io
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.requests import ClientDisconnect

from backend.app.services.request_limits import (
    BodySizeLimitMiddleware, BudgetedUploadRoute, UploadBudget, build_route_budgets,
)


class Body(BaseModel):
    blob: str


def make_app(budget=None, limit=64, endpoint_failure=None):
    app = FastAPI()
    app.router.route_class = BudgetedUploadRoute
    app.add_middleware(BodySizeLimitMiddleware, max_json_body_bytes=limit,
                       route_budgets={"/upload": budget or UploadBudget(32, 1, 1, 16)})
    seen = []

    @app.post("/echo")
    @app.post("/auth/register")
    async def echo(body: Body):
        seen.append("json")
        return {"bytes": len(body.blob)}

    @app.post("/upload")
    async def upload(files: list[UploadFile] = File(...), title: str = Form("")):
        sizes = [len(await file.read()) for file in files]
        if endpoint_failure is not None:
            raise endpoint_failure
        seen.append("upload")
        return {"sizes": sizes, "title": title}

    return app, seen


@pytest.fixture
def spools(monkeypatch):
    files = []

    class Spool(io.BytesIO):
        _rolled = False

        def __init__(self):
            super().__init__()
            self.written = 0

        def write(self, data):
            self.written += len(data)
            return super().write(data)

    def create(*args, **kwargs):
        file = Spool()
        files.append(file)
        return file

    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", create)
    return files


@pytest.mark.parametrize("media", ["application/json", "application/problem+json", "Application/JSON",
                                   "application/octet-stream", "text/plain", None])
def test_all_media_types_are_bounded_without_trusting_length(media):
    app, seen = make_app()
    headers = {"content-length": "1"}
    if media:
        headers["content-type"] = media
    with TestClient(app) as client:
        result = client.post("/echo", content=json.dumps({"blob": "x" * 512}), headers=headers)
    assert result.status_code == 413
    assert seen == []


@pytest.mark.parametrize("media", ["application/json", "application/problem+json"])
def test_legal_json_and_exact_wire_limit_reach_model(media):
    raw = b'{"blob":"abc"}'
    app, seen = make_app(limit=len(raw))
    with TestClient(app) as client:
        assert client.post("/echo", content=raw, headers={"content-type": media}).json() == {"bytes": 3}
        assert client.post("/echo", content=raw + b" ", headers={"content-type": media}).status_code == 413
    assert seen == ["json"]


def test_registration_uses_existing_8k_actual_byte_budget():
    app, seen = make_app(limit=32 * 1024 * 1024)
    with TestClient(app) as client:
        response = client.post("/auth/register", content=json.dumps({"blob": "x" * 8192}),
                               headers={"content-type": "application/problem+json", "content-length": "1"})
    assert response.status_code == 413
    assert seen == []


def test_existing_large_upload_defaults_and_config_overrides():
    mib = 1024 * 1024
    expected = {
        "/datasets/upload": (512, 1, 8), "/kb/materials/upload": (50, 1, 5),
        "/media/video-upload": (100, 1, 2), "/image-library/upload": (20, 1, 2),
        "/ppt/render": (50, 1, 0), "/projects/{project_id}/presentations": (50, 1, 1),
        "/question-banks/import": (50, 4, 1), "/lesson-design/import-docx": (20, 1, 1),
        "/projects/{project_id}/timeline/generate": (20, 1, 0),
    }
    budgets = build_route_budgets()
    for path, (size, count, fields) in expected.items():
        budget = budgets[path]
        assert (budget.max_file_bytes, budget.max_files, budget.max_fields) == (size * mib, count, fields)
        assert budget.max_body_bytes == size * mib * count + fields * mib + 64 * 1024
    configured = build_route_budgets(SimpleNamespace(max_video_upload_bytes=127, max_dataset_upload_bytes=511))
    assert configured["/media/video-upload"].max_file_bytes == 127
    assert configured["/datasets/upload"].max_file_bytes == 511


async def asgi_call(app, chunks, *, path="/upload", headers=(), root_path=""):
    sent = []
    calls = []

    async def receive():
        index = len(calls)
        calls.append(index)
        value = chunks[index]
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, dict):
            return value
        return {"type": "http.request", "body": value, "more_body": index < len(chunks) - 1}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "http_version": "1.1", "method": "POST", "path": path,
             "raw_path": path.encode(), "query_string": b"", "headers": list(headers),
             "scheme": "http", "server": ("test", 80), "client": ("test", 123), "root_path": root_path}
    await app(scope, receive, send)
    return sent, calls


@pytest.mark.parametrize("template", list(build_route_budgets()))
@pytest.mark.parametrize("trailing", ["", "/"])
def test_route_templates_select_budget_before_any_body_read(template, trailing):
    observed = []

    async def inner(scope, receive, send):
        observed.append(scope["webgis.request_budget"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = BodySizeLimitMiddleware(inner, 64)
    path = "/api" + template.replace("{project_id}", "school-project") + trailing
    sent, calls = asyncio.run(asgi_call(middleware, [], path=path, root_path="/api"))
    assert observed == [build_route_budgets()[template]]
    assert sent[0]["status"] == 200 and calls == []


def test_legal_multipart_and_exact_file_limit_are_closed(spools):
    app, seen = make_app()
    with TestClient(app) as client:
        response = client.post("/upload", files={"files": ("file.bin", b"x" * 32)}, data={"title": "legal"})
    assert response.status_code == 200
    assert response.json() == {"sizes": [32], "title": "legal"}
    assert seen == ["upload"]
    assert all(file.closed for file in spools)


@pytest.mark.parametrize("case", ["file_size", "file_count", "unknown_file", "field_size", "field_count"])
def test_parser_limits_before_endpoint_and_cleanup(case, spools):
    app, seen = make_app()
    files = [("files", ("file.bin", b"x" * (33 if case == "file_size" else 8)))]
    fields = {"title": "x" * (17 if case == "field_size" else 1)}
    if case in {"file_count", "unknown_file"}:
        files.append(("ignored" if case == "unknown_file" else "files", ("extra.bin", b"extra")))
    if case == "field_count":
        fields["ignored"] = "extra"
    with TestClient(app) as client:
        response = client.post("/upload", files=files, data=fields)
    assert response.status_code == 413
    assert seen == []
    assert all(file.closed for file in spools)
    if case == "file_size":
        assert sum(file.written for file in spools) == 0


def test_four_question_bank_files_are_accepted_but_fifth_rejected(spools):
    app, seen = make_app(UploadBudget(8, 4, 0))
    with TestClient(app) as client:
        files = [("files", (f"{i}.docx", b"x" * 8)) for i in range(5)]
        assert client.post("/upload", files=files[:4]).status_code == 200
        assert client.post("/upload", files=files).status_code == 413
    assert seen == ["upload"]
    assert all(file.closed for file in spools)


PART_START = b'--BOUND\r\nContent-Disposition: form-data; name="files"; filename="a"\r\n\r\n'
MULTIPART_HEADERS = [(b"content-type", b"multipart/form-data; boundary=BOUND"), (b"content-length", b"1")]


def test_wire_overflow_aborts_without_drain_and_closes_partial_file(spools):
    app, seen = make_app(UploadBudget(64, 1, 0, overhead_bytes=128))
    chunks = [PART_START + b"a" * 8, b"b" * 200, AssertionError("must not drain")]
    sent, calls = asyncio.run(asgi_call(app, chunks, headers=MULTIPART_HEADERS))
    assert [item["status"] for item in sent if item["type"] == "http.response.start"] == [413]
    assert len(calls) == 2 and seen == []
    assert spools and all(file.closed for file in spools)
    assert sum(file.written for file in spools) == 8


@pytest.mark.parametrize("failure", [ClientDisconnect, asyncio.CancelledError])
def test_disconnect_and_cancel_close_partial_files(failure, spools):
    app, seen = make_app(UploadBudget(64, 1, 0))
    end = {"type": "http.disconnect"} if failure is ClientDisconnect else asyncio.CancelledError()
    with pytest.raises(failure):
        asyncio.run(asgi_call(app, [PART_START + b"a" * 8, end], headers=MULTIPART_HEADERS))
    assert seen == [] and spools and all(file.closed for file in spools)


def test_incomplete_form_closes_files_and_never_calls_endpoint(spools):
    app, seen = make_app()
    sent, _ = asyncio.run(asgi_call(app, [PART_START + b"x"], headers=MULTIPART_HEADERS))
    assert sent[0]["status"] == 400
    assert seen == [] and spools and all(file.closed for file in spools)


def test_endpoint_cancellation_also_closes_completed_files(spools):
    app, seen = make_app(endpoint_failure=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(asgi_call(app, [PART_START + b"x\r\n--BOUND--\r\n"], headers=MULTIPART_HEADERS))
    assert seen == [] and spools and all(file.closed for file in spools)


def test_part_header_budget_rejects_before_creating_spool(spools):
    app, seen = make_app(UploadBudget(1024, 1, 0, overhead_bytes=64))
    raw = PART_START.replace(b'filename="a"', b'filename="' + b"x" * 80 + b'"') + b"x\r\n--BOUND--\r\n"
    sent, _ = asyncio.run(asgi_call(app, [raw], headers=MULTIPART_HEADERS))
    assert sent[0]["status"] == 413 and seen == [] and spools == []


def test_declared_oversize_never_reads_request():
    app, seen = make_app()
    sent, calls = asyncio.run(asgi_call(app, [], path="/echo", headers=[(b"content-length", b"65")]))
    assert sent[0]["status"] == 413 and calls == [] and seen == []


def test_huge_content_length_is_rejected_without_integer_conversion_failure():
    app, seen = make_app()
    sent, calls = asyncio.run(asgi_call(app, [], path="/echo", headers=[(b"content-length", b"9" * 5000)]))
    assert sent[0]["status"] == 413 and calls == [] and seen == []


def test_malformed_multipart_closes_files_and_reports_400(spools):
    app, seen = make_app()
    raw = PART_START + b"x\r\n--BOUND\r\nBroken header\r\n\r\n"
    sent, _ = asyncio.run(asgi_call(app, [raw], headers=MULTIPART_HEADERS))
    assert sent[0]["status"] == 400 and seen == []
    assert spools and all(file.closed for file in spools)


def test_websocket_and_lifespan_pass_through():
    observed = []

    async def inner(scope, receive, send):
        observed.append(scope["type"])

    middleware = BodySizeLimitMiddleware(inner, 1)
    for kind in ("websocket", "lifespan"):
        asyncio.run(middleware({"type": kind}, None, None))
    assert observed == ["websocket", "lifespan"]
