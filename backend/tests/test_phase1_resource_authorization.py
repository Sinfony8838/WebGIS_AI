"""Phase-1 audit task T2: resource authorization boundary matrix.

Covers the /files serving decision (normalized shared-dir membership,
project-derived ownership, explicit grants), scoped response grants,
server-side workflow project context, and the worker-side dataset boundary
(project-pinned uploads, workspace-confined absolute paths, traversal).
Every file involved is a tiny synthetic fixture inside the pytest sandbox.
"""
from __future__ import annotations

import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services import resource_access
from backend.app.services.auth import AuthService
from backend.app.services.workflow_executor import _resolve_dataset_for_preflight
from backend.app.services.pyqgis_worker.handlers import _common as worker_common
from backend.app.services.pyqgis_worker.workspace import Workspace
from backend.app.services.pyqgis_worker.errors import WorkflowExecutionError

GEOJSON = (
    '{"type":"FeatureCollection","features":[{"type":"Feature",'
    '"properties":{"name":"a"},"geometry":{"type":"Point","coordinates":[116.4,39.9]}}]}'
)

TEACHER_A = "teacher.a@school.edu.cn"
TEACHER_B = "teacher.b@school.edu.cn"


class ResourceAuthorizationMatrixTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sandbox = Path(self.temp_dir.name)
        self.previous = (app_main.config, app_main.runtime, app_main.auth_service)
        config = AppConfig(root_dir=self.sandbox, auth_mode="users")
        config.ensure_dirs()
        app_main.config = config
        app_main.runtime = WebGISRuntime(config=config)
        app_main.auth_service = AuthService(config.auth_db_path)
        self.client = TestClient(app_main.app)
        self._admin, self.admin_csrf = self._bootstrap_admin()
        self.teacher_a_client, self.a_csrf, self.a_user = self._create_teacher(TEACHER_A, "教师A")
        self.teacher_b_client, self.b_csrf, self.b_user = self._create_teacher(TEACHER_B, "教师B")
        self.project_a = self._create_project(self.teacher_a_client, self.a_csrf, "A的项目")
        self.project_b = self._create_project(self.teacher_b_client, self.b_csrf, "B的项目")

    def tearDown(self) -> None:
        self.client.close()
        self.teacher_a_client.close()
        self.teacher_b_client.close()
        app_main.config, app_main.runtime, app_main.auth_service = self.previous
        self.temp_dir.cleanup()

    # ------------------------------------------------------------- helpers

    def _bootstrap_admin(self) -> tuple[dict, str]:
        response = self.client.post(
            "/auth/bootstrap",
            json={"email": "admin@school.edu.cn", "nickname": "系统管理员", "password": "Strong-Admin-2026!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["user"], response.json()["csrf_token"]

    def _create_teacher(self, email: str, nickname: str):
        created = self.client.post(
            "/admin/users",
            json={"email": email, "nickname": nickname, "role": "teacher"},
            headers={"X-WebGIS-CSRF": self.admin_csrf},
        )
        self.assertEqual(created.status_code, 200, created.text)
        temp_password = created.json()["temporary_password"]
        client = TestClient(app_main.app)
        login = client.post("/auth/login", json={"email": email, "password": temp_password})
        self.assertEqual(login.status_code, 200, login.text)
        csrf = login.json()["csrf_token"]
        changed = client.post(
            "/auth/change-password",
            json={"current_password": temp_password, "new_password": "Teacher-New-2026!"},
            headers={"X-WebGIS-CSRF": csrf},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        me = client.get("/auth/me")
        self.assertEqual(me.status_code, 200)
        return client, me.json().get("csrf_token", csrf), me.json()["user"]

    def _create_project(self, client: TestClient, csrf: str, name: str) -> str:
        response = client.post("/projects", json={"name": name}, headers={"X-WebGIS-CSRF": csrf})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["project_id"]

    def _upload_dataset(self, project_id: str, filename: str = "points.geojson"):
        return self.teacher_a_client.post(
            "/datasets/upload",
            data={"project_id": project_id, "dataset_name": "测试数据"},
            files={"file": (filename, GEOJSON.encode("utf-8"), "application/geo+json")},
            headers={"X-WebGIS-CSRF": self.a_csrf},
        )

    def _fabricated_request(self, user_id: str, role: str = "teacher") -> Request:
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        request.state.auth = types.SimpleNamespace(user={"user_id": user_id, "role": role})
        return request

    # ------------------------------------------------- normalization units

    def test_file_reference_normalization_rejects_hostile_forms(self) -> None:
        for reference in (
            "/files/state/runtime.json",
            "/files/uploads/../state/runtime.json",
            "/files/uploads/x\\..\\..\\state\\runtime.json",
            "/files/C:/Windows/win.ini",
            "/files//etc/passwd",
            "/files/",
            "uploads/../../outside.txt",
            "",
            None,
        ):
            with self.subTest(reference=reference):
                if reference is None:
                    self.assertIsNone(resource_access.normalize_file_reference(reference))
                else:
                    self.assertIsNone(
                        resource_access.normalize_file_reference(reference),
                        "hostile reference must normalize to None",
                    )
        # Percent-encoded traversal is decoded by the framework before the
        # handler sees it (where ".." is rejected); the raw literal segment is
        # inert, but must never normalize into an escape either.
        encoded = resource_access.normalize_file_reference("/files/uploads/%2e%2e/state/runtime.json")
        if encoded is not None:
            self.assertNotIn("..", encoded.parts)
            self.assertEqual(encoded.parts[0], "uploads")

    def test_resolve_public_reference_follows_symlinks_before_containment(self) -> None:
        config = app_main.config
        outside = self.sandbox / "outsider" / "secret.txt"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("x", encoding="utf-8")
        link = Path(config.uploads_dir) / "link.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted on this account")
        self.assertIsNone(resource_access.resolve_public_reference(config, "/files/uploads/link.txt"))

    # ------------------------------------------------------- /files matrix

    def test_dataset_file_download_owner_yes_others_no_admin_yes(self) -> None:
        upload = self._upload_dataset(self.project_a)
        self.assertEqual(upload.status_code, 200, upload.text)
        payload = upload.json()
        artifact = payload.get("artifact") or {}
        url = (artifact.get("metadata") or {}).get("public_url") or payload.get("url")
        self.assertTrue(url, "upload response must expose the stored file URL")
        self.assertIn("/files/uploads/", url)
        owner = self.teacher_a_client.get(url)
        self.assertEqual(owner.status_code, 200)
        other = self.teacher_b_client.get(url)
        self.assertEqual(other.status_code, 404)
        admin = self.client.get(url)
        self.assertEqual(admin.status_code, 200)

    def test_dataset_upload_grants_only_own_project_files(self) -> None:
        upload = self._upload_dataset(self.project_a)
        self.assertEqual(upload.status_code, 200, upload.text)
        stored = list((Path(app_main.config.uploads_dir) / self.project_a).glob("*.geojson"))
        self.assertTrue(stored)
        granted = app_main.auth_service.can_access_file(self.a_user["user_id"], stored[0])
        self.assertTrue(granted)
        foreign = Path(app_main.config.uploads_dir) / self.project_b / "other.geojson"
        foreign.parent.mkdir(parents=True, exist_ok=True)
        foreign.write_text(GEOJSON, encoding="utf-8")
        self.assertFalse(app_main.auth_service.can_access_file(self.a_user["user_id"], foreign))

    def test_shared_teaching_map_visible_to_both_teachers(self) -> None:
        shared_dir = Path(app_main.config.uploads_dir) / "teaching_maps"
        shared_dir.mkdir(parents=True, exist_ok=True)
        asset = shared_dir / "hu_line.png"
        asset.write_bytes(b"PNG-fixture")
        for client, csrf, label in (
            (self.teacher_a_client, self.a_csrf, "A"),
            (self.teacher_b_client, self.b_csrf, "B"),
        ):
            response = client.get("/files/uploads/teaching_maps/hu_line.png")
            self.assertEqual(response.status_code, 200, f"teacher {label}: {response.text}")
        # Normalized-equivalent form of the same shared asset stays visible.
        dotted = self.teacher_a_client.get("/files/uploads/./teaching_maps/hu_line.png")
        self.assertEqual(dotted.status_code, 200)
        # Traversal out of the shared dir must not ride on the prefix.
        escape = self.teacher_a_client.get("/files/uploads/teaching_maps/../hu_line.png")
        self.assertEqual(escape.status_code, 404)

    def test_private_file_of_other_project_404_even_in_shared_named_dir(self) -> None:
        # A file that merely lives under a path containing the shared name in
        # a private subtree must not become globally visible.
        tricky_root = Path(app_main.config.outputs_dir) / self.project_a / "teaching_maps"
        tricky_root.mkdir(parents=True, exist_ok=True)
        asset = tricky_root / "private.png"
        asset.write_bytes(b"PNG")
        response = self.teacher_b_client.get(f"/files/outputs/{self.project_a}/teaching_maps/private.png")
        self.assertEqual(response.status_code, 404)

    def test_unknown_and_deleted_files_return_404(self) -> None:
        self.assertEqual(self.teacher_a_client.get("/files/uploads/nothing.png").status_code, 404)
        volatile = Path(app_main.config.uploads_dir) / "teaching_maps" / "gone.png"
        volatile.parent.mkdir(parents=True, exist_ok=True)
        volatile.write_bytes(b"x")
        self.assertEqual(self.teacher_a_client.get("/files/uploads/teaching_maps/gone.png").status_code, 200)
        volatile.unlink()
        self.assertEqual(self.teacher_a_client.get("/files/uploads/teaching_maps/gone.png").status_code, 404)

    def test_cross_project_output_file_404_for_other_teacher(self) -> None:
        output = Path(app_main.config.outputs_dir) / self.project_a / "map.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"PNG")
        self.assertEqual(
            self.teacher_a_client.get(f"/files/outputs/{self.project_a}/map.png").status_code, 404
        )  # not registered, not granted: even the owner needs a grant path
        self.assertEqual(
            self.teacher_b_client.get(f"/files/outputs/{self.project_a}/map.png").status_code, 404
        )
        self.assertEqual(self.client.get(f"/files/outputs/{self.project_a}/map.png").status_code, 200)

    # ------------------------------------------------- scoped grant checks

    def test_grant_response_files_only_grants_allowed_roots(self) -> None:
        config = app_main.config
        legit_dir = Path(config.uploads_dir) / "kb_materials"
        legit_dir.mkdir(parents=True, exist_ok=True)
        legit = legit_dir / "doc.png"
        legit.write_bytes(b"x")
        foreign = Path(config.uploads_dir) / self.project_b / "steal.png"
        foreign.parent.mkdir(parents=True, exist_ok=True)
        foreign.write_bytes(b"x")
        payload = {
            "ok": f"/files/uploads/kb_materials/doc.png",
            "nested": {"list": [f"/files/uploads/{self.project_b}/steal.png"]},
            "shape_only": "text mentioning /files/uploads/{self.project_b}/steal.png but not a URL",
        }
        request = self._fabricated_request(self.a_user["user_id"])
        app_main._grant_response_files(
            request, payload, allowed_roots=(Path(config.uploads_dir) / "kb_materials",)
        )
        self.assertTrue(app_main.auth_service.can_access_file(self.a_user["user_id"], legit))
        self.assertFalse(app_main.auth_service.can_access_file(self.a_user["user_id"], foreign))

    def test_grant_response_files_without_roots_grants_nothing(self) -> None:
        target = Path(app_main.config.uploads_dir) / "kb_materials" / "x.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
        request = self._fabricated_request(self.a_user["user_id"])
        app_main._grant_response_files(request, {"url": "/files/uploads/kb_materials/x.png"}, allowed_roots=())
        self.assertFalse(app_main.auth_service.can_access_file(self.a_user["user_id"], target))

    def test_question_bank_list_grants_only_this_projects_banks(self) -> None:
        images_a = Path(app_main.config.uploads_dir) / "question_banks" / "bank_a" / "images"
        images_a.mkdir(parents=True, exist_ok=True)
        (images_a / "q.png").write_bytes(b"PNG")
        response = self.teacher_a_client.get(
            f"/question-banks?project_id={self.project_a}", headers={"X-WebGIS-CSRF": self.a_csrf}
        )
        self.assertEqual(response.status_code, 200, response.text)
        bank_b_image = Path(app_main.config.uploads_dir) / "question_banks" / "bank_b" / "images" / "q.png"
        bank_b_image.parent.mkdir(parents=True, exist_ok=True)
        bank_b_image.write_bytes(b"PNG")
        self.assertFalse(app_main.auth_service.can_access_file(self.a_user["user_id"], bank_b_image))

    # --------------------------------------- workflow project context (T2.3)

    def test_workflow_submit_rejects_mismatched_nested_project_id(self) -> None:
        response = self.teacher_a_client.post(
            "/workflow/submit",
            json={
                "project_id": self.project_a,
                "message": "做一幅人口分布专题图",
                "parameters": {"project_id": self.project_b},
            },
            headers={"X-WebGIS-CSRF": self.a_csrf},
        )
        self.assertEqual(response.status_code, 400, response.text)

    def test_workflow_submit_forces_server_project_context(self) -> None:
        response = self.teacher_a_client.post(
            "/workflow/submit",
            json={
                "project_id": self.project_a,
                "message": "做一幅人口分布专题图",
                "parameters": {"project_id": self.project_a},
            },
            headers={"X-WebGIS-CSRF": self.a_csrf},
        )
        self.assertEqual(response.status_code, 200, response.text)
        workflow_id = response.json()["workflow_id"]
        record = app_main.runtime.store.get_workflow(workflow_id)
        self.assertIsNotNone(record)
        for step in record.workflow_json.get("steps", []):
            params = step.get("params") or step.get("parameters") or {}
            if "project_id" in params:
                self.assertEqual(params["project_id"], self.project_a)

    # ------------------------------------------- worker dataset boundary

    def _worker_sandbox(self):
        config = app_main.config
        workflows_root = Path(config.workflows_dir)
        workspace = Workspace("wf_phase1", workflows_root / "wf_phase1")
        for project in (self.project_a, self.project_b):
            project_dir = Path(config.uploads_dir) / project
            project_dir.mkdir(parents=True, exist_ok=True)
            (project_dir / "data.geojson").write_text(GEOJSON, encoding="utf-8")
        return workspace

    def test_worker_upload_reference_pinned_to_owning_project(self) -> None:
        workspace = self._worker_sandbox()
        resolved = worker_common.resolve_dataset_path(
            workspace, f"upload:{self.project_a}/data.geojson", project_id=self.project_a
        )
        self.assertTrue(resolved.is_file())
        with self.assertRaises(WorkflowExecutionError) as ctx:
            worker_common.resolve_dataset_path(
                workspace, f"upload:{self.project_b}/data.geojson", project_id=self.project_a
            )
        self.assertEqual(ctx.exception.code, "DATASET_NOT_ALLOWED")

    def test_worker_upload_reference_rejects_traversal_between_projects(self) -> None:
        workspace = self._worker_sandbox()
        for source in (
            f"upload:{self.project_a}/../{self.project_b}/data.geojson",
            "upload:../outside/data.geojson",
            f"upload:{self.project_a}/..\\{self.project_b}\\data.geojson",
        ):
            with self.subTest(source=source):
                with self.assertRaises(WorkflowExecutionError) as ctx:
                    worker_common.resolve_dataset_path(workspace, source, project_id=self.project_a)
                self.assertEqual(ctx.exception.code, "DATASET_NOT_ALLOWED")

    def test_worker_absolute_path_confined_to_workflow_workspace(self) -> None:
        workspace = self._worker_sandbox()
        inside = workspace.outputs_dir / "previous_step.geojson"
        inside.write_text(GEOJSON, encoding="utf-8")
        resolved = worker_common.resolve_dataset_path(workspace, str(inside), project_id=self.project_a)
        self.assertEqual(resolved.resolve(), inside.resolve())
        outside = Path(app_main.config.uploads_dir) / self.project_b / "data.geojson"
        with self.assertRaises(WorkflowExecutionError) as ctx:
            worker_common.resolve_dataset_path(workspace, str(outside), project_id=self.project_a)
        self.assertEqual(ctx.exception.code, "DATASET_NOT_ALLOWED")
        # A readable system file is equally refused.
        windows_host_file = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "win.ini"
        if windows_host_file.exists():
            with self.assertRaises(WorkflowExecutionError) as ctx:
                worker_common.resolve_dataset_path(workspace, str(windows_host_file), project_id=self.project_a)
            self.assertEqual(ctx.exception.code, "DATASET_NOT_ALLOWED")

    def test_worker_bare_name_resolves_only_in_own_project(self) -> None:
        workspace = self._worker_sandbox()
        resolved = worker_common.resolve_dataset_path(workspace, "data.geojson", project_id=self.project_a)
        self.assertEqual(resolved.resolve(), (Path(app_main.config.uploads_dir) / self.project_a / "data.geojson").resolve())

    def test_preflight_mirror_matches_worker_boundary(self) -> None:
        config = app_main.config
        uploads_a = Path(config.uploads_dir) / self.project_a
        uploads_a.mkdir(parents=True, exist_ok=True)
        (uploads_a / "data.geojson").write_text(GEOJSON, encoding="utf-8")
        self.assertIsNotNone(
            _resolve_dataset_for_preflight(config, f"upload:{self.project_a}/data.geojson", self.project_a)
        )
        self.assertIsNone(
            _resolve_dataset_for_preflight(config, f"upload:{self.project_b}/data.geojson", self.project_a)
        )
        self.assertIsNone(
            _resolve_dataset_for_preflight(
                config, f"upload:{self.project_a}/../{self.project_b}/data.geojson", self.project_a
            )
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
