"""上课模拟测试服务：对课时做工作副本式试讲调整，完成后发布为新课时版本。

模拟测试是教案草稿与真实课堂之间的闸门：
- 开启时快照课时当前版本，所有调整只落在工作副本上，可随时取消丢弃；
- 完成时重新运行全部预演校验，通过后工作副本提交为新的课时版本并置
  ready_for_class=True，重新生成教案 Word；
- 模拟测试不产生班课（class session），因此其数据永远不会进入真实课堂报告。
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from ..models import LessonRehearsalRecord, LessonRecord, utc_now
from ..store import RuntimeStore
from .lesson_design import LessonDesignService
from .lessons import LessonService
from .question_bank import QuestionBankService


# PATCH 允许直接替换的工作副本顶层字段（题目快照、场景等结构由专用操作维护）。
PATCHABLE_KEYS = (
    "title", "subject", "grade", "objectives", "duration_minutes", "stages",
    "homework", "design_thinking", "core_questions", "board_design", "reflection",
    "question_citations", "methods", "key_difficulties", "curriculum_interpretation",
    "student_analysis", "textbook_analysis", "knowledge_structure", "capabilities",
)


class LessonRehearsalService:
    def __init__(
        self,
        config: Any,
        store: RuntimeStore,
        lesson_service: LessonService,
        lesson_design_service: LessonDesignService,
        question_bank_service: Optional[QuestionBankService],
    ) -> None:
        self.config = config
        self.store = store
        self.lesson_service = lesson_service
        self.lesson_design = lesson_design_service
        self.question_bank = question_bank_service

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def create(self, project_id: str, lesson_id: str, owner_user_id: str = "") -> Dict[str, Any]:
        lesson = self.lesson_service.get_lesson(lesson_id)
        if lesson.source == "builtin":
            raise ValueError("内置课时请先另存为教师课时，再进入模拟测试。")
        existing = self.store.list_lesson_rehearsals(lesson_id=lesson_id, status="active")
        if existing:
            # 已有进行中的模拟测试：直接续用（教师刷新/重开面板的场景）。
            return {"status": "success", "rehearsal": existing[0].to_dict(), "resumed": True}
        base_version = self._lesson_version(lesson)
        record = LessonRehearsalRecord.create(
            project_id=project_id,
            owner_user_id=owner_user_id,
            lesson_id=lesson_id,
            base_version=base_version,
            working_copy=self._working_copy_from_lesson(lesson),
        )
        record.modification_events.append(
            {"action": "rehearsal_start", "base_version": base_version, "at": utc_now()}
        )
        self.store.upsert_lesson_rehearsal(record)
        return {"status": "success", "rehearsal": record.to_dict(), "resumed": False}

    def get(self, rehearsal_id: str) -> LessonRehearsalRecord:
        record = self.store.get_lesson_rehearsal(rehearsal_id)
        if record is None:
            raise KeyError(f"Unknown rehearsal: {rehearsal_id}")
        return record

    def list(
        self,
        project_id: str = "",
        lesson_id: str = "",
        status: str = "",
    ) -> Dict[str, Any]:
        items = self.store.list_lesson_rehearsals(
            project_id=project_id, lesson_id=lesson_id, status=status
        )
        return {"status": "success", "items": [item.to_dict() for item in items]}

    # ------------------------------------------------------------------
    # 工作副本调整
    # ------------------------------------------------------------------

    def update(
        self,
        rehearsal_id: str,
        patch: Optional[Dict[str, Any]] = None,
        question_bind: Optional[Dict[str, Any]] = None,
        question_remove: Optional[Dict[str, Any]] = None,
        image_bind: Optional[Dict[str, Any]] = None,
        scene_capture: Optional[Dict[str, Any]] = None,
        test_result: Optional[Dict[str, Any]] = None,
        expected_revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        record = self.get(rehearsal_id)
        if record.status != "active":
            raise ValueError("模拟测试已结束，无法继续修改。")
        if expected_revision is not None and int(expected_revision) != record.revision:
            raise ValueError("模拟测试内容已更新，请刷新后再操作。")
        working = record.working_copy
        events: List[Dict[str, Any]] = []

        if patch:
            applied_keys = [key for key in patch if key in PATCHABLE_KEYS]
            for key in applied_keys:
                working[key] = copy.deepcopy(patch[key])
            if applied_keys:
                events.append({"action": "patch", "keys": sorted(applied_keys), "at": utc_now()})

        if question_bind:
            events.append(self._bind_question(record, question_bind))
        if question_remove:
            events.append(self._remove_question(record, question_remove))
        if image_bind:
            events.append(self._bind_image(record, image_bind))
        if scene_capture:
            events.append(self._capture_scene(record, scene_capture))
        if test_result:
            events.append(self._record_test_result(record, test_result))

        record.modification_events.extend(events)
        record.revision += 1
        self.store.upsert_lesson_rehearsal(record)
        return {"status": "success", "rehearsal": record.to_dict()}

    def apply_stage_scene(self, rehearsal_id: str, stage_id: str) -> Dict[str, Any]:
        record = self.get(rehearsal_id)
        if record.status != "active":
            raise ValueError("模拟测试已结束，无法预览场景。")
        stage = self._find_stage(record, stage_id)
        return self.lesson_service.apply_stage_scene_data(
            record.project_id, stage, lesson_id=record.lesson_id
        )

    # ------------------------------------------------------------------
    # 校验 / 完成 / 取消
    # ------------------------------------------------------------------

    def report(self, rehearsal_id: str) -> Dict[str, Any]:
        record = self.get(rehearsal_id)
        validation = self.lesson_design.validate_plan(record.working_copy, [])
        return {
            "status": "success",
            "rehearsal_id": record.rehearsal_id,
            "revision": record.revision,
            "report": validation,
        }

    def complete(self, rehearsal_id: str, expected_revision: Optional[int] = None) -> Dict[str, Any]:
        record = self.get(rehearsal_id)
        if record.status != "active":
            raise ValueError("模拟测试已结束，不能重复完成。")
        if expected_revision is not None and int(expected_revision) != record.revision:
            raise ValueError("模拟测试内容已更新，请刷新后再操作。")
        validation = self.lesson_design.validate_plan(record.working_copy, [])
        if not validation.get("ready"):
            record.modification_events.append(
                {"action": "complete_blocked", "errors": validation.get("errors") or [], "at": utc_now()}
            )
            record.revision += 1
            self.store.upsert_lesson_rehearsal(record)
            raise ValueError("模拟测试未通过：" + " ".join(validation.get("errors") or []))

        lesson = self.lesson_service.get_lesson(record.lesson_id)
        if lesson.source == "builtin":
            raise ValueError("内置课时不能被模拟测试覆盖。")
        new_version = self._lesson_version(lesson) + 1
        working = copy.deepcopy(record.working_copy)
        with self.store.batch():
            lesson.title = str(working.get("title") or lesson.title)
            lesson.grade = str(working.get("grade") or lesson.grade)
            lesson.objectives = [str(item) for item in working.get("objectives") or []]
            lesson.stages = copy.deepcopy(working.get("stages") or [])
            lesson.plan = working
            completed_at = utc_now()
            lesson.metadata = {
                **(lesson.metadata or {}),
                "duration_minutes": int(working.get("duration_minutes") or 0),
                "lesson_version": new_version,
                "ready_for_class": True,
                "last_rehearsal": {
                    "rehearsal_id": record.rehearsal_id,
                    "completed_at": completed_at,
                    "base_version": record.base_version,
                    "committed_version": new_version,
                },
            }
            self.store.upsert_lesson(lesson)
            record.status = "completed"
            record.committed_version = new_version
            record.completed_at = completed_at
            record.modification_events.append(
                {"action": "complete", "committed_version": new_version, "at": completed_at}
            )
            record.revision += 1
            self.store.upsert_lesson_rehearsal(record)

        # 完成后重新生成教案 Word（新版本）；失败不阻塞完成，但要把结果带回去。
        export_result: Dict[str, Any] = {}
        try:
            design_id = str((lesson.metadata or {}).get("design_id") or "")
            export_result = self.lesson_design.export_docx(lesson.lesson_id, record.project_id, design_id)
        except Exception:
            export_result = {"status": "skipped", "message": "新版教案 Word 导出失败，可稍后在课时详情重新导出。"}
        return {
            "status": "success",
            "lesson": lesson.to_dict(),
            "rehearsal": record.to_dict(),
            "report": validation,
            "export": export_result,
        }

    def cancel(self, rehearsal_id: str) -> Dict[str, Any]:
        record = self.get(rehearsal_id)
        if record.status != "active":
            raise ValueError("模拟测试已结束，无需取消。")
        record.status = "cancelled"
        record.modification_events.append({"action": "cancel", "at": utc_now()})
        record.revision += 1
        self.store.upsert_lesson_rehearsal(record)
        return {"status": "success", "rehearsal": record.to_dict()}

    # ------------------------------------------------------------------
    # 内部操作
    # ------------------------------------------------------------------

    def _bind_question(self, record: LessonRehearsalRecord, bind: Dict[str, Any]) -> Dict[str, Any]:
        stage_id = str(bind.get("stage_id") or "")
        stage = self._find_stage(record, stage_id)
        questions = stage.setdefault("questions", [])
        position = bind.get("position")
        if isinstance(position, bool) or not isinstance(position, int) or not (0 <= int(position) < max(len(questions), 1)):
            position = None
        manual = bind.get("manual")
        if isinstance(manual, dict) and str(manual.get("text") or "").strip():
            if self.question_bank is None:
                raise ValueError("题库服务不可用。")
            snapshot = QuestionBankService.build_manual_question(
                manual, stage_id, len(questions) + 1
            )
            label = "手动题目"
        else:
            question_id = str(bind.get("question_id") or "")
            if not question_id:
                raise ValueError("换题需要 question_id 或 manual 题干。")
            if self.question_bank is None:
                raise ValueError("题库服务不可用。")
            snapshot = self.question_bank.snapshot_question(question_id)
            label = str(snapshot.get("number") or snapshot.get("question_id") or "")
        if position is not None:
            questions[int(position)] = snapshot
        else:
            # 同一题不重复追加；重复换入视为替换第一处。
            existing = next(
                (index for index, item in enumerate(questions)
                 if isinstance(item, dict) and str(item.get("question_id")) == snapshot["question_id"]),
                None,
            )
            if existing is None:
                questions.append(snapshot)
            else:
                questions[existing] = snapshot
        return {"action": "bind_question", "stage_id": stage_id, "label": label, "at": utc_now()}

    def _remove_question(self, record: LessonRehearsalRecord, payload: Dict[str, Any]) -> Dict[str, Any]:
        stage_id = str(payload.get("stage_id") or "")
        question_id = str(payload.get("question_id") or "")
        stage = self._find_stage(record, stage_id)
        questions = stage.setdefault("questions", [])
        stage["questions"] = [
            item for item in questions
            if not (isinstance(item, dict) and str(item.get("question_id")) == question_id)
        ]
        return {"action": "remove_question", "stage_id": stage_id, "question_id": question_id, "at": utc_now()}

    def _bind_image(self, record: LessonRehearsalRecord, payload: Dict[str, Any]) -> Dict[str, Any]:
        stage_id = str(payload.get("stage_id") or "")
        question_id = str(payload.get("question_id") or "")
        image = payload.get("image")
        if not isinstance(image, dict) or not str(image.get("url") or "").strip():
            raise ValueError("绑定题图需要 image.url。")
        stage = self._find_stage(record, stage_id)
        question = next(
            (item for item in stage.get("questions") or []
             if isinstance(item, dict) and str(item.get("question_id")) == question_id),
            None,
        )
        if question is None:
            raise KeyError(f"Unknown question: {question_id}")
        entry = {
            "url": str(image.get("url") or ""),
            "width": int(image.get("width") or 0),
            "height": int(image.get("height") or 0),
            "content_type": str(image.get("content_type") or ""),
            "anchor": str(image.get("anchor") or "group"),
            "order": int(image.get("order") or 0),
        }
        images = [item for item in question.get("images") or [] if isinstance(item, dict)]
        if not any(str(item.get("url")) == entry["url"] for item in images):
            images.append(entry)
        question["images"] = images
        return {"action": "bind_image", "stage_id": stage_id, "question_id": question_id, "at": utc_now()}

    def _capture_scene(self, record: LessonRehearsalRecord, payload: Dict[str, Any]) -> Dict[str, Any]:
        stage_id = str(payload.get("stage_id") or "")
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            raise ValueError("存图需要 snapshot。")
        stage = self._find_stage(record, stage_id)
        stage["scene"] = LessonService.merge_scene_snapshot(stage.get("scene") or {}, snapshot)
        return {"action": "scene_capture", "stage_id": stage_id, "at": utc_now()}

    def _record_test_result(self, record: LessonRehearsalRecord, payload: Dict[str, Any]) -> Dict[str, Any]:
        key = str(payload.get("key") or "").strip()
        if not key:
            raise ValueError("试讲记录需要 key。")
        entry = {
            "passed": bool(payload.get("passed")),
            "note": str(payload.get("note") or ""),
            "at": utc_now(),
        }
        record.test_results[key] = entry
        return {"action": "test_result", "key": key, "passed": entry["passed"], "at": utc_now()}

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    def _find_stage(self, record: LessonRehearsalRecord, stage_id: str) -> Dict[str, Any]:
        stages = record.working_copy.get("stages") or []
        for stage in stages:
            if isinstance(stage, dict) and str(stage.get("stage_id")) == str(stage_id):
                return stage
        raise KeyError(f"Unknown stage: {stage_id}")

    @staticmethod
    def _lesson_version(lesson: LessonRecord) -> int:
        raw = (lesson.metadata or {}).get("lesson_version")
        try:
            return max(1, int(raw or 1))
        except (TypeError, ValueError):
            return 1

    def _working_copy_from_lesson(self, lesson: LessonRecord) -> Dict[str, Any]:
        plan = lesson.plan or {}
        stages = plan.get("stages") or lesson.stages or []
        minutes = 0
        for stage in stages:
            try:
                minutes += max(0, int((stage or {}).get("minutes") or 0))
            except (TypeError, ValueError):
                continue
        working: Dict[str, Any] = copy.deepcopy(plan) if plan else {}
        working.setdefault("title", lesson.title)
        working.setdefault("subject", lesson.subject)
        working.setdefault("grade", lesson.grade)
        working["objectives"] = list(working.get("objectives") or lesson.objectives or [])
        working["stages"] = copy.deepcopy(stages)
        if not working.get("duration_minutes"):
            working["duration_minutes"] = int(
                (lesson.metadata or {}).get("duration_minutes") or minutes or 40
            )
        homework = working.get("homework")
        if not isinstance(homework, dict):
            homework = {}
        homework.setdefault("basic", [])
        homework.setdefault("inquiry", [])
        working["homework"] = homework
        return working
