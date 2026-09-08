"""数据库优化轮后端测试。

覆盖：工作流产物同步注册进 RuntimeStore（幂等）、teacher_facing 白名单、
outputs→图层端点方法、DELETE artifact、资源检索保存为 KB 素材、题库搜索
跨页修复。全部离线。
"""
import tempfile
import unittest
from pathlib import Path
from typing import Tuple

from backend.app.config import AppConfig
from backend.app.models import WorkflowRecord
from backend.app.runtime import WebGISRuntime
from backend.app.services.workflow_executor import WorkflowExecutor
from backend.app.store import RuntimeStore


class DatabasePanelBackendTest(unittest.TestCase):
    def build_runtime(self) -> Tuple[WebGISRuntime, RuntimeStore, str]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.workflows_dir = config.data_dir / "workflows"
        config.state_file = config.state_dir / "runtime.json"
        # KB manifest 是全局单文件：必须重定向到临时目录，避免污染真实
        # 内置知识库（也避免跨测试累积「检索收藏」材料）。
        config.knowledge_dir = config.data_dir / "knowledge"
        config.ensure_dirs()
        runtime = WebGISRuntime(config=config, store=RuntimeStore(config.state_file))
        runtime.session_engine.knowledge.minimax_client = None
        runtime.session_engine.tool_planner.llm_planner.minimax_client = None
        project = runtime.create_project()
        return runtime, runtime.store, project["project_id"]

    # ------------------------------------------------------------------
    # Workflow artifacts mirrored into RuntimeStore
    # ------------------------------------------------------------------

    def _make_workflow_with_artifact(self, runtime: WebGISRuntime, project_id: str, workflow_id: str) -> WorkflowRecord:
        record = WorkflowRecord.create(
            project_id=project_id,
            user_message="分析",
            template_id="population_choropleth",
        )
        record.workflow_id = workflow_id
        record.status = "success"
        record.artifacts = [
            {
                "kind": "geojson",
                "title": "结果矢量",
                "relative_path": "outputs/result.geojson",
                "public_url": f"/workflow-files/{workflow_id}/outputs/result.geojson",
                "metadata": {},
            }
        ]
        # 在磁盘上放置真实产物文件，load_output_as_layer 需要读取它。
        output_dir = runtime.config.workflows_dir / workflow_id / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "result.geojson").write_text(
            '{"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"name": "a"}, "geometry": {"type": "Point", "coordinates": [104.0, 35.0]}}]}',
            encoding="utf-8",
        )
        return record

    def test_workflow_artifacts_mirror_into_outputs(self) -> None:
        runtime, store, project_id = self.build_runtime()
        executor = WorkflowExecutor(runtime.config, store)
        record = self._make_workflow_with_artifact(runtime, project_id, "wf_db_1")
        executor._sync_artifacts_to_database(record)

        items = runtime.list_outputs(project_id=project_id)["items"]
        mirrored = [item for item in items if item["artifact_type"] == "workflow_output"]
        self.assertEqual(len(mirrored), 1)
        self.assertEqual(mirrored[0]["metadata"]["workflow_id"], "wf_db_1")
        self.assertEqual(mirrored[0]["metadata"]["kind"], "geojson")

    def test_workflow_artifact_mirror_is_idempotent(self) -> None:
        runtime, store, project_id = self.build_runtime()
        executor = WorkflowExecutor(runtime.config, store)
        record = self._make_workflow_with_artifact(runtime, project_id, "wf_db_2")
        executor._sync_artifacts_to_database(record)
        executor._sync_artifacts_to_database(record)

        items = runtime.list_outputs(project_id=project_id)["items"]
        mirrored = [item for item in items if item["artifact_type"] == "workflow_output"]
        self.assertEqual(len(mirrored), 1, "重复同步不应产生重复记录")

    def test_teacher_facing_whitelist_includes_reports_and_papers(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        for artifact_type in (
            "workflow_output",
            "class_report",
            "practice_paper_student",
            "lesson_plan_docx",
        ):
            runtime.store.register_artifact(project_id, "job_x", artifact_type, "t", "/tmp/x")
        kinds = {item["artifact_type"] for item in runtime.list_outputs(project_id=project_id)["items"]}
        self.assertTrue({"workflow_output", "class_report", "practice_paper_student", "lesson_plan_docx"} <= kinds)

    # ------------------------------------------------------------------
    # outputs → layer / delete
    # ------------------------------------------------------------------

    def test_load_output_as_layer_creates_layer(self) -> None:
        runtime, store, project_id = self.build_runtime()
        executor = WorkflowExecutor(runtime.config, store)
        record = self._make_workflow_with_artifact(runtime, project_id, "wf_load")
        executor._sync_artifacts_to_database(record)
        artifact_id = next(
            item["artifact_id"]
            for item in runtime.list_outputs(project_id=project_id)["items"]
            if item["artifact_type"] == "workflow_output"
        )

        result = runtime.load_output_as_layer(project_id, artifact_id)
        layer = result["item"]
        self.assertEqual(layer["source"], "output_artifact")
        self.assertEqual(layer["geometry_type"], "Point")
        project = runtime._require_project(project_id)
        self.assertTrue(any(item.layer_id == layer["layer_id"] for item in project.layers))

    def test_load_output_as_layer_rejects_non_geojson(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        runtime.store.register_artifact(project_id, "job_n", "assistant_note", "笔记", "/tmp/note.md")
        artifact_id = runtime.list_outputs(project_id=project_id)["items"][0]["artifact_id"]
        with self.assertRaises(ValueError):
            runtime.load_output_as_layer(project_id, artifact_id)

    def test_delete_output_removes_record_only(self) -> None:
        runtime, store, project_id = self.build_runtime()
        runtime.store.register_artifact(project_id, "job_d", "assistant_note", "待删", "/tmp/note.md")
        artifact_id = runtime.list_outputs(project_id=project_id)["items"][0]["artifact_id"]

        runtime.delete_output(project_id, artifact_id)
        self.assertIsNone(store.get_artifact(artifact_id))
        self.assertEqual(runtime.list_outputs(project_id=project_id)["items"], [])

    # ------------------------------------------------------------------
    # resources/save
    # ------------------------------------------------------------------

    def test_save_resource_result_creates_collection_and_material(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        result = runtime.save_resource_result(
            project_id,
            {
                "title": "联合国人口报告",
                "url": "https://www.un.org/population",
                "summary": "权威人口数据",
                "source": "authoritative_web",
                "type": "report",
            },
            owner_user_id="local_admin",
        )
        self.assertEqual(result["status"], "success")
        manifest = runtime.knowledge_base_service.get_manifest(owner_user_id="local_admin", include_all=True)
        collection = next(item for item in manifest["items"] if item["title"] == "检索收藏")
        materials = collection.get("materials") or []
        self.assertTrue(any(material.get("url") == "https://www.un.org/population" for material in materials))

        # 再次保存：复用同一条目，不新建。
        runtime.save_resource_result(
            project_id,
            {"title": "第二条", "url": "https://www.un.org/second"},
            owner_user_id="local_admin",
        )
        manifest = runtime.knowledge_base_service.get_manifest(owner_user_id="local_admin", include_all=True)
        collections = [item for item in manifest["items"] if item["title"] == "检索收藏"]
        self.assertEqual(len(collections), 1)
        self.assertEqual(len(collections[0].get("materials") or []), 2)

    def test_save_resource_result_requires_url(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        with self.assertRaises(ValueError):
            runtime.save_resource_result(project_id, {"title": "无链接"}, owner_user_id="local_admin")

    def test_saved_resources_are_isolated_by_owner_and_keep_summary(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        first = runtime.save_resource_result(project_id, {"url": "https://example.org/a", "summary": "摘要"}, owner_user_id="teacher-a")
        second = runtime.save_resource_result(project_id, {"url": "https://example.org/a"}, owner_user_id="teacher-b")
        self.assertNotEqual(first["kb_item_id"], second["kb_item_id"])
        items = runtime.knowledge_base_service.get_manifest(owner_user_id="teacher-a")["items"]
        owned = [item for item in items if item.get("owner_user_id")]
        self.assertEqual([item["id"] for item in owned], [first["kb_item_id"]])
        self.assertEqual(owned[0]["materials"][0]["description"], "摘要")


if __name__ == "__main__":
    unittest.main()
