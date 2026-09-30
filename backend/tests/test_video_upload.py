from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import main as app_main
from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.auth import AuthService


def _mp4_bytes(size: int = 2048) -> bytes:
    # 最小 MP4 形态：ftyp box 头 + 填充
    head = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    return head + b"\x00" * max(0, size - len(head))


def _webm_bytes(size: int = 512) -> bytes:
    head = b"\x1a\x45\xdf\xa3\x01\x00\x00\x00\x00\x00\x00\x1fEBML"
    return head + b"\x00" * max(0, size - len(head))


class VideoUploadTest(unittest.TestCase):
    """项目级视频资源上传：类型/大小校验、项目归属与可访问性。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_config = app_main.config
        self.previous_runtime = app_main.runtime
        self.previous_auth_service = app_main.auth_service
        config = AppConfig(root_dir=Path(self.temp_dir.name), auth_mode="users")
        config.minimax_api_key = ""
        config.minimax_token_plan_key = ""
        config.ensure_dirs()
        app_main.config = config
        app_main.runtime = WebGISRuntime(config=config)
        app_main.auth_service = AuthService(config.auth_db_path)
        self.client = TestClient(app_main.app)
        bootstrap = self.client.post(
            "/auth/bootstrap",
            json={"email": "admin@school.edu.cn", "nickname": "系统管理员", "password": "Strong-Admin-2026!"},
        )
        self.headers = {"X-WebGIS-CSRF": bootstrap.json()["csrf_token"]}
        self.project_id = self.client.post(
            "/projects", json={"name": "视频资源"}, headers=self.headers
        ).json()["project_id"]

    def tearDown(self) -> None:
        self.client.close()
        app_main.config = self.previous_config
        app_main.runtime = self.previous_runtime
        app_main.auth_service = self.previous_auth_service
        self.temp_dir.cleanup()

    def _upload(self, filename: str, payload: bytes, mime: str = "video/mp4"):
        return self.client.post(
            "/media/video-upload",
            data={"project_id": self.project_id},
            files={"file": (filename, BytesIO(payload), mime)},
            headers=self.headers,
        )

    def test_upload_mp4_and_webm_roundtrip(self) -> None:
        for filename, payload, mime in (
            ("讲解.mp4", _mp4_bytes(), "video/mp4"),
            ("实验.webm", _webm_bytes(), "video/webm"),
        ):
            with self.subTest(filename=filename):
                response = self._upload(filename, payload, mime)
                self.assertEqual(response.status_code, 200, response.text)
                artifact = response.json()["artifact"]
                self.assertEqual(artifact["artifact_type"], "uploaded_video")
                url = artifact["metadata"]["public_url"]
                fetched = self.client.get(url, headers=self.headers)
                self.assertEqual(fetched.status_code, 200)
                self.assertEqual(fetched.content, payload)

    def test_rejects_non_video_and_mismatched_suffix(self) -> None:
        bad_magic = self._upload("fake.mp4", b"this is not a video")
        self.assertEqual(bad_magic.status_code, 400)
        self.assertIn("MP4", bad_magic.json()["detail"])
        mismatch = self._upload("讲解.webm", _mp4_bytes())
        self.assertEqual(mismatch.status_code, 400)
        self.assertIn("不一致", mismatch.json()["detail"])

    def test_rejects_oversized(self) -> None:
        app_main.config.max_video_upload_bytes = 1024
        response = self._upload("big.mp4", _mp4_bytes(size=4096))
        self.assertEqual(response.status_code, 413)

    def test_video_appears_in_teacher_outputs(self) -> None:
        self._upload("讲解.mp4", _mp4_bytes())
        outputs = self.client.get("/outputs", headers=self.headers).json()
        types = {item["artifact_type"] for item in outputs.get("items", [])}
        self.assertIn("uploaded_video", types)


if __name__ == "__main__":
    unittest.main()
