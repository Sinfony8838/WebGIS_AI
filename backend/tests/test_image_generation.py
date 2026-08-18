from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.config import AppConfig
from backend.app.runtime import TRANSPARENT_PNG, WebGISRuntime
from backend.app.services.minimax_image_client import MiniMaxImageClient
from backend.app.store import RuntimeStore


class _Response:
    def __init__(self, payload: dict):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


class MiniMaxImageClientTest(unittest.TestCase):
    def test_regular_api_key_configures_pay_as_you_go_image_generation(self) -> None:
        config = AppConfig(minimax_api_key="regular-balance-key")

        status = config.image_generation_status()

        self.assertTrue(status["configured"])
        self.assertEqual(status["billing"], "pay_as_you_go_api")
        self.assertEqual(status["model"], "image-01")
        self.assertNotIn("regular-balance-key", json.dumps(status))

    def test_client_posts_base64_request_to_direct_image_endpoint(self) -> None:
        config = AppConfig(
            minimax_api_key="regular-balance-key",
            minimax_image_base_url="https://api.minimaxi.com",
            minimax_image_model="image-01",
        )
        client = MiniMaxImageClient(config)
        captured: dict = {}

        def urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _Response(
                {
                    "id": "request_1",
                    "data": {"image_base64": [base64.b64encode(TRANSPARENT_PNG).decode("ascii")]},
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                }
            )

        with patch("urllib.request.urlopen", side_effect=urlopen):
            result = client.generate("高中地理水循环示意图", aspect_ratio="4:3")

        self.assertEqual(captured["url"], "https://api.minimaxi.com/v1/image_generation")
        self.assertEqual(captured["payload"]["model"], "image-01")
        self.assertEqual(captured["payload"]["response_format"], "base64")
        self.assertEqual(captured["payload"]["n"], 1)
        self.assertTrue(captured["payload"]["aigc_watermark"])
        self.assertEqual(result["raw_bytes"], TRANSPARENT_PNG)
        self.assertEqual(result["mime_type"], "image/png")

    def test_client_rejects_unsupported_model_and_ratio(self) -> None:
        client = MiniMaxImageClient(AppConfig(minimax_api_key="key"))
        with self.assertRaisesRegex(ValueError, "image-01"):
            client.generate("地貌图", model="MiniMax-M2.7-highspeed")
        with self.assertRaisesRegex(ValueError, "比例"):
            client.generate("地貌图", aspect_ratio="5:4")


class ImageGenerationRuntimeTest(unittest.TestCase):
    def build_runtime(self) -> tuple[WebGISRuntime, str]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir, minimax_api_key="regular-balance-key")
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.ensure_dirs()
        runtime = WebGISRuntime(config=config, store=RuntimeStore(config.state_file))
        project_id = runtime.create_project()["project_id"]
        return runtime, project_id

    def test_generated_image_is_persisted_and_can_be_attached(self) -> None:
        runtime, project_id = self.build_runtime()
        runtime.image_generation_service.generate = lambda *args, **kwargs: {
            "raw_bytes": TRANSPARENT_PNG,
            "mime_type": "image/png",
            "suffix": ".png",
            "model": "image-01",
            "aspect_ratio": "16:9",
            "request_id": "request_1",
        }

        result = runtime.generate_image_asset(project_id, "水循环过程示意图")

        artifact = result["artifact"]
        self.assertEqual(artifact["artifact_type"], "generated_image")
        self.assertTrue(artifact["metadata"]["ai_generated"])
        self.assertEqual(artifact["metadata"]["source"], "minimax_image_generation")
        self.assertTrue(Path(artifact["path"]).is_file())
        self.assertIn(artifact["artifact_id"], {item["artifact_id"] for item in runtime.list_outputs(project_id)["items"]})
        resolved = runtime.resolve_image_attachments(project_id, [{"artifact_id": artifact["artifact_id"]}])
        self.assertEqual(resolved[0]["path"], str(Path(artifact["path"]).resolve()))

    def test_generation_failure_does_not_register_artifact(self) -> None:
        runtime, project_id = self.build_runtime()

        def fail(*_args, **_kwargs):
            raise RuntimeError("upstream unavailable")

        runtime.image_generation_service.generate = fail
        with self.assertRaisesRegex(RuntimeError, "upstream unavailable"):
            runtime.generate_image_asset(project_id, "地形剖面图")
        self.assertFalse(any(item["artifact_type"] == "generated_image" for item in runtime.list_outputs(project_id)["items"]))

    def test_assistant_generation_intent_requires_confirmation(self) -> None:
        runtime, project_id = self.build_runtime()
        project = runtime.store.get_project(project_id)
        self.assertIsNotNone(project)

        plan = runtime.assistant_service.plan_actions(
            "请生成一张16:9的高中地理水循环示意图",
            project,
        )
        assessment = runtime.session_engine.tool_executor.assess(
            "webgis",
            plan["actions"],
            assistant_mode="teaching_action",
            project_state={"project_id": project_id},
        )

        self.assertEqual(plan["actions"][0]["tool_name"], "generate_image")
        self.assertEqual(plan["actions"][0]["tool_params"]["aspect_ratio"], "16:9")
        self.assertEqual(assessment["risk_level"], "high")
        self.assertTrue(assessment["requires_confirmation"])

    def test_image_analysis_does_not_trigger_generation(self) -> None:
        runtime, project_id = self.build_runtime()
        project = runtime.store.get_project(project_id)
        self.assertIsNotNone(project)

        plan = runtime.assistant_service.plan_actions("请分析这张地形图", project)

        self.assertFalse(any(action["tool_name"] == "generate_image" for action in plan["actions"]))


if __name__ == "__main__":
    unittest.main()
