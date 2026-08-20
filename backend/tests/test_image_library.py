from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.runtime import TRANSPARENT_PNG, WebGISRuntime
from backend.app.services.session_engine import KnowledgeEngine
from backend.app.store import RuntimeStore


class ImageLibraryRuntimeTest(unittest.TestCase):
    def build_runtime(self) -> tuple[WebGISRuntime, str]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.assistant_v2_enabled = True
        config.ensure_dirs()
        runtime = WebGISRuntime(config=config, store=RuntimeStore(config.state_file))
        project = runtime.create_project()
        return runtime, project["project_id"]

    def wait_for_job(self, runtime: WebGISRuntime, job_id: str) -> dict:
        for _ in range(200):
            job = runtime.get_job(job_id)
            if job["status"] in {"completed", "failed"}:
                return job
            time.sleep(0.02)
        self.fail("assistant job did not finish")

    def test_upload_persists_project_image_artifact(self) -> None:
        runtime, project_id = self.build_runtime()

        result = runtime.upload_image_asset(project_id, "terrain.png", TRANSPARENT_PNG, "地貌图")

        artifact = result["artifact"]
        self.assertEqual(artifact["artifact_type"], "uploaded_image")
        self.assertEqual(artifact["project_id"], project_id)
        self.assertEqual(artifact["metadata"]["mime_type"], "image/png")
        self.assertTrue(Path(artifact["path"]).is_file())
        self.assertIn(artifact["artifact_id"], {item["artifact_id"] for item in runtime.list_outputs(project_id)["items"]})

    def test_upload_rejects_invalid_and_oversized_images(self) -> None:
        runtime, project_id = self.build_runtime()

        with self.assertRaisesRegex(ValueError, "仅支持"):
            runtime.upload_image_asset(project_id, "notes.png", b"not an image")
        with self.assertRaisesRegex(ValueError, "20MB"):
            runtime.upload_image_asset(project_id, "huge.png", b"\x89PNG\r\n\x1a\n" + b"0" * (20 * 1024 * 1024))

    def test_attachment_must_belong_to_same_project(self) -> None:
        runtime, project_id = self.build_runtime()
        other_project = runtime.create_project()["project_id"]
        artifact = runtime.upload_image_asset(other_project, "other.png", TRANSPARENT_PNG)["artifact"]

        with self.assertRaisesRegex(ValueError, "其他项目"):
            runtime.resolve_image_attachments(project_id, [{"artifact_id": artifact["artifact_id"]}])

    def test_attachment_rejects_tampered_non_image_file(self) -> None:
        runtime, project_id = self.build_runtime()
        artifact = runtime.upload_image_asset(project_id, "terrain.png", TRANSPARENT_PNG)["artifact"]
        Path(artifact["path"]).write_bytes(b"not an image")

        with self.assertRaisesRegex(ValueError, "内容与格式"):
            runtime.resolve_image_attachments(project_id, [{"artifact_id": artifact["artifact_id"]}])

    def test_assistant_sends_real_image_path_and_question_to_vision(self) -> None:
        runtime, project_id = self.build_runtime()
        artifact = runtime.upload_image_asset(project_id, "rainfall.png", TRANSPARENT_PNG, "降水分布图")["artifact"]
        calls: list[dict] = []

        def understand_image(**kwargs):
            calls.append(kwargs)
            return {
                "used_vision": True,
                "summary": "图中降水量总体由东南沿海向西北内陆递减。",
                "provider": "test_vision",
                "snapshot_path": kwargs["image_path"],
            }

        runtime.vision_service.understand_image = understand_image
        runtime.session_engine.knowledge.minimax_client = None
        response = runtime.submit_assistant_message(
            project_id,
            "这张图反映了什么空间规律？",
            assistant_mode="knowledge",
            image_attachments=[{"artifact_id": artifact["artifact_id"]}],
        )
        job = self.wait_for_job(runtime, response["job_id"])

        self.assertEqual(job["status"], "completed")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["question"], "这张图反映了什么空间规律？")
        self.assertEqual(Path(calls[0]["image_path"]), Path(artifact["path"]))
        self.assertIn("东南沿海", job["result"]["assistant_message"])
        self.assertNotIn("缩放级别", job["result"]["assistant_message"])
        self.assertNotIn("经纬度", job["result"]["assistant_message"])

    def test_image_failure_does_not_fall_back_to_map_coordinates(self) -> None:
        runtime, project_id = self.build_runtime()
        artifact = runtime.upload_image_asset(project_id, "terrain.png", TRANSPARENT_PNG)["artifact"]
        runtime.vision_service.understand_image = lambda **kwargs: {
            "used_vision": False,
            "reason": "图片识别服务暂时不可用，请稍后重试。",
        }
        response = runtime.submit_assistant_message(
            project_id,
            "识别这张图",
            map_context={"center": [104, 35], "zoom": 8, "extent": [100, 30, 108, 40]},
            image_attachments=[{"artifact_id": artifact["artifact_id"]}],
        )
        job = self.wait_for_job(runtime, response["job_id"])

        message = job["result"]["assistant_message"]
        self.assertIn("图片识别服务暂时不可用", message)
        self.assertNotIn("104", message)
        self.assertNotIn("缩放", message)

    def test_image_follow_up_reuses_only_the_recent_conversation_image(self) -> None:
        runtime, project_id = self.build_runtime()
        artifact = runtime.upload_image_asset(project_id, "river.png", TRANSPARENT_PNG)["artifact"]
        calls: list[str] = []

        def understand_image(**kwargs):
            calls.append(kwargs["question"])
            return {"used_vision": True, "summary": "图中是一条曲流河道。", "provider": "test"}

        runtime.vision_service.understand_image = understand_image
        runtime.session_engine.knowledge.minimax_client = None
        first = runtime.submit_assistant_message(
            project_id,
            "识别河流形态",
            image_attachments=[{"artifact_id": artifact["artifact_id"]}],
        )
        first_job = self.wait_for_job(runtime, first["job_id"])
        conversation_id = first_job["result"]["conversation_id"]

        follow_up = runtime.submit_assistant_message(
            project_id,
            "刚才的图片为什么会形成这种弯曲？",
            conversation_id=conversation_id,
        )
        self.wait_for_job(runtime, follow_up["job_id"])
        ordinary = runtime.submit_assistant_message(
            project_id,
            "什么是季风？",
            conversation_id=conversation_id,
        )
        self.wait_for_job(runtime, ordinary["job_id"])

        self.assertEqual(calls, ["识别河流形态", "刚才的图片为什么会形成这种弯曲？"])

    def test_legacy_snapshot_failure_is_not_replaced_with_map_coordinates(self) -> None:
        runtime, project_id = self.build_runtime()
        runtime.vision_service.understand_map = lambda **kwargs: {
            "used_vision": False,
            "reason": "图片识别服务暂时不可用。",
        }
        response = runtime.submit_assistant_message(
            project_id,
            "请读图分析",
            map_context={"center": [104, 35], "zoom": 8},
            screen_snapshot={"image_data_url": "data:image/png;base64,AAAA"},
        )
        job = self.wait_for_job(runtime, response["job_id"])

        message = job["result"]["assistant_message"]
        self.assertIn("图片识别服务暂时不可用", message)
        self.assertNotIn("104", message)
        self.assertNotIn("缩放", message)


class RetrievalPolicyTest(unittest.TestCase):
    def build_engine(self) -> KnowledgeEngine:
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.minimax_api_key = ""

        class ResourceSearch:
            def search(self, query: str, scope: str, limit: int):
                return {
                    "items": [
                        {
                            "title": "国家统计局",
                            "url": "https://www.stats.gov.cn/",
                            "summary": "权威统计数据",
                            "confidence": 0.95,
                        }
                    ]
                }

        return KnowledgeEngine(config, minimax_client=None, resource_search=ResourceSearch())

    def test_retrieval_modes_are_intent_driven(self) -> None:
        engine = self.build_engine()

        plain_image = engine.answer("这是什么地貌？", {"image_attachment": {"artifact_id": "a"}, "vision_summary": "山地河谷"})
        local = engine.answer("请根据知识库解释胡焕庸线")
        web = engine.answer("请核实今年最新人口数据及来源")
        both = engine.answer("结合教材和最新在线来源解释胡焕庸线")

        self.assertEqual(plain_image["retrieval_mode"], "none")
        self.assertEqual(plain_image["citations"], [])
        self.assertEqual(local["retrieval_mode"], "local")
        self.assertTrue(local["citations"])
        self.assertEqual(web["retrieval_mode"], "web")
        self.assertEqual(both["retrieval_mode"], "local_web")

    def test_in_class_skips_implicit_web_but_honors_explicit_verification(self) -> None:
        engine = self.build_engine()
        context = {"teaching_context": {"phase": "in_class"}}

        ordinary = engine.answer("解释季风形成原因", context)
        implicit_current = engine.answer("目前的季风监测情况如何", context)
        explicit = engine.answer("联网核实今年最新季风监测来源", context)

        self.assertEqual(ordinary["retrieval_mode"], "none")
        self.assertEqual(ordinary["citations"], [])
        self.assertEqual(implicit_current["retrieval_mode"], "none")
        self.assertEqual(implicit_current["citations"], [])
        self.assertEqual(explicit["retrieval_mode"], "web")
        self.assertTrue(explicit["citations"])

    def test_image_answer_prompt_forbids_facts_outside_vision_summary(self) -> None:
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.llm_provider = "minimax"
        config.minimax_api_key = "test-key"

        class CapturingClient:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def chat_completion(self, messages, temperature=0.3, **kwargs):
                self.calls.append({"messages": messages, "temperature": temperature})
                return "图中西北部地势较高，中南部湖泊密集；具体湖泊名称无法从现有图面确认。"

        client = CapturingClient()
        engine = KnowledgeEngine(config, minimax_client=client, resource_search=None)
        result = engine.answer(
            "请分析地势和主要水域。",
            {
                "image_attachment": {"artifact_id": "artifact_test"},
                "vision_summary": "西北部颜色较深，表示地势较高；中南部可见密集湖泊，未确认具体湖名。",
                "center": [104, 35],
                "zoom": 6,
            },
        )

        system_prompt = client.calls[0]["messages"][0]["content"]
        user_prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("唯一事实来源", system_prompt)
        self.assertIn("用户问题只决定从中挑选哪些内容", system_prompt)
        self.assertIn("必须在视觉读图结果中明确出现", system_prompt)
        self.assertIn("中文专名时必须逐字复制", system_prompt)
        self.assertIn("答案中不要出现经纬度", system_prompt)
        self.assertIn("图片事实仅限以下内容", user_prompt)
        self.assertEqual(client.calls[0]["temperature"], 0.0)
        self.assertEqual(result["map_grounding"], "")
