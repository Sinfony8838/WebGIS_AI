"""Business checks recovered from historical trajectory drafts.

Use real isolated state and generated artifacts. Exceptions, empty output and
merely repeated error messages never count as a successful export.
"""
from copy import deepcopy
from pathlib import Path
import time

from docx import Document
import pytest

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore


LESSON_ID = "lesson_builtin_population_shanghai_world"


@pytest.fixture
def classroom(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBGIS_AI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("WEBGIS_AI_AUTH_DB", str(tmp_path / "data/auth/auth.db"))
    config = AppConfig(root_dir=Path(__file__).resolve().parents[2])
    config.minimax_api_key = ""
    config.minimax_token_plan_key = ""
    config.ensure_dirs()
    store = RuntimeStore(config.state_file)
    runtime = WebGISRuntime(config=config, store=store)
    project_id = runtime.create_project()["project_id"]
    assert config.data_dir.resolve().is_relative_to(tmp_path.resolve())
    return runtime, store, project_id


def test_next_stage_commands_persist_the_shanghai_sequence(classroom):
    runtime, store, project_id = classroom
    session = runtime.classroom.create_class_session(LESSON_ID, project_id)["session"]
    session_id = session["session_id"]
    context = {"teaching_context": {"session_id": session_id, "lesson_id": LESSON_ID, "phase": "in_class"}}
    runtime.classroom.enter_session_stage(session_id, "shanghai_intro")
    for expected in ("concept", "shanghai_inquiry"):
        plan = runtime.assistant_service.plan_interaction_actions("下一环节", store.get_project(project_id), context)
        assert [action["tool_name"] for action in plan["actions"]] == ["enter_lesson_stage"]
        runtime._execute_assistant_action(project_id, plan["actions"][0], context)
        restored = RuntimeStore(store.state_file).get_class_session(session_id)
        assert restored.current_stage_id == expected
        assert any(event["type"] == "stage_enter" and event["stage_id"] == expected for event in restored.events)


def test_hiding_top_thematic_layer_preserves_lower_layer_and_order(classroom):
    runtime, store, project_id = classroom
    runtime.add_catalog_dataset_layer(project_id, "china_provinces")
    runtime.add_catalog_dataset_layer(project_id, "shanghai_age_60_plus_2020")
    layers = {layer.layer_id: layer for layer in store.get_project(project_id).layers}
    lower = layers["one_map_china_provinces"]
    upper = layers["one_map_shanghai_age_60_plus_2020"]
    original_order = (lower.z_index, upper.z_index)
    assert original_order[0] < original_order[1]
    plan = runtime.assistant_service.plan_interaction_actions(
        f"隐藏{upper.name}", store.get_project(project_id), {})
    assert [action["tool_name"] for action in plan["actions"]] == ["toggle_layer"]
    runtime._execute_assistant_action(project_id, plan["actions"][0], {})
    restored = RuntimeStore(store.state_file).get_project(project_id)
    layers = {layer.layer_id: layer for layer in restored.layers}
    assert layers[lower.layer_id].visible is True
    assert layers[upper.layer_id].visible is False
    assert (layers[lower.layer_id].z_index, layers[upper.layer_id].z_index) == original_order


def test_regenerated_reports_preserve_statistics_and_classroom_evidence(classroom):
    runtime, store, project_id = classroom
    session_id = runtime.classroom.create_class_session(LESSON_ID, project_id)["session"]["session_id"]
    runtime.classroom.enter_session_stage(session_id, "china_inquiry")
    runtime.classroom.log_session_event(session_id, "note", "china_inquiry", {
        "kind": "population_inquiry_record", "source": "preset_example", "text": "合成演练观点"})
    runtime.classroom.end_class_session(session_id)
    before = deepcopy(store.get_class_session(session_id).to_dict())
    reports = []
    for _ in range(2):
        job_id = runtime.classroom.submit_session_report(session_id)["job_id"]
        deadline = time.monotonic() + 15
        while store.get_job(job_id).status not in {"completed", "failed"} and time.monotonic() < deadline:
            time.sleep(0.01)
        job = store.get_job(job_id)
        assert job.status == "completed", job.error
        reports.append(job.result["statistics"])
        assert job.result["diagnosis"]["generator"] == "rules"
    assert reports[0] == reports[1]
    assert reports[0]["response_data_collected"] is False
    assert reports[0]["participant_count"] == 0
    assert all(question.get("correct_rate") is None for question in reports[0]["questions"])
    assert RuntimeStore(store.state_file).get_class_session(session_id).to_dict() == before


def test_repeated_practice_exports_create_real_consistent_papers(classroom):
    runtime, store, project_id = classroom
    lesson = store.get_lesson(LESSON_ID)
    lesson.plan = {"homework": {"basic": ["比较黄浦与崇明的人口密度并说明一个原因。"]}}
    session_id = runtime.classroom.create_class_session(LESSON_ID, project_id)["session"]["session_id"]
    before = deepcopy(store.get_class_session(session_id).to_dict())
    exports = [runtime.classroom.export_session_practice(session_id) for _ in range(2)]
    assert exports[0]["selected_ids"] == exports[1]["selected_ids"]
    assert exports[0]["selected_ids"]
    for kind in ("student_artifact", "teacher_artifact"):
        texts = []
        for result in exports:
            path = Path(result[kind]["path"])
            assert path.is_file() and path.stat().st_size > 0
            texts.append("\n".join(paragraph.text for paragraph in Document(path).paragraphs))
        assert "比较黄浦与崇明" in texts[0]
        assert texts[0] == texts[1]
    assert RuntimeStore(store.state_file).get_class_session(session_id).to_dict() == before


def test_empty_practice_rejection_is_not_a_successful_export(classroom):
    runtime, store, project_id = classroom
    lesson = runtime.classroom.lesson_service.create_lesson({"title": "无作业演练", "stages": []})
    lesson_id = lesson.lesson_id
    session_id = runtime.classroom.create_class_session(lesson_id, project_id)["session"]["session_id"]
    jobs_before = set(store.jobs)
    for _ in range(2):
        with pytest.raises(ValueError, match="未找到可用作业内容"):
            runtime.classroom.export_session_practice(session_id)
    assert set(store.jobs) == jobs_before
    assert not list(runtime.config.outputs_dir.rglob("*.docx"))
