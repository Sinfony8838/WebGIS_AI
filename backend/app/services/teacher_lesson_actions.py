"""Execute only actions declared in the classroom's frozen lesson snapshot."""
from __future__ import annotations
from copy import deepcopy
import json
from typing import Any, Dict


def materials(config, rows):
    path = config.uploads_dir / "teacher_population_revised/manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [{**item, "url": f"/files/uploads/teacher_population_revised/{item['filename']}"}
            for item in manifest.get("items", []) if item.get("row") in rows]


def apply_action(runtime, session_id: str, stage_id: str, action_id: str, opacities=None) -> Dict[str, Any]:
    classroom = runtime.classroom
    session = classroom._require_session(session_id)
    if session.status != "running" or session.current_stage_id != stage_id:
        raise ValueError("课堂环节已变化，请返回当前环节操作。")
    lesson = classroom._lesson_for_session(session)
    stage = lesson.find_stage(stage_id) if lesson else None
    action = next((a for a in stage.get("actions", []) if a["action_id"] == action_id), None) if stage else None
    if not action:
        raise KeyError("当前课时没有此教学操作。")
    action = deepcopy(action)
    result = {"status": "success", "action": action, "materials": materials(runtime.config, action.get("resource_rows", []))}
    if action.get("scene"):
        if opacities:
            for item in action["scene"].get("teaching_maps", []):
                if item["id"] in opacities:
                    value = float(opacities[item["id"]])
                    if not 0 <= value <= 1:
                        raise ValueError("透明度应介于0和1。")
                    item["opacity"] = value
        result["scene"] = classroom.lesson_service.apply_stage_scene_data(session.project_id, {**stage, "scene": action["scene"]}, lesson_id=lesson.lesson_id)
    if action["type"] == "workflow":
        if action_id != "finland_reproduce":
            raise ValueError("此教学工作流尚未配置。")
        result["workflow"] = runtime.submit_workflow(session.project_id, "芬兰2015年人口密度分级设色", template_id="population_choropleth",
            parameters={"dataset": "builtin:one_map/population/finland_density_2015.geojson", "population_field": "population", "area_field": "area", "density_field": "density", "classes": 5})
        if result["workflow"].get("status") == "error":
            raise ValueError(result["workflow"].get("error", {}).get("user_friendly") or "芬兰工作流暂不可用。")
    if action["type"] == "summary":
        shown = []
        for event in session.events:
            if event.get("type") == "lesson_action":
                p = event.get("payload") or {}
                if p.get("note"):
                    shown.append(f"{p.get('label','')}: {p['note']}")
        result["prompt"] = action.get("prompt", "") + "\n本课堂实际点击的材料（只说明展示记录，不代表学生已掌握）：\n" + "\n".join(shown[-30:])
    runtime.store.append_session_event(session_id, "lesson_action", stage_id=stage_id,
        payload={"action_id": action_id, "label": action["label"], "note": action.get("note", ""), "opacities": opacities or {}, "workflow_id": result.get("workflow", {}).get("workflow_id", "")})
    result["session"] = classroom.get_class_session(session_id)["session"]
    return result


def resource_check(runtime, lesson_id: str):
    lesson = runtime.classroom.lesson_service.get_lesson(lesson_id)
    ids = set()
    for stage in lesson.stages:
        for scene in [stage.get("scene", {}), *(a.get("scene", {}) for a in stage.get("actions", []))]:
            ids.update(m["id"] for m in scene.get("teaching_maps", []))
    maps = []
    for id in sorted(ids):
        info = runtime.teaching_map_service.get_map(id)
        maps.append({"id": id, "name": info.get("name", id) if info else id, "available": bool(info and info.get("available")),
                     "registration": (info or {}).get("registration", "textbook_image")})
    figures = materials(runtime.config, list(range(24)))
    manifest_path = runtime.config.uploads_dir / "teacher_population_revised/manifest.json"
    try:
        source_matches = json.loads(manifest_path.read_text(encoding="utf-8")).get("source_sha256") == lesson.metadata.get("source_document", {}).get("sha256")
    except (OSError, ValueError):
        source_matches = False
    package = runtime.config.data_dir / "population/worldpop_global_2015"
    return {"status": "success", "maps": maps,
            "figures_available": source_matches and len(figures) == 42 and all((runtime.config.uploads_dir / "teacher_population_revised" / f["filename"]).is_file() for f in figures),
            "population_available": (package / "package.json").is_file() and (package / "counts.sqlite").is_file() and (package / "counts.sqlite").stat().st_size > 0}


def preview_action(runtime, rehearsal_id, stage_id, action_id):
    rehearsal = runtime.classroom.lesson_rehearsal.get(rehearsal_id)
    if rehearsal.status != "active":
        raise ValueError("模拟测试已结束。")
    stage = next((s for s in rehearsal.working_copy.get("stages", []) if s["stage_id"] == stage_id), None)
    action = next((a for a in stage.get("actions", []) if a["action_id"] == action_id), None) if stage else None
    if not action:
        raise KeyError("模拟测试中没有此教学操作。")
    result = {"status": "success", "action": action, "materials": materials(runtime.config, action.get("resource_rows", []))}
    if action.get("scene"):
        result["scene"] = runtime.classroom.lesson_service.apply_stage_scene_data(rehearsal.project_id, {**stage, "scene": action["scene"]}, lesson_id=rehearsal.lesson_id)
    return result


def apply_workflow_result(runtime, session_id, stage_id, workflow_id):
    with runtime.store.batch():
        session = runtime.classroom._require_session(session_id)
        if session.status != "running" or session.current_stage_id != stage_id or stage_id != "finland_application":
            raise ValueError("课堂环节已变化，不加载上一个环节的分析结果。")
        if not any(e.get("type") == "lesson_action" and e.get("stage_id") == stage_id
                   and (e.get("payload") or {}).get("action_id") == "finland_reproduce"
                   and (e.get("payload") or {}).get("workflow_id") == workflow_id for e in session.events):
            raise ValueError("该分析任务不是本课堂已发起的芬兰操作。")
        workflow = runtime.store.get_workflow(workflow_id)
        if not workflow or workflow.project_id != session.project_id or workflow.status != "success":
            raise ValueError("人口密度分析尚未成功完成。")
        output = next((a for a in runtime.store.list_outputs(project_id=session.project_id)
                       if a.get("metadata", {}).get("workflow_id") == workflow_id and a.get("metadata", {}).get("kind") == "geojson"), None)
        if not output:
            raise ValueError("分析未生成可加载的矢量结果。")
        result = runtime.load_output_as_layer(session.project_id, output["artifact_id"])
        layer = result["item"]
        for previous in runtime.store.get_project(session.project_id).layers:
            if previous.layer_id != layer["layer_id"] and previous.metadata.get("teacher_topic") == "finland_population_2015":
                runtime.store.patch_layer(session.project_id, previous.layer_id, {"visible": False})
        runtime.store.patch_layer(session.project_id, layer["layer_id"], {"visible": True, "z_index": 30, "opacity": 1, "metadata": {
            **layer["metadata"], "teacher_topic": "finland_population_2015", "source_year": "2015",
            "data_source": "WorldPop R2025A UA v1；0.1°聚合教学网格"}})
        runtime.store.patch_layer(session.project_id, "one_map_finland_population_density_2015", {"visible": False})
        runtime.store.append_session_event(session_id, "lesson_action_result", stage_id=stage_id, payload={"workflow_id":workflow_id,"artifact_id":output["artifact_id"]})
        return {"status":"success", "artifact_id":output["artifact_id"]}
