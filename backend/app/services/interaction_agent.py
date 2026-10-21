"""Bounded plan/act/observe loop over the existing tool executor."""
from __future__ import annotations

import copy
from typing import Any, Dict
from uuid import uuid4
from .interaction_run import InteractionRun, ModelBudgetExceeded, RunStopped

TOOL_LABELS = {
 "switch_view_mode": "切换视图", "switch_basemap": "切换底图", "open_panel": "打开面板",
 "toggle_layer": "调整图层显隐", "set_layer_opacity": "调整透明度", "focus_layer": "定位图层",
 "set_view": "调整视角", "run_workflow": "空间分析", "build_workflow": "空间分析",
 "draft_teaching": "生成教学草稿", "run_visual_query": "指标查询", "query_features": "属性查询",
 "generate_image": "生成图片", "enter_lesson_stage": "切换教学环节",
}
_SYNC_TOOLS = {"set_view", "switch_basemap", "toggle_layer", "style_layer", "reorder_layer", "focus_layer", "set_layer_opacity", "draw_annotation", "apply_template", "toggle_teaching_map", "enter_lesson_stage", "run_visual_query", "build_workflow", "run_workflow"}


def brief(value: Any, depth: int = 0) -> Any:
    if depth > 12:
        return "[omitted]"
    if isinstance(value, dict):
        return {str(key): brief(item, depth + 1) for key, item in list(value.items())[:35]
                if key not in {"data", "geometry", "coordinates", "geojson", "path", "export_path", "screen_snapshot", "prompt_parts", "image_data_url"}}
    if isinstance(value, list):
        return [brief(item, depth + 1) for item in value[:10]]
    return value[:2000] if isinstance(value, str) else value


def remembered_executions(project: Any, context: Dict[str, Any], map_context: Dict[str, Any]) -> list:
    remembered = (context.get("pinned_state") or {}).get("interaction_executions") or []
    scope = map_context.get("teaching_context") or {}
    scope = {key: str(scope.get(key) or "") for key in ("lesson_id", "session_id")}
    revisions = {layer.layer_id: layer.data_rev for layer in project.layers}
    return [item for item in remembered if item.get("scope") == scope and item.get("status") == "success"
            and all(revisions.get(key) == rev for key, rev in item.get("layer_revisions", {}).items())][-8:]


def run_goal(engine: Any, *, project: Any, conversation: Any, message: str,
             map_context: Dict[str, Any], context: Dict[str, Any], plan: Dict[str, Any],
             assessment: Dict[str, Any], route: Dict[str, Any], prompt_parts: Dict[str, Any],
             run_context: Any, control: InteractionRun, job_id: str, input_mode: str,
             stage_callback: Any, actor_role: str) -> Dict[str, Any]:
    executed, descriptors, issues = [], [], []
    control.observations = copy.deepcopy(map_context.get("interaction_memory") or [])
    outcome = "completed"
    answer = ""
    initial = True
    try:
        while True:
            control.check()
            actions = list(plan.get("actions") or [])
            if not initial:
                assessment = engine.tool_executor.assess("webgis", actions,
                    pinned_state=context.get("pinned_state"), assistant_mode="interaction",
                    project_state={"project_id": project.project_id}, map_context=map_context,
                    run_context=run_context, allow_image_generation=False)
            initial = False
            descriptors.extend(assessment.get("actions_planned") or [])
            requested = plan.get("request_capabilities") or []
            should_continue = bool(plan.get("continue_after_observation") or requested or plan.get("retryable_plan_error"))
            if assessment.get("requires_confirmation") and assessment.get("risk_level") != "blocked":
                # Freeze only the still-unexecuted suffix. Previously completed
                # results remain visible separately and are never replayed.
                engine.memory.update_task_memory(conversation, {"last_intent": "interaction"}, map_context,
                    pinned_state_updates={"interaction_executions": [item for item in control.observations if item.get("status") == "success"][-8:]})
                confirmation = engine._request_tool_confirmation(project=project, conversation=conversation,
                    message=message, normalized_mode="interaction", effective_target="webgis", map_context=map_context,
                    plan=plan, actions=actions, assessment=assessment, route=route, prompt_parts=prompt_parts,
                    context=context, run_context=run_context, job_id=job_id, stage_callback=stage_callback)
                confirmation["completed_actions"] = executed
                if executed:
                    confirmation["assistant_message"] = "已完成前面的操作。" + confirmation["assistant_message"]
                control.emit("waiting_user", "等待确认")
                return confirmation
            if assessment.get("risk_level") == "blocked":
                error = next((item.get("validation_error") for item in assessment["actions_planned"] if item.get("validation_error")), "操作未通过权限校验。")
                control.observations.append({"observation_id": "obs_" + uuid4().hex, "status": "error", "error": error})
                issues.append(error)
                # Permissions and action/loop guards cannot be repaired by changing wording.
                if not any(item.get("validation_error") for item in assessment["actions_planned"]):
                    outcome = "blocked"
                    break
                if any(item.get("name") == "agent_harness" for item in assessment["actions_planned"]):
                    outcome = "blocked"
                    break
                should_continue = control.route == "agent"
            elif actions:
                if all(action["tool_name"] == "run_workflow" for action in actions) and not should_continue:
                    control.route = "workflow"
                batch_success = True
                for action in actions:
                    control.check()
                    tool = action["tool_name"]
                    label = TOOL_LABELS.get(tool, "执行操作")
                    control.emit("tool_running", ("正在执行 · " if control.route == "direct" else "智能体调用工具中 · ") + label, tool=label)
                    stage_callback("execution", "running", control.activity["label"], "")
                    try:
                        entries = engine.tool_executor.execute(project.project_id, "webgis", [action], map_context,
                            pinned_state=context.get("pinned_state"), assistant_mode="interaction",
                            run_context=run_context, allow_image_generation=False)
                        entry = entries[0]
                        result = entry["result"]
                        # Preserve the committed backend outcome even if a stop
                        # arrives while the UI is still acknowledging it.
                        executed.append(entry)
                        ui = list(result.get("ui_actions") or [])
                        if tool in _SYNC_TOOLS and result.get("status", "success") == "success":
                            current_project = engine.store.get_project(project.project_id) or project
                            ui.append({"type": "sync_project", "project_updated_at": current_project.updated_at})
                        if ui and control.observe_ui:
                            try:
                                receipts = control.observe_ui(ui)
                            except RunStopped:
                                result["status"] = "unconfirmed"
                                result["assistant_message"] = "已保留操作结果，界面状态尚未确认。"
                                raise
                            result["ui_observations"] = receipts
                            if any(item.get("status") != "applied" for item in receipts):
                                result["status"] = "unconfirmed"
                                result["assistant_message"] = "操作已下发，界面尚未确认生效。"
                        success = result.get("status", "success") == "success" and not result.get("error")
                        current_project = engine.store.get_project(project.project_id) or project
                        binding = {layer.layer_id: layer.data_rev for layer in current_project.layers}
                        observation = {"observation_id": "obs_" + uuid4().hex, "status": "success" if success else result.get("status", "error"),
                                       "job_id": job_id, "action": brief(action), "result": brief(result),
                                       "scope": {key: str((map_context.get("teaching_context") or {}).get(key) or "") for key in ("lesson_id", "session_id")},
                                       "layer_revisions": binding}
                        entry["observation_id"] = observation["observation_id"]
                        control.observations.append(observation)
                        if not success:
                            batch_success = False
                            issues.append(str(result.get("assistant_message") or "操作未完成。"))
                            if result.get("status") == "unconfirmed":
                                outcome = "partial"
                                should_continue = False
                                break
                            should_continue = control.route == "agent"
                            break
                    except RunStopped:
                        raise
                    except Exception as exc:
                        batch_success = False
                        error = str(exc)
                        control.observations.append({"observation_id": "obs_" + uuid4().hex, "status": "error", "action": brief(action), "error": error})
                        issues.append(error)
                        should_continue = control.route == "agent"
                        break
                if batch_success:
                    issues.clear()
                stage_callback("execution", "success" if not issues else "error", "操作结果已返回", "")
            elif not should_continue:
                answer = str(plan.get("assistant_message") or "请补充目标或选择数据。")
                if not plan.get("goal_completed") or issues or not executed:
                    outcome = "partial" if executed else "needs_clarification"
                break
            if not should_continue:
                if issues:
                    outcome = "partial" if executed else "blocked"
                break
            control.emit("verifying", "正在核对结果")
            map_context = {**map_context, "agent_observations": brief(control.observations[-10:]),
                           "requested_capabilities": requested}
            project = engine.store.get_project(project.project_id) or project
            plan = engine.tool_planner.llm_planner.plan_interaction_step(message, project, map_context, input_mode)
            if plan.get("llm_fallback_reason") and not plan.get("retryable_plan_error"):
                issues.append(str(plan["assistant_message"]))
                answer = "剩余任务尚未完成：" + str(plan["assistant_message"])
                outcome = "partial" if executed else "needs_clarification"
                break
    except ModelBudgetExceeded as exc:
        outcome, answer = "budget_exhausted", str(exc)
    except RunStopped as exc:
        outcome, answer = "cancelled" if control.cancelled() else "partial", str(exc)
    # Executor observations, not a speculative plan sentence, determine completion.
    messages = [str(entry["result"].get("assistant_message") or "") for entry in executed]
    if outcome != "completed" and not answer and issues and issues[-1] not in messages:
        answer = issues[-1]
    if not messages and not answer:
        answer = issues[-1] if issues else "没有执行操作，请补充目标或数据。"
    if executed and outcome == "completed":
        # A corrected error may have been followed by an actual successful result.
        answer = ""
    parts = list(dict.fromkeys(text for text in messages + ([answer] if answer else []) if text))
    assistant_message = "\n".join(parts)
    remembered = [item for item in control.observations if item.get("status") == "success"][-8:]
    engine.memory.append(conversation.conversation_id, "assistant", assistant_message, "interaction",
                         metadata={"intent": "interaction", "planner": plan.get("planner"), "outcome": outcome})
    engine.memory.update_task_memory(conversation, {"last_intent": "interaction"}, map_context,
        pinned_state_updates={"last_route": route, "interaction_executions": remembered,
                              "active_plan_fingerprint": "", "last_pending_confirmation": {},
                              "last_execution": {"target": "webgis", "actions": [entry["action"] for entry in executed], "intent": "interaction"}})
    control.emit("finished", "操作完成" if outcome == "completed" else "结果已返回", outcome=outcome)
    return {"intent": "interaction", "assistant_message": assistant_message, "knowledge": None, "citations": [],
            "actions_planned": descriptors, "actions_executed": executed, "requires_confirmation": False,
            "confirmation_id": "", "planner": plan.get("planner", "interaction_agent"), "retrieval_trace": [],
            "conversation_id": conversation.conversation_id, "prompt_parts": prompt_parts,
            "permission_context": assessment.get("permission_context", {}), "outcome": outcome,
            "observations": brief(control.observations[-8:]), "route": control.route}
