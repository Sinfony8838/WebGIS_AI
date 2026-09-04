"""Guided, population-first lesson-plan co-creation service.

The service deliberately keeps the teacher-facing conversation natural while
persisting a small, validated draft after every turn. The draft is portable
JSON, so refreshing the browser never loses the current design.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..models import LessonDesignRecord, LessonRecord
from ..store import RuntimeStore
from .lessons import LessonService
from .minimax_client import MiniMaxClient
from .population_lesson_prep import ALLOWED_GLOBE_THEME_IDS


STEP_KEYS = ("requirements", "analysis", "objectives", "process", "capabilities", "rehearsal", "confirmation")
STEP_LABELS = {
    "requirements": "教学需求", "analysis": "课标与学情", "objectives": "目标与重难点",
    "process": "教学过程", "capabilities": "GIS/AI能力", "rehearsal": "预演检查", "confirmation": "确认保存",
}
SECTION_KEYS = (
    "requirements", "curriculum_interpretation", "student_analysis", "textbook_analysis",
    "objectives", "key_difficulties", "methods", "knowledge_structure", "stages",
    "capabilities", "references", "reflection",
)
STEP_SECTIONS = {
    "requirements": ("requirements",),
    "analysis": ("curriculum_interpretation", "student_analysis", "textbook_analysis"),
    "objectives": ("objectives", "key_difficulties", "methods", "knowledge_structure"),
    "process": ("stages",),
    "capabilities": ("capabilities",),
}
REQUIRED_SECTIONS = (
    "requirements", "curriculum_interpretation", "student_analysis", "textbook_analysis",
    "objectives", "key_difficulties", "stages", "capabilities",
)
SECTION_LABELS = {
    "requirements": "教学需求", "curriculum_interpretation": "课标解读", "student_analysis": "学情分析",
    "textbook_analysis": "教材分析", "objectives": "教学目标", "key_difficulties": "教学重难点",
    "methods": "教学方法", "knowledge_structure": "知识结构", "stages": "教学过程",
    "capabilities": "GIS/AI能力", "references": "参考资料", "reflection": "教学反思",
}


def default_draft() -> Dict[str, Any]:
    return {
        "title": "", "subject": "地理", "grade": "", "duration_minutes": 40, "topic": "",
        "requirements": {}, "curriculum_interpretation": "", "student_analysis": "",
        "textbook_analysis": "", "objectives": [], "key_difficulties": {"key": [], "difficult": []},
        "methods": [], "knowledge_structure": [], "stages": [], "capabilities": [],
        "references": [], "reflection": "",
    }


class LessonDesignService:
    """Create, discuss, validate and publish teacher-owned lesson drafts."""

    def __init__(
        self, config: Any, store: RuntimeStore, lesson_service: LessonService,
        minimax_client: Optional[MiniMaxClient] = None, template_service: Any = None,
        catalog_service: Any = None, knowledge_base_service: Any = None,
        resource_search_service: Any = None,
    ):
        self.config = config
        self.store = store
        self.lesson_service = lesson_service
        self.minimax_client = minimax_client
        self.template_service = template_service
        self.catalog_service = catalog_service
        self.knowledge_base_service = knowledge_base_service
        self.resource_search_service = resource_search_service

    def create_or_resume(
        self, project_id: str, owner_user_id: str, base_lesson_id: str = "",
        requirements: Optional[Dict[str, Any]] = None,
    ) -> LessonDesignRecord:
        existing = self.store.list_lesson_designs(project_id=project_id, owner_user_id=owner_user_id, active_only=True)
        for item in existing:
            if str(item.base_lesson_id or "") == str(base_lesson_id or ""):
                return item
        draft = default_draft()
        if base_lesson_id:
            lesson = self.store.get_lesson(base_lesson_id)
            if lesson is None:
                raise KeyError("Unknown base lesson")
            lesson_project_id = str((lesson.metadata or {}).get("project_id") or "")
            if lesson.source != "builtin" and lesson_project_id and lesson_project_id != project_id:
                raise ValueError("关联课时不属于当前项目")
            draft.update(copy.deepcopy(lesson.plan or {}))
            draft["title"] = draft.get("title") or lesson.title
            draft["subject"] = draft.get("subject") or lesson.subject
            draft["grade"] = draft.get("grade") or lesson.grade
            draft["objectives"] = copy.deepcopy(lesson.objectives)
            draft["stages"] = copy.deepcopy(lesson.stages)
        req = {str(k): v for k, v in (requirements or {}).items()}
        if req:
            draft["requirements"] = {**draft.get("requirements", {}), **req}
        base_draft = copy.deepcopy(draft) if base_lesson_id else {}
        design = LessonDesignRecord.create(
            project_id=project_id, owner_user_id=owner_user_id, base_lesson_id=base_lesson_id,
            requirements=req, draft=draft, base_draft=base_draft,
        )
        design.section_status = {key: ("proposed" if base_lesson_id and self._section_has_content(draft.get(key)) else "pending") for key in SECTION_KEYS}
        design.diff_summary = self._build_diff_summary(design)
        return self.store.upsert_lesson_design(design)

    def get(self, design_id: str) -> LessonDesignRecord:
        design = self.store.get_lesson_design(design_id)
        if design is None:
            raise KeyError("Unknown lesson design")
        return design

    def capability_catalog(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = [
            {"id": "map_2d", "label": "2D 地图场景", "kind": "map", "available": True},
            {"id": "globe_3d", "label": "3D 地球场景", "kind": "map", "available": True},
            {"id": "basemap_switch", "label": "底图切换", "kind": "map", "available": True},
            {"id": "population_sources", "label": "人口专题来源卡", "kind": "data", "available": True},
            {"id": "population_top20", "label": "人口指标 TOP20 查询", "kind": "analysis", "available": True},
            {"id": "annotation_measurement", "label": "地图标注与测量", "kind": "map", "available": True},
            {"id": "image_understanding", "label": "图片识别", "kind": "ai", "available": True},
            {"id": "knowledge_base", "label": "项目知识库", "kind": "knowledge", "available": bool(self.knowledge_base_service)},
            {"id": "class_records", "label": "课堂记录与报告", "kind": "classroom", "available": True},
        ]
        if self.template_service is not None:
            try:
                for item in self.template_service.list_templates().get("items", []):
                    if isinstance(item, dict) and item.get("template_id"):
                        items.append({
                            "id": str(item["template_id"]), "label": str(item.get("title") or item["template_id"]),
                            "kind": "template", "available": True,
                        })
            except Exception:
                pass
        if self.catalog_service is not None:
            try:
                for item in self.catalog_service.list_catalog().get("items", []):
                    if isinstance(item, dict) and item.get("id"):
                        items.append({
                            "id": str(item["id"]), "label": str(item.get("name") or item["id"]),
                            "kind": "dataset",
                            "available": str(item.get("status") or "available") not in {"missing", "unavailable"},
                            "source_year": str(item.get("source_year") or ""),
                        })
            except Exception:
                pass
        result, seen = [], set()
        for item in items:
            if item["id"] not in seen:
                seen.add(item["id"])
                result.append(item)
        return result

    def turn(self, design_id: str, message: str, expected_revision: Optional[int] = None, step: str = "") -> Dict[str, Any]:
        design = self.get(design_id)
        if expected_revision is not None and expected_revision != design.revision:
            raise ValueError("教案草稿已更新，请刷新后再继续。")
        message = str(message or "").strip()
        if not message:
            raise ValueError("请先告诉我你的教学想法或修改要求。")
        current_step = step if step in STEP_KEYS else design.current_step
        if any(token in message for token in ("返回上一步", "回到上一步")):
            current_index = STEP_KEYS.index(current_step) if current_step in STEP_KEYS else 0
            current_step = STEP_KEYS[max(0, current_index - 1)]
            design.current_step = current_step
        result = self._ask_minimax(design, current_step, message) or self._fallback_turn(design, current_step, message)
        if current_step == "requirements":
            result = self._normalize_requirements_result(result, message, design.draft)
        patch = result.get("section_patch") if isinstance(result, dict) else {}
        patch = patch if isinstance(patch, dict) else {}
        # 已确认章节默认是稳定约束；只有教师明确提出修改/返回时才重新打开。
        reopen = any(token in message for token in ("修改", "调整", "返回", "重做", "换一种"))
        for key in list(patch):
            if design.section_status.get(key) == "confirmed" and not reopen:
                patch.pop(key, None)
            elif design.section_status.get(key) == "confirmed" and reopen:
                design.section_status[key] = "pending"
        self._merge_patch(design.draft, patch)
        next_step = str(result.get("next_step") or self._next_step(current_step))
        if next_step not in STEP_KEYS:
            next_step = self._next_step(current_step)
        for key in patch:
            if key in SECTION_KEYS:
                design.section_status[key] = "proposed"
        if patch:
            design.current_step = current_step
            design.pending_next_step = next_step
        else:
            design.current_step = next_step
            design.pending_next_step = ""
        design.revision += 1
        design.turns.append({
            "revision": design.revision, "step": current_step, "message": message,
            "reply": str(result.get("reply") or ""), "section_patch": copy.deepcopy(patch),
        })
        retrieval_mode, retrieved_refs = self._retrieve(message, design.owner_user_id)
        design.source_refs = self._merge_refs(design.source_refs, result.get("source_refs"))
        design.source_refs = self._merge_refs(design.source_refs, retrieved_refs)
        design.draft["references"] = copy.deepcopy(design.source_refs)
        design.capability_bindings = self._validate_bindings(result.get("capability_bindings") or design.draft.get("capabilities") or [])
        design.draft["capabilities"] = copy.deepcopy(design.capability_bindings)
        design.diff_summary = self._build_diff_summary(design)
        self.store.upsert_lesson_design(design)
        rehearsal_report = self.rehearse(design_id) if current_step == "rehearsal" else None
        return {
            "status": "success", "assistant_message": str(result.get("reply") or self._natural_prompt(next_step)),
            "next_step": design.current_step, "step_label": STEP_LABELS.get(design.current_step, design.current_step),
            "draft": copy.deepcopy(design.draft), "section_status": copy.deepcopy(design.section_status),
            "source_refs": copy.deepcopy(design.source_refs), "capability_bindings": copy.deepcopy(design.capability_bindings),
            "revision": design.revision, "suggestions": [str(item) for item in result.get("suggestions") or []],
            "retrieval": {"mode": retrieval_mode, "used": bool(retrieved_refs)},
            "diff_summary": copy.deepcopy(design.diff_summary),
            "review_sections": [key for key in STEP_SECTIONS.get(current_step, ()) if design.section_status.get(key) == "proposed"],
            "rehearsal_report": rehearsal_report,
        }

    def resolve(self, design_id: str, section_id: str, decision: str = "accept", teacher_note: str = "", expected_revision: Optional[int] = None, value: Any = None) -> Dict[str, Any]:
        design = self.get(design_id)
        if expected_revision is not None and expected_revision != design.revision:
            raise ValueError("教案草稿已更新，请刷新后再操作。")
        if section_id not in SECTION_KEYS and section_id not in STEP_SECTIONS and section_id not in {"title", "grade", "duration_minutes"}:
            raise ValueError("未知教案章节")
        section_ids = STEP_SECTIONS.get(section_id, (section_id,))
        normalized_decision = str(decision).lower()
        if normalized_decision in {"edit", "direct_edit", "直接编辑"}:
            patch_value = copy.deepcopy(value)
            if section_id in STEP_SECTIONS:
                if not isinstance(patch_value, dict):
                    raise ValueError("当前步骤的直接编辑内容格式不正确")
                allowed_group = set(STEP_SECTIONS[section_id])
                for key, item in patch_value.items():
                    if key in allowed_group:
                        if key == "capabilities":
                            if not isinstance(item, list):
                                raise ValueError("系统能力配置格式不正确")
                            validated = self._validate_bindings(item)
                            requested_ids = {
                                str(binding if isinstance(binding, str) else binding.get("id") or binding.get("capability_id") or "")
                                for binding in item if isinstance(binding, (str, dict))
                            }
                            accepted_ids = {binding["id"] for binding in validated}
                            unknown = sorted(capability_id for capability_id in requested_ids - accepted_ids if capability_id)
                            if unknown:
                                raise ValueError("包含不可用系统能力：" + "、".join(unknown))
                            design.capability_bindings = validated
                            design.draft[key] = copy.deepcopy(validated)
                        else:
                            design.draft[key] = copy.deepcopy(item)
                        design.section_status[key] = "proposed"
                if not any(key in allowed_group for key in patch_value):
                    raise ValueError("没有可保存的当前步骤内容")
                design.revision += 1
                design.diff_summary = self._build_diff_summary(design)
                self.store.upsert_lesson_design(design)
                return {"status": "success", "message": "已保存当前步骤的直接编辑内容。", "design": design.to_dict()}
            if section_id == "duration_minutes":
                try:
                    patch_value = max(1, int(value))
                except (TypeError, ValueError) as exc:
                    raise ValueError("课时时长必须是正整数") from exc
            if section_id in {"title", "grade"}:
                patch_value = str(value or "").strip()
                if not patch_value:
                    raise ValueError("直接编辑内容不能为空")
            design.draft[section_id] = patch_value
            if section_id in SECTION_KEYS:
                design.section_status[section_id] = "proposed"
            design.revision += 1
            design.diff_summary = self._build_diff_summary(design)
            self.store.upsert_lesson_design(design)
            return {"status": "success", "message": "已保存直接编辑内容。", "design": design.to_dict()}
        if normalized_decision in {"accept", "accepted", "确认", "接受"}:
            accepted = []
            for key in section_ids:
                if self._section_has_content(design.draft.get(key)):
                    design.section_status[key] = "confirmed"
                    accepted.append(key)
            if not accepted:
                raise ValueError("这一部分还没有可确认的内容")
            design.current_step = design.pending_next_step or self._next_step(design.current_step)
            design.pending_next_step = ""
            design.revision += 1
            message = "已接受这一部分。"
        else:
            for key in section_ids:
                if design.section_status.get(key) == "proposed":
                    design.section_status[key] = "pending"
            if teacher_note:
                design.turns.append({"revision": design.revision, "step": design.current_step, "message": teacher_note, "reply": ""})
            message = "好的，我们保留现稿，按你的补充继续修改。"
        design.diff_summary = self._build_diff_summary(design)
        self.store.upsert_lesson_design(design)
        return {"status": "success", "message": message, "design": design.to_dict()}

    def rehearse(self, design_id: str) -> Dict[str, Any]:
        design = self.get(design_id)
        draft, errors, warnings = design.draft, [], []
        if not str(draft.get("title") or draft.get("topic") or "").strip():
            errors.append("还缺少课题名称。")
        if not str(draft.get("grade") or "").strip():
            warnings.append("尚未填写年级，课堂难度需要教师确认。")
        objectives = draft.get("objectives") or []
        if not isinstance(objectives, list) or not objectives:
            errors.append("至少需要一个可观察的教学目标。")
        stages = draft.get("stages") or []
        if not isinstance(stages, list) or not stages:
            errors.append("还没有教学过程环节。")
        total = 0
        capability_items = self.capability_catalog()
        valid_ids = {item["id"] for item in capability_items if item.get("available", True)}
        dataset_ids = {item["id"] for item in capability_items if item.get("kind") == "dataset" and item.get("available", True)}
        for index, stage in enumerate(stages, 1):
            if not isinstance(stage, dict):
                errors.append(f"第{index}个环节格式不完整。")
                continue
            try:
                minutes = int(stage.get("minutes") or 0)
            except (TypeError, ValueError):
                minutes = 0
            total += max(0, minutes)
            if not str(stage.get("title") or "").strip():
                errors.append(f"第{index}个环节缺少名称。")
            if not str(stage.get("design_intent") or stage.get("content") or "").strip():
                warnings.append(f"“{stage.get('title') or f'环节{index}'}”还可以补充设计意图。")
            questions = stage.get("questions") or []
            if not isinstance(questions, list) or not any(isinstance(item, dict) and str(item.get("text") or "").strip() for item in questions):
                errors.append(f"环节“{stage.get('title') or index}”至少需要一个明确问题。")
            for template_id in (stage.get("scene") or {}).get("templates") or []:
                if template_id not in valid_ids:
                    errors.append(f"环节“{stage.get('title') or index}”引用了不可用能力 {template_id}。")
            for dataset_id in (stage.get("scene") or {}).get("catalog_layers") or []:
                if dataset_id not in dataset_ids:
                    errors.append(f"环节“{stage.get('title') or index}”引用了不可用数据 {dataset_id}。")
            globe = (stage.get("scene") or {}).get("globe") or {}
            if isinstance(globe, dict) and globe.get("enabled"):
                unknown_themes = [theme for theme in globe.get("themes") or [] if str(theme) not in ALLOWED_GLOBE_THEME_IDS]
                if unknown_themes:
                    errors.append(f"环节“{stage.get('title') or index}”引用了不可用三维主题：{'、'.join(map(str, unknown_themes))}。")
        duration = int(draft.get("duration_minutes") or 0)
        if duration > 0 and total != duration:
            errors.append(
                f"各环节合计 {total} 分钟，与课堂时长 {duration} 分钟不一致；"
                "请先调整环节时长，再定稿。"
            )
        if not design.source_refs:
            warnings.append("目前没有引用资料；如需课标或年份核验，请在下一轮明确提出。")
        for source in design.source_refs:
            if isinstance(source, dict) and source.get("dataset_id") and not str(source.get("year") or source.get("source_year") or "").strip():
                warnings.append(f"资料“{source.get('title') or source.get('dataset_id')}”尚未标明年份。")
        return {"ready": not errors, "errors": errors, "warnings": warnings, "total_minutes": total, "duration_minutes": duration, "capabilities": self.capability_catalog()}

    def finalize(self, design_id: str, expected_revision: Optional[int] = None, apply_base: bool = False) -> Dict[str, Any]:
        design = self.get(design_id)
        if expected_revision is not None and expected_revision != design.revision:
            raise ValueError("教案草稿已更新，请刷新后再确认。")
        report = self.rehearse(design_id)
        if not report["ready"]:
            raise ValueError("教案还不能保存：" + " ".join(report["errors"]))
        unconfirmed = [key for key in REQUIRED_SECTIONS if design.section_status.get(key) != "confirmed"]
        if unconfirmed:
            labels = "、".join(SECTION_LABELS.get(key, key) for key in unconfirmed)
            raise ValueError("请先逐项确认这些章节：" + labels)
        if design.base_lesson_id and apply_base:
            base = self.store.get_lesson(design.base_lesson_id)
            if base is None or base.source == "builtin":
                raise ValueError("内置课时不能直接覆盖，请保存为新的教师草稿。")
        draft = copy.deepcopy(design.draft)
        lesson = self.lesson_service.create_lesson({
            "title": draft.get("title") or draft.get("topic") or "人口地理教案",
            "subject": draft.get("subject") or "地理", "grade": draft.get("grade") or "",
            "objectives": draft.get("objectives") or [], "stages": draft.get("stages") or [],
            "metadata": {"design_id": design.design_id, "project_id": design.project_id, "duration_minutes": draft.get("duration_minutes", 40)},
            "plan": draft,
        }, source="assistant_draft", owner_user_id=design.owner_user_id)
        design.status, design.final_lesson_id, design.current_step = "finalized", lesson.lesson_id, "confirmation"
        design.revision += 1
        self.store.upsert_lesson_design(design)
        return {"status": "success", "lesson": lesson.to_dict(), "design": design.to_dict(), "capability_report": report}

    def export_docx(self, lesson_id: str, project_id: str, design_id: str = "") -> Dict[str, Any]:
        lesson = self.store.get_lesson(lesson_id)
        if lesson is None:
            raise KeyError("Unknown lesson")
        lesson_project_id = str((lesson.metadata or {}).get("project_id") or "")
        if lesson.source != "builtin" and lesson_project_id and lesson_project_id != project_id:
            raise ValueError("课时不属于当前项目")
        if design_id:
            design = self.get(design_id)
            if design.project_id != project_id or (design.final_lesson_id and design.final_lesson_id != lesson_id):
                raise ValueError("教案会话与当前项目或课时不匹配")
        output_dir = self.config.project_output_dir(project_id) / "lesson_plans"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"lesson_plan_{lesson.lesson_id}_{uuid4().hex[:8]}.docx"
        self._write_docx(path, lesson)
        job = self.store.create_job(project_id=project_id, job_type="lesson_plan_export", title=f"导出教案：{lesson.title}", workflow_type="lesson_plan_export", request={"lesson_id": lesson_id, "design_id": design_id})
        artifact = self.store.register_artifact(project_id=project_id, job_id=job.job_id, artifact_type="lesson_plan_docx", title=f"{lesson.title} 教案", path=str(path), metadata={"lesson_id": lesson_id, "design_id": design_id, "public_url": self.config.public_url_for_path(path)})
        self.store.set_job_status(job.job_id, "success", {"artifact": artifact.to_dict()})
        return {"status": "success", "artifact": artifact.to_dict(), "job_id": job.job_id}

    def _retrieve(self, message: str, owner_user_id: str) -> tuple[str, List[Dict[str, Any]]]:
        lowered = str(message or "").lower()
        local = any(token in lowered for token in ("教材", "课程资料", "知识库", "课标", "项目资料"))
        web = any(token in lowered for token in ("最新", "当前数据", "今年", "核实", "来源", "在线"))
        mode = "local+web" if local and web else "local" if local else "web" if web else "none"
        refs: List[Dict[str, Any]] = []
        if local and self.knowledge_base_service is not None:
            try:
                payload = self.knowledge_base_service.search(query=message, limit=3, owner_user_id=owner_user_id)
                for item in payload.get("items", []):
                    if isinstance(item, dict):
                        refs.append({"id": "kb:" + str(item.get("id") or ""), "title": str(item.get("title") or "项目知识库资料")})
            except Exception:
                pass
        if web and self.resource_search_service is not None:
            try:
                payload = self.resource_search_service.search(query=message, scope="web", limit=3)
                for item in payload.get("items", []):
                    if isinstance(item, dict):
                        refs.append({"id": str(item.get("id") or ""), "title": str(item.get("title") or "在线资料"), "url": str(item.get("url") or "")})
            except Exception:
                pass
        return mode, refs

    def _ask_minimax(self, design: LessonDesignRecord, step: str, message: str) -> Optional[Dict[str, Any]]:
        if self.minimax_client is None:
            return None
        system = (
            "你是高中地理教案共创助手。默认简体中文，每轮只推进一个步骤，先复述教师意图，再给可修改建议。"
            "只输出 JSON，字段为 reply、section_patch、next_step、source_refs、capability_bindings、suggestions。"
            "不要输出内部轨迹。当前步骤：" + STEP_LABELS.get(step, step) +
            "。草稿：" + json.dumps(design.draft, ensure_ascii=False)[:12000] +
            "。真实能力目录：" + json.dumps(self.capability_catalog(), ensure_ascii=False)[:8000]
        )
        try:
            content = self.minimax_client.chat_completion(
                [{"role": "system", "content": system}, {"role": "user", "content": message[:6000]}],
                temperature=0.2, extra_payload={"max_completion_tokens": 2400},
            )
            payload = self._extract_json(content)
            return self._validate_model_payload(payload)
        except Exception:
            return None

    def _fallback_turn(self, design: LessonDesignRecord, step: str, message: str) -> Dict[str, Any]:
        draft, clean = design.draft, message.strip()
        rename = re.search(r"(?:课题|标题)\s*(?:改为|调整为|改成|是)[:：\s]*(.+)", clean)
        if rename:
            title = rename.group(1).strip("。 ")
            return {
                "reply": f"好的，我把课题改为“{title}”，其他章节暂时保持不变。",
                "section_patch": {"title": title, "topic": title},
                "next_step": step,
                "source_refs": [],
                "capability_bindings": [],
                "suggestions": [],
            }
        if step == "requirements":
            duration_match = re.search(r"(\d+)\s*分钟", clean)
            grade_match = re.search(r"(高[一二三]|初[一二三]|七年级|八年级|九年级)", clean)
            topic = self._extract_topic(clean) or str(draft.get("topic") or draft.get("title") or "人口地理专题课")
            patch = {"title": topic or draft.get("title") or "人口地理专题课", "topic": topic or draft.get("topic") or "人口地理", "grade": grade_match.group(1) if grade_match else draft.get("grade") or "", "duration_minutes": int(duration_match.group(1)) if duration_match else int(draft.get("duration_minutes") or 40), "requirements": {"raw": clean}}
            reply = f"我理解你想做一节“{patch['title']}”。目前先按 {patch['duration_minutes']} 分钟、{patch['grade'] or '年级待定'}来搭框架。接下来我们先确认学生最需要带走的核心认识，可以吗？"
            next_step = "analysis"
        elif step == "analysis":
            patch = {"curriculum_interpretation": clean, "student_analysis": "学生已有基础知识，但需要通过地图和案例把分布格局与成因联系起来。", "textbook_analysis": "围绕人口分布、人口迁移或区域案例组织由图到理的学习任务。"}
            reply, next_step = "我先把课标、学情和教材放在同一条逻辑线上：从地图观察出发，再用案例解释空间差异。你可以直接改写其中任意一段。", "objectives"
        elif step == "objectives":
            items = [line.strip(" -•；;") for line in re.split(r"[；;\n。]", clean) if line.strip()] or ["能够描述人口分布的空间差异", "能够结合地图和案例解释差异成因"]
            patch = {
                "objectives": items[:5],
                "key_difficulties": {"key": [items[0]], "difficult": [items[-1]]},
                "methods": ["地图观察", "案例探究", "问题链"],
                "knowledge_structure": ["地图观察", "空间格局描述", "区域差异解释", "规律迁移"],
            }
            reply, next_step = "我把你的想法整理成了可观察的学习目标，并标出一个重点和一个难点。下一步会让每个目标都对应到地图操作或学生表达。", "process"
        elif step == "process":
            patch, next_step = {"stages": self._make_stages(draft.get("topic") or "人口分布", draft.get("duration_minutes") or 40)}, "capabilities"
            reply = "我先给出一版可执行的五列教学过程：每个环节都写清知识单元、知识点、活动、设计意图和系统操作。你可以指出要改哪一个环节。"
        elif step == "capabilities":
            bindings = [{"id": "map_2d", "reason": "展示人口分布空间格局"}, {"id": "knowledge_base", "reason": "必要时核对项目资料"}]
            if any(word in clean for word in ("三维", "3D", "地球")):
                bindings.append({"id": "globe_3d", "reason": "从全球尺度观察人口分布"})
            patch, next_step = {"capabilities": bindings}, "rehearsal"
            reply = "结合现有注册能力，我建议先用 2D 地图完成分布观察；如果你明确需要全球尺度，再加入 3D 地球。当前没有假造数据或图层。"
        elif step == "rehearsal":
            report = self.rehearse(design.design_id)
            reply = "预演检查已完成。" + (f"目前有：{'；'.join(report['errors'])}" if report["errors"] else "主要结构已经齐全。") + " 你可以先接受这一版，或者告诉我希望调整的环节。"
            return {"reply": reply, "section_patch": {}, "next_step": "confirmation", "suggestions": report["warnings"]}
        else:
            patch, next_step, reply = {}, "confirmation", "如果内容已经符合你的课堂设想，可以确认保存；若要调整，直接告诉我具体章节或环节。"
        return {"reply": reply, "section_patch": patch, "next_step": next_step, "source_refs": [], "capability_bindings": patch.get("capabilities", []), "suggestions": []}

    @staticmethod
    def _extract_topic(message: str) -> str:
        """Extract a short lesson topic from a natural multi-part requirement."""
        clean = str(message or "").strip()
        book_title = re.search(r"《\s*([^》\r\n]{1,80}?)\s*》", clean)
        if book_title:
            return book_title.group(1).strip()
        explicit = re.search(
            r"(?:课题|标题)\s*(?:改为|调整为|改成|为|是)?\s*[:：]?\s*[\"“]?([^，,。；;\n”\"]{1,80})",
            clean,
        )
        if explicit:
            return explicit.group(1).strip()
        simplified = re.sub(r"(高[一二三]|初[一二三]|七年级|八年级|九年级|\d+\s*分钟|单课时)", "", clean)
        simplified = simplified.replace("我想上", "").replace("请设计", "").replace("共创", "")
        parts = [item.strip(" ：:，,。、") for item in re.split(r"[，,。；;\n、]", simplified)]
        parts = [item for item in parts if item and len(item) <= 40]
        return parts[0] if parts else simplified.strip(" ：:，,。、")[:80]

    @classmethod
    def _normalize_requirements_result(
        cls, result: Dict[str, Any], message: str, draft: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Keep model output usable when one sentence contains topic plus constraints."""
        normalized = copy.deepcopy(result) if isinstance(result, dict) else {}
        patch = normalized.get("section_patch")
        patch = patch if isinstance(patch, dict) else {}
        topic = cls._extract_topic(message)
        duration_match = re.search(r"(\d+)\s*分钟", message)
        grade_match = re.search(r"(高[一二三]|初[一二三]|七年级|八年级|九年级)", message)
        original_title = str(patch.get("title") or patch.get("topic") or "").strip()
        if topic:
            patch["title"] = topic
            patch["topic"] = topic
        if duration_match:
            patch["duration_minutes"] = int(duration_match.group(1))
        if grade_match:
            patch["grade"] = grade_match.group(1)
        requirements = patch.get("requirements")
        if not isinstance(requirements, dict):
            requirements = {}
        requirements["raw"] = str(message or "").strip()
        patch["requirements"] = requirements
        normalized["section_patch"] = patch
        if topic and (len(original_title) > 60 or topic not in original_title):
            grade = str(patch.get("grade") or draft.get("grade") or "年级待定")
            duration = int(patch.get("duration_minutes") or draft.get("duration_minutes") or 40)
            normalized["reply"] = (
                f"我已记录：{grade}《{topic}》，{duration} 分钟；其余内容作为学情、证据主线和课堂任务要求保存。"
                "下一步我们确认课标与学情分析，可以吗？"
            )
        return normalized

    @staticmethod
    def _make_stages(topic: str, duration: int) -> List[Dict[str, Any]]:
        first, middle = max(5, min(10, duration // 5)), max(10, min(18, duration // 2))
        last = max(5, duration - first - middle)
        return [
            {"stage_id": "s1", "title": "情境导入与地图观察", "minutes": first, "knowledge_unit": topic, "knowledge_point": "空间分布格局", "content": f"展示{topic}专题地图，学生先说出最直观的空间差异。", "activities": ["学生观察地图并圈出集中区与稀疏区", "教师追问差异是否具有稳定方向"], "design_intent": "从可观察的空间证据进入问题。", "system_steps": ["打开2D地图", "叠加已注册的人口专题图层"], "scene": {"templates": ["population_distribution"], "catalog_layers": []}, "script": [], "questions": [{"question_id": "s1q1", "type": "open", "text": f"{topic}在空间上呈现怎样的差异？", "options": [], "answer_index": None, "expected_points": [], "misconceptions": []}], "assistant_prompts": []},
            {"stage_id": "s2", "title": "案例探究与成因解释", "minutes": middle, "knowledge_unit": topic, "knowledge_point": "空间差异的形成机制", "content": "以区域案例对比，引导学生把地图观察转化为地理解释。", "activities": ["小组比较两个区域", "学生用因果链说明自然与社会因素"], "design_intent": "让学生完成由描述到解释的认知跃迁。", "system_steps": ["使用地图标注", "调用已注册的案例或知识库资料"], "scene": {"templates": [], "catalog_layers": []}, "script": [], "questions": [{"question_id": "s2q1", "type": "open", "text": "哪些自然和社会条件共同造成了这种区域差异？", "options": [], "answer_index": None, "expected_points": ["自然条件", "社会经济条件", "因果联系"], "misconceptions": []}], "assistant_prompts": []},
            {"stage_id": "s3", "title": "归纳迁移与课堂小结", "minutes": last, "knowledge_unit": topic, "knowledge_point": "规律归纳与迁移", "content": "学生用一句话概括规律，再将方法迁移到新的区域。", "activities": ["个人完成结论卡片", "教师根据回答收束"], "design_intent": "检查目标达成并形成可迁移的方法。", "system_steps": ["课堂记录学生回答", "生成课后复习提示"], "scene": {"templates": [], "catalog_layers": []}, "script": [], "questions": [{"question_id": "s3q1", "type": "open", "text": "换到另一个区域时，你会按什么顺序完成读图与解释？", "options": [], "answer_index": None, "expected_points": ["读图例", "描述格局", "解释原因"], "misconceptions": []}], "assistant_prompts": []},
        ]

    @staticmethod
    def _section_has_content(value: Any) -> bool:
        if isinstance(value, dict):
            return any(LessonDesignService._section_has_content(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return any(LessonDesignService._section_has_content(item) for item in value)
        return bool(str(value or "").strip())

    @staticmethod
    def _build_diff_summary(design: LessonDesignRecord) -> List[Dict[str, Any]]:
        if not design.base_draft:
            return []
        result: List[Dict[str, Any]] = []
        for key in SECTION_KEYS:
            before = design.base_draft.get(key)
            after = design.draft.get(key)
            if before != after:
                result.append({
                    "section": key,
                    "label": SECTION_LABELS.get(key, key),
                    "changed": True,
                })
        return result

    @staticmethod
    def _validate_model_payload(payload: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return None
        patch = payload.get("section_patch", {})
        if not isinstance(patch, dict):
            return None
        allowed = set(SECTION_KEYS) | {"title", "subject", "grade", "topic", "duration_minutes"}
        normalized_patch = {str(key): copy.deepcopy(value) for key, value in patch.items() if str(key) in allowed}
        next_step = str(payload.get("next_step") or "")
        source_refs = payload.get("source_refs") if isinstance(payload.get("source_refs"), list) else []
        bindings = payload.get("capability_bindings") if isinstance(payload.get("capability_bindings"), list) else []
        suggestions = payload.get("suggestions") if isinstance(payload.get("suggestions"), list) else []
        return {
            "reply": str(payload.get("reply") or "").strip(),
            "section_patch": normalized_patch,
            "next_step": next_step if next_step in STEP_KEYS else "",
            "source_refs": [item for item in source_refs if isinstance(item, dict)],
            "capability_bindings": [item for item in bindings if isinstance(item, dict)],
            "suggestions": [str(item) for item in suggestions if str(item).strip()],
        }

    @staticmethod
    def _merge_patch(draft: Dict[str, Any], patch: Dict[str, Any]) -> None:
        allowed = set(SECTION_KEYS) | {"title", "subject", "grade", "topic", "duration_minutes"}
        for key, value in patch.items():
            if key not in allowed:
                continue
            if isinstance(value, dict) and isinstance(draft.get(key), dict):
                draft[key] = {**draft[key], **copy.deepcopy(value)}
            else:
                draft[key] = copy.deepcopy(value)

    @staticmethod
    def _next_step(step: str) -> str:
        try:
            return STEP_KEYS[min(STEP_KEYS.index(step) + 1, len(STEP_KEYS) - 1)]
        except ValueError:
            return STEP_KEYS[0]

    @staticmethod
    def _step_for_section(section_id: str) -> str:
        return {"requirements": "analysis", "objectives": "process", "stages": "capabilities"}.get(section_id, "confirmation")

    @staticmethod
    def _natural_prompt(step: str) -> str:
        return {
            "requirements": "先告诉我年级、课题和大致课时，我会帮你搭起第一版框架。",
            "analysis": "接下来一起确认课标重点、学生基础和教材位置。",
            "objectives": "这节课最希望学生学会什么？可以先说一两点。",
            "process": "我们把目标落到具体环节，每轮只设计一个关键环节。",
            "capabilities": "最后核对哪些地图、数据和课堂记录能力真的可用。",
            "rehearsal": "现在可以做一次时长、问题和能力检查。",
            "confirmation": "如果这版符合你的设想，就可以确认保存并导出 Word。",
        }.get(step, "我们从课题、年级和课时开始吧。")

    def _validate_bindings(self, bindings: Any) -> List[Dict[str, Any]]:
        catalog = {item["id"]: item for item in self.capability_catalog()}
        result = []
        for item in bindings if isinstance(bindings, list) else []:
            if isinstance(item, str):
                item = {"id": item}
            if not isinstance(item, dict):
                continue
            capability_id = str(item.get("id") or item.get("capability_id") or "")
            if capability_id in catalog:
                result.append({"id": capability_id, "label": catalog[capability_id]["label"], "reason": str(item.get("reason") or "")})
        return result

    @staticmethod
    def _merge_refs(existing: List[Dict[str, Any]], refs: Any) -> List[Dict[str, Any]]:
        result, seen = list(existing), {str(item.get("id") or item.get("source_id") or "") for item in existing}
        for item in refs if isinstance(refs, list) else []:
            if isinstance(item, str):
                item = {"id": item, "title": item}
            if not isinstance(item, dict):
                continue
            key = str(item.get("id") or item.get("source_id") or item.get("title") or "")
            if key and key not in seen:
                result.append({str(k): v for k, v in item.items() if k in {"id", "source_id", "dataset_id", "title", "year", "source_year", "url"}})
                seen.add(key)
        return result

    @staticmethod
    def _extract_json(content: str) -> Any:
        cleaned = str(content or "").strip()
        fence = chr(96) * 3
        if cleaned.startswith(fence):
            cleaned = re.sub(r"^" + re.escape(fence) + r"(?:json)?", "", cleaned, flags=re.I).strip()
            cleaned = re.sub(re.escape(fence) + r"$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start >= 0 and end > start:
                return json.loads(cleaned[start:end + 1])
            raise

    @staticmethod
    def _set_cell(cell: Any, value: Any, size: int = 9) -> None:
        from docx.shared import Pt
        from docx.oxml.ns import qn
        cell.text = str(value or "")
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.font.name = "宋体"
                if run._element.rPr is not None:
                    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
                run.font.size = Pt(size)

    def _write_docx(self, path: Path, lesson: LessonRecord) -> None:
        from docx import Document
        from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Inches, Pt

        template_path = (
            self.config.root_dir
            / "backend"
            / "app"
            / "data"
            / "builtin"
            / "lesson_plan_template"
            / "lesson_plan_template.docx"
        )
        doc = Document(str(template_path)) if template_path.is_file() else Document()
        body = doc._element.body
        for child in list(body):
            if child.tag != qn("w:sectPr"):
                body.remove(child)
        section = doc.sections[0]
        section.top_margin = section.bottom_margin = Inches(0.5)
        section.left_margin = section.right_margin = Inches(0.5)
        normal = doc.styles["Normal"]
        normal.font.name = "宋体"
        normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        normal.font.size = Pt(10)
        doc.core_properties.title = lesson.title
        doc.core_properties.subject = "WebGIS-AI 教案导出"
        doc.core_properties.author = "WebGIS-AI"
        doc.core_properties.last_modified_by = "WebGIS-AI"

        def set_table_geometry(table: Any, widths: list[int]) -> None:
            table.autofit = False
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table_properties = table._tbl.tblPr
            layout = table_properties.find(qn("w:tblLayout"))
            if layout is None:
                layout = OxmlElement("w:tblLayout")
                table_properties.append(layout)
            layout.set(qn("w:type"), "fixed")
            table_width = table_properties.find(qn("w:tblW"))
            if table_width is None:
                table_width = OxmlElement("w:tblW")
                table_properties.append(table_width)
            table_width.set(qn("w:type"), "dxa")
            table_width.set(qn("w:w"), str(sum(widths)))
            grid = table._tbl.tblGrid
            for node in list(grid):
                grid.remove(node)
            for width in widths:
                grid_col = OxmlElement("w:gridCol")
                grid_col.set(qn("w:w"), str(width))
                grid.append(grid_col)
            for row in table.rows:
                for cell, width in zip(row.cells, widths):
                    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                    cell.width = width
                    cell_properties = cell._tc.get_or_add_tcPr()
                    cell_width = cell_properties.find(qn("w:tcW"))
                    if cell_width is None:
                        cell_width = OxmlElement("w:tcW")
                        cell_properties.append(cell_width)
                    cell_width.set(qn("w:type"), "dxa")
                    cell_width.set(qn("w:w"), str(width))
                    margins = cell_properties.find(qn("w:tcMar"))
                    if margins is None:
                        margins = OxmlElement("w:tcMar")
                        cell_properties.append(margins)
                    for side, value in (("top", 80), ("start", 100), ("bottom", 80), ("end", 100)):
                        margin = margins.find(qn(f"w:{side}"))
                        if margin is None:
                            margin = OxmlElement(f"w:{side}")
                            margins.append(margin)
                        margin.set(qn("w:w"), str(value))
                        margin.set(qn("w:type"), "dxa")

        def mark_header(row: Any) -> None:
            row_properties = row._tr.get_or_add_trPr()
            header = OxmlElement("w:tblHeader")
            header.set(qn("w:val"), "true")
            row_properties.append(header)
            for cell in row.cells:
                shade = OxmlElement("w:shd")
                shade.set(qn("w:fill"), "D9EAF7")
                cell._tc.get_or_add_tcPr().append(shade)
                for run in cell.paragraphs[0].runs:
                    run.bold = True

        title_style = "Lesson Title" if "Lesson Title" in doc.styles else None
        title = doc.add_paragraph(style=title_style)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title.add_run(lesson.title).bold = True
        plan = lesson.plan or {}
        info = doc.add_table(rows=4, cols=4)
        info.style = "Table Grid"
        rows = [
            ("学科", lesson.subject, "年级", lesson.grade),
            ("课题", lesson.title, "课时", f"{plan.get('duration_minutes', lesson.metadata.get('duration_minutes', 40))}分钟"),
            ("课型", plan.get("lesson_type", "专题探究课"), "平台", "WebGIS-AI"),
            ("设计来源", "教师与智能体共创", "版本", "当前草稿"),
        ]
        for row, values in zip(info.rows, rows):
            for cell, value in zip(row.cells, values):
                self._set_cell(cell, value)
        set_table_geometry(info, [1200, 3900, 1200, 4169])
        for row in info.rows:
            for index in (0, 2):
                for run in row.cells[index].paragraphs[0].runs:
                    run.bold = True

        heading_style = "Lesson Heading" if "Lesson Heading" in doc.styles else "Heading 2"
        doc.add_paragraph("一、课标与前置分析", style=heading_style)
        for heading, text in (("课标解读", plan.get("curriculum_interpretation", "")), ("学情分析", plan.get("student_analysis", "")), ("教材分析", plan.get("textbook_analysis", ""))):
            p = doc.add_paragraph()
            p.add_run(heading + "：").bold = True
            p.add_run(str(text or "待教师补充。"))
        doc.add_paragraph("二、教学目标与重难点", style=heading_style)
        for objective in plan.get("objectives") or lesson.objectives:
            doc.add_paragraph(str(objective), style="List Bullet")
        difficulties = plan.get("key_difficulties") or {}
        p = doc.add_paragraph()
        p.add_run("重点：").bold = True
        p.add_run("；".join(str(x) for x in difficulties.get("key") or []) or "待确认")
        p.add_run("    难点：").bold = True
        p.add_run("；".join(str(x) for x in difficulties.get("difficult") or []) or "待确认")
        methods = plan.get("methods") or []
        if methods:
            p = doc.add_paragraph()
            p.add_run("教学方法：").bold = True
            p.add_run("；".join(str(item) for item in methods))
        doc.add_paragraph("三、知识结构", style=heading_style)
        knowledge = plan.get("knowledge_structure") or []
        structure = " → ".join(str(item) for item in knowledge) if knowledge else f"{lesson.title} → 空间分布观察 → 成因解释 → 规律迁移"
        structure_paragraph = doc.add_paragraph(structure)
        structure_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        doc.add_paragraph("四、教学过程", style=heading_style)
        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        for cell, header in zip(table.rows[0].cells, ["环节", "知识单元", "知识点", "具体内容/活动", "设计意图"]):
            self._set_cell(cell, header)
        mark_header(table.rows[0])
        for stage in lesson.stages:
            row = table.add_row()
            activities = stage.get("activities") or []
            content = stage.get("content") or "；".join(str(x) for x in activities) or "待补充"
            if stage.get("system_steps"):
                content += "\n系统操作：" + "；".join(str(x) for x in stage["system_steps"])
            values = [
                f"{stage.get('title', '')}（{stage.get('minutes', 0)}分钟）", stage.get("knowledge_unit", ""),
                stage.get("knowledge_point", ""), content, stage.get("design_intent", ""),
            ]
            for cell, value in zip(row.cells, values):
                self._set_cell(cell, value)
        set_table_geometry(table, [1300, 1500, 1500, 3569, 2600])
        doc.add_paragraph("五、参考资料与教学反思", style=heading_style)
        refs = plan.get("references") or []
        for ref in refs or ["本教案未强制附加默认来源；需要核验时由教师指定资料。"]:
            doc.add_paragraph(str(ref.get("title") if isinstance(ref, dict) else ref), style="List Bullet")
        doc.add_paragraph("教学反思：" + str(plan.get("reflection") or "课后根据课堂记录补充。"))
        doc.save(path)
