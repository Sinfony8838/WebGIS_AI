"""Exercise receive/parser/archive budgets through the real application routes."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.request_limits import BodySizeLimitMiddleware, BudgetedUploadRoute


@pytest.fixture
def api(tmp_path, monkeypatch):
    config = AppConfig(root_dir=tmp_path, auth_mode="disabled")
    config.minimax_api_key = ""
    config.minimax_token_plan_key = ""
    config.max_json_body_bytes = 256
    config.ensure_dirs()
    runtime = WebGISRuntime(config=config)
    project = runtime.store.create_project(name="Budget checks", owner_user_id="local_admin")
    monkeypatch.setattr(app_main, "config", config)
    monkeypatch.setattr(app_main, "runtime", runtime)
    monkeypatch.setattr(app_main, "auth_service", None)
    previous_stack = app_main.app.middleware_stack
    for middleware in app_main.app.user_middleware:
        if middleware.cls is BodySizeLimitMiddleware:
            monkeypatch.setitem(middleware.kwargs, "config", config)
    app_main.app.middleware_stack = None
    client = TestClient(app_main.app)
    try:
        yield client, config, runtime, project.project_id
    finally:
        client.close()
        app_main.app.middleware_stack = previous_stack


def files_on_disk(config):
    return {path.relative_to(config.data_root): path.read_bytes()
            for root in (config.uploads_dir, config.outputs_dir)
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("media", ["application/json", "application/problem+json"])
def test_actual_json_route_rejects_lying_content_length_without_creating_project(api, media):
    client, _, runtime, _ = api
    before = set(runtime.store.projects)
    response = client.post("/projects", content=b'{"name":"' + b"x" * 512 + b'"}',
                           headers={"content-type": media, "content-length": "1"})
    assert response.status_code == 413
    assert set(runtime.store.projects) == before
    assert client.get("/health").status_code == 200


def test_upload_routes_are_budgeted_and_keep_larger_file_capacity(api):
    client, config, _, project_id = api
    for route in app_main.app.routes:
        if getattr(route, "path", "") == "/datasets/upload":
            assert isinstance(route, BudgetedUploadRoute)
    raw = b"name,lat,lon\n" + b"point,31,121\n" * 30
    assert len(raw) > config.max_json_body_bytes
    response = client.post("/datasets/upload", data={"project_id": project_id},
                           files={"file": ("points.csv", raw)})
    assert response.status_code == 200, response.text


def test_actual_file_cap_rejects_before_dataset_import(api, monkeypatch):
    client, config, runtime, project_id = api
    config.max_dataset_upload_bytes = 64
    before = files_on_disk(config)
    called = []
    monkeypatch.setattr(runtime, "upload_dataset", lambda **kwargs: called.append(kwargs))
    response = client.post("/datasets/upload", data={"project_id": project_id},
                           files={"file": ("points.csv", b"x" * 65)})
    assert response.status_code == 413
    assert called == []
    assert files_on_disk(config) == before


@pytest.mark.parametrize("extra_field", [False, True])
def test_actual_bank_part_counts_do_not_admit_jobs(api, extra_field):
    client, config, runtime, project_id = api
    before_jobs = set(runtime.store.jobs)
    before_files = files_on_disk(config)
    data = {"project_id": project_id}
    if extra_field:
        data["unrecognized"] = "not admitted"
    response = client.post("/question-banks/import", data=data,
                           files=[("files", (f"bank{i}.docx", b"x"))
                                  for i in range(1 if extra_field else 5)])
    assert response.status_code == 413, response.text
    assert set(runtime.store.jobs) == before_jobs
    assert files_on_disk(config) == before_files


def oversized_archive():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for index in range(2001):
            archive.writestr(f"entry{index}", b"")
    return stream.getvalue()


@pytest.mark.parametrize("kind", ["bank", "presentation", "lesson", "timeline", "dataset"])
def test_archive_budget_returns_413_without_persisting_or_admitting_work(api, kind):
    client, config, runtime, project_id = api
    paths = {
        "bank": ("/question-banks/import", "files", "bank.docx", {"project_id": project_id}),
        "presentation": (f"/projects/{project_id}/presentations", "file", "deck.pptx",
                         {"request_id": "budget_test_123"}),
        "lesson": ("/lesson-design/import-docx", "file", "lesson.docx", {"project_id": project_id}),
        "timeline": (f"/projects/{project_id}/timeline/generate", "file", "lesson.docx", {}),
        "dataset": ("/datasets/upload", "file", "shape.zip", {"project_id": project_id}),
    }
    path, field, filename, data = paths[kind]
    before_jobs = set(runtime.store.jobs)
    before_designs = set(runtime.store.lesson_designs)
    before_files = files_on_disk(config)
    response = client.post(path, data=data, files={field: (filename, oversized_archive())})
    assert response.status_code == 413, response.text
    assert set(runtime.store.jobs) == before_jobs
    assert set(runtime.store.lesson_designs) == before_designs
    assert files_on_disk(config) == before_files
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("kind", ["bank", "presentation"])
def test_malformed_office_upload_is_rejected_before_job_or_source_file(api, kind):
    client, config, runtime, project_id = api
    before_jobs = set(runtime.store.jobs)
    before_files = files_on_disk(config)
    if kind == "bank":
        path, data, field = "/question-banks/import", {"project_id": project_id}, "files"
    else:
        path, data, field = f"/projects/{project_id}/presentations", {"request_id": "bad_test_123"}, "file"
    response = client.post(path, data=data, files={field: ("bad.docx" if kind == "bank" else "bad.pptx", b"bad")})
    assert response.status_code == 400, response.text
    assert set(runtime.store.jobs) == before_jobs
    assert files_on_disk(config) == before_files
