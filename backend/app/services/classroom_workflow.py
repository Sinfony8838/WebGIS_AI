from __future__ import annotations

import json
import os
import secrets
import socket
import threading
import time
from typing import Any, Dict, List, Optional

from .lessons import LessonService
from .lesson_design import LessonDesignService
from .lesson_rehearsal import LessonRehearsalService
from .population_lesson_prep import PopulationLessonPrepService
from .question_bank import QuestionBankService
from .reports import ReportService
from .visual_query import VisualQueryService


class ClassroomWorkflowRuntime:
    """Pre-class, in-class, after-class workflow layer.

    This is kept separate from the D-drive v1.2 runtime so the improved
    3D/UI/workflow skeleton stays intact while the newer lesson/session
    features remain available.
    """

    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.config = runtime.config
        self.store = runtime.store
        self.visual_query_service = VisualQueryService(self.config)
        self.lesson_service = LessonService(
            self.config,
            self.store,
            runtime.template_service,
            self.visual_query_service,
            minimax_client=runtime.minimax_client if self.config.minimax_enabled() else None,
            catalog_layer_loader=runtime.materialize_catalog_layer,
        )
        self.report_service = ReportService(
            self.config,
            minimax_client=runtime.minimax_client if self.config.minimax_enabled() else None,
        )
        self.population_lesson_prep = PopulationLessonPrepService(
            self.store,
            self.lesson_service,
            runtime.population_source_registry_service,
        )
        self.question_bank = QuestionBankService(
            self.config,
            minimax_client=runtime.minimax_client if self.config.minimax_enabled() else None,
        )
        self.lesson_design = LessonDesignService(
            self.config,
            self.store,
            self.lesson_service,
            minimax_client=runtime.minimax_client if self.config.minimax_enabled() else None,
            template_service=runtime.template_service,
            catalog_service=runtime.one_map_catalog_service,
            knowledge_base_service=runtime.knowledge_base_service,
            resource_search_service=runtime.resource_search_service,
            question_bank_service=self.question_bank,
        )
        self.lesson_rehearsal = LessonRehearsalService(
            self.config,
            self.store,
            self.lesson_service,
            self.lesson_design,
            self.question_bank,
        )
        self._student_presence: Dict[str, Dict[str, float]] = {}

    # ------------------------------------------------------------------
    # Lessons
    # ------------------------------------------------------------------

    def list_lessons(self, owner_user_id: str = "", include_all: bool = False) -> Dict[str, Any]:
        return self.lesson_service.list_lessons(
            owner_user_id=owner_user_id,
            include_all=include_all,
        )

    def get_lesson(self, lesson_id: str) -> Dict[str, Any]:
        return {"status": "success", **self.lesson_service.get_lesson(lesson_id).to_dict()}

    def create_lesson(self, payload: Dict[str, Any], owner_user_id: str = "") -> Dict[str, Any]:
        return {
            "status": "success",
            **self.lesson_service.create_lesson(
                payload,
                owner_user_id=owner_user_id,
            ).to_dict(),
        }

    def update_lesson(self, lesson_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", **self.lesson_service.update_lesson(lesson_id, payload).to_dict()}

    def delete_lesson(self, lesson_id: str) -> Dict[str, Any]:
        self.lesson_service.delete_lesson(lesson_id)
        return {"status": "success", "lesson_id": lesson_id}

    def apply_lesson_scene(self, project_id: str, lesson_id: str, stage_id: str) -> Dict[str, Any]:
        self.runtime._require_project(project_id)
        result = self.lesson_service.apply_stage_scene(project_id, lesson_id, stage_id)
        for session in self.store.list_class_sessions(project_id=project_id, status="running"):
            if session.lesson_id != lesson_id:
                continue
            self.store.append_session_event(
                session.session_id,
                "scene_applied",
                stage_id=stage_id,
                payload={"stage_title": result.get("stage_title", "")},
            )
        return result

    def capture_lesson_scene(self, lesson_id: str, stage_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        return self.lesson_service.capture_stage_scene(lesson_id, stage_id, snapshot)

    def submit_lesson_import(self, project_id: str, text: str, owner_user_id: str = "") -> Dict[str, Any]:
        job = self.store.create_job(
            project_id=project_id,
            job_type="lesson_import",
            title="Import lesson plan",
            workflow_type="lesson_import",
            request={"text_length": len(text or "")},
        )
        threading.Thread(
            target=self._run_lesson_import_job,
            args=(job.job_id, text, owner_user_id),
            daemon=True,
        ).start()
        return {"status": "accepted", "job_id": job.job_id, "project_id": project_id}

    def submit_population_lesson_prep(self, project_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.population_lesson_prep.submit(project_id, payload)

    # ------------------------------------------------------------------
    # Guided lesson-plan co-creation
    # ------------------------------------------------------------------

    def create_lesson_design(self, project_id: str, owner_user_id: str, base_lesson_id: str = "", requirements: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        design = self.lesson_design.create_or_resume(project_id, owner_user_id, base_lesson_id, requirements)
        return {"status": "success", **design.to_dict(), **self.lesson_design.session_view(design), "capabilities": self.lesson_design.capability_catalog()}

    def get_lesson_design(self, design_id: str) -> Dict[str, Any]:
        design = self.lesson_design.get(design_id)
        return {"status": "success", **design.to_dict(), **self.lesson_design.session_view(design), "capabilities": self.lesson_design.capability_catalog()}

    def turn_lesson_design(self, design_id: str, message: str, expected_revision: Optional[int] = None, step: str = "") -> Dict[str, Any]:
        return self.lesson_design.turn(design_id, message, expected_revision, step)

    def resolve_lesson_design(self, design_id: str, section_id: str, decision: str = "accept", teacher_note: str = "", expected_revision: Optional[int] = None, value: Any = None) -> Dict[str, Any]:
        return self.lesson_design.resolve(design_id, section_id, decision, teacher_note, expected_revision, value)

    def bind_lesson_design_question(
        self,
        design_id: str,
        stage_id: str,
        question_id: str = "",
        manual: Optional[Dict[str, Any]] = None,
        action: str = "add",
        position: Optional[int] = None,
        expected_revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self.lesson_design.bind_question(
            design_id, stage_id,
            question_id=question_id, manual=manual, action=action,
            position=position, expected_revision=expected_revision,
        )

    def finalize_lesson_design(self, design_id: str, expected_revision: Optional[int] = None, apply_base: bool = False) -> Dict[str, Any]:
        return self.lesson_design.finalize(design_id, expected_revision, apply_base)

    def export_lesson_docx(self, lesson_id: str, project_id: str, design_id: str = "") -> Dict[str, Any]:
        return self.lesson_design.export_docx(lesson_id, project_id, design_id)

    # ------------------------------------------------------------------
    # Question banks（题库导入/检索）
    # ------------------------------------------------------------------

    def submit_question_bank_import(
        self,
        project_id: str,
        files: List[Dict[str, Any]],
        owner_user_id: str = "",
    ) -> Dict[str, Any]:
        """``files`` 为 [{"filename": ..., "raw": bytes}]；导入在后台线程执行。"""
        job = self.store.create_job(
            project_id=project_id,
            job_type="question_bank_import",
            title="Import question bank",
            workflow_type="question_bank_import",
            request={"file_count": len(files), "filenames": [str(item.get("filename") or "") for item in files]},
        )
        threading.Thread(
            target=self._run_question_bank_import_job,
            args=(job.job_id, project_id, files, owner_user_id),
            daemon=True,
        ).start()
        return {"status": "accepted", "job_id": job.job_id, "project_id": project_id}

    def _run_question_bank_import_job(
        self,
        job_id: str,
        project_id: str,
        files: List[Dict[str, Any]],
        owner_user_id: str,
    ) -> None:
        try:
            self.store.set_job_status(job_id, "running")
            payload = [
                (str(item.get("filename") or ""), bytes(item.get("raw") or b""))
                for item in files
            ]

            def progress(stage: str, message: str) -> None:
                key = "analysis" if stage == "validate" else "actions"
                self.store.update_job_stage(job_id, key, "running", message)

            self.store.update_job_stage(job_id, "analysis", "running", "Validating DOCX files.")
            banks = self.question_bank.import_files(project_id, owner_user_id, payload, progress=progress)
            self.store.update_job_stage(job_id, "analysis", "success", "Question bank files parsed.")
            self.store.update_job_stage(job_id, "actions", "success", f"Imported {len(banks)} question bank(s).")
            self.store.update_job_stage(job_id, "map", "skipped", "Question bank import does not change the map.")
            self.store.update_job_stage(job_id, "artifacts", "success", "Question bank stored.")
            summary_parts = [
                f"{bank.get('title', '')}：{bank.get('question_count', 0)} 题"
                for bank in banks
            ]
            self.store.set_job_status(
                job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "question_bank_import",
                    "summary": "；".join(summary_parts),
                    "assistant_message": f"题库导入完成（{len(banks)} 套）。可在教案设计的题目匹配环节检索使用。",
                    "banks": banks,
                    "stages": self.store.get_job(job_id).stages,
                },
            )
        except Exception as exc:
            self.runtime._fail_job(job_id, "question_bank_import", str(exc))

    def list_question_banks(self, project_id: str) -> Dict[str, Any]:
        return {"status": "success", "items": self.question_bank.list_banks(project_id)}

    def get_question_bank_questions(
        self,
        bank_id: str,
        section: str = "",
        qtype: str = "",
        answer_complete: Optional[bool] = None,
        search: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        return self.question_bank.list_questions(
            bank_id,
            section=section,
            qtype=qtype,
            answer_complete=answer_complete,
            search=search,
            page=page,
            page_size=page_size,
        )

    def get_question_bank_group(self, bank_id: str, group_key: str) -> Dict[str, Any]:
        return self.question_bank.get_group(bank_id, group_key)

    def search_question_banks(
        self,
        project_id: str,
        bank_ids: Optional[List[str]] = None,
        topic: str = "",
        knowledge: str = "",
        objectives: Optional[List[str]] = None,
        qtype: str = "",
        exclude_ids: Optional[List[str]] = None,
        limit: int = 5,
    ) -> Dict[str, Any]:
        return self.question_bank.search(
            project_id=project_id,
            bank_ids=bank_ids,
            topic=topic,
            knowledge=knowledge,
            objectives=objectives,
            qtype=qtype,
            exclude_ids=exclude_ids,
            limit=limit,
        )

    def delete_question_bank(self, bank_id: str) -> Dict[str, Any]:
        return self.question_bank.delete_bank(bank_id)

    # ------------------------------------------------------------------
    # 上课模拟测试（教案草稿 → 真实课堂的闸门）
    # ------------------------------------------------------------------

    def create_lesson_rehearsal(self, project_id: str, lesson_id: str, owner_user_id: str = "") -> Dict[str, Any]:
        self.runtime._require_project(project_id)
        return self.lesson_rehearsal.create(project_id, lesson_id, owner_user_id=owner_user_id)

    def get_lesson_rehearsal(self, rehearsal_id: str) -> Dict[str, Any]:
        record = self.lesson_rehearsal.get(rehearsal_id)
        return {"status": "success", "rehearsal": record.to_dict()}

    def list_lesson_rehearsals(
        self,
        project_id: str = "",
        lesson_id: str = "",
        status: str = "",
    ) -> Dict[str, Any]:
        return self.lesson_rehearsal.list(project_id=project_id, lesson_id=lesson_id, status=status)

    def update_lesson_rehearsal(
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
        return self.lesson_rehearsal.update(
            rehearsal_id,
            patch=patch,
            question_bind=question_bind,
            question_remove=question_remove,
            image_bind=image_bind,
            scene_capture=scene_capture,
            test_result=test_result,
            expected_revision=expected_revision,
        )

    def apply_rehearsal_stage_scene(self, rehearsal_id: str, stage_id: str) -> Dict[str, Any]:
        return self.lesson_rehearsal.apply_stage_scene(rehearsal_id, stage_id)

    def lesson_rehearsal_report(self, rehearsal_id: str) -> Dict[str, Any]:
        return self.lesson_rehearsal.report(rehearsal_id)

    def complete_lesson_rehearsal(self, rehearsal_id: str, expected_revision: Optional[int] = None) -> Dict[str, Any]:
        return self.lesson_rehearsal.complete(rehearsal_id, expected_revision=expected_revision)

    def cancel_lesson_rehearsal(self, rehearsal_id: str) -> Dict[str, Any]:
        return self.lesson_rehearsal.cancel(rehearsal_id)

    def resolve_population_lesson_prep(
        self,
        job_id: str,
        decision: str,
        accepted_stage_ids: Any = None,
    ) -> Dict[str, Any]:
        return self.population_lesson_prep.resolve_change_set(
            job_id,
            decision,
            accepted_stage_ids=accepted_stage_ids,
        )

    def _run_lesson_import_job(self, job_id: str, text: str, owner_user_id: str = "") -> None:
        try:
            self.store.set_job_status(job_id, "running")
            self.store.update_job_stage(job_id, "analysis", "running", "Parsing lesson text.")
            result = self.lesson_service.import_from_text(text, owner_user_id=owner_user_id)
            lesson = result["lesson"]
            parser_label = "minimax" if result.get("parser") == "minimax" else "rules"
            self.store.update_job_stage(job_id, "analysis", "success", f"Lesson parsed by {parser_label}.")
            self.store.update_job_stage(job_id, "actions", "success", f"Detected {len(lesson.get('stages', []))} stages.")
            self.store.update_job_stage(job_id, "map", "skipped", "Lesson import does not change the map.")
            self.store.update_job_stage(job_id, "artifacts", "success", "Lesson saved.")
            self.store.set_job_status(
                job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "lesson_import",
                    "summary": f"Imported lesson: {lesson.get('title', '')}",
                    "assistant_message": "Lesson imported. Review stages and bind map scenes before class.",
                    "lesson": lesson,
                    "parser": result.get("parser"),
                    "stages": self.store.get_job(job_id).stages,
                },
            )
        except Exception as exc:  # pragma: no cover
            self.runtime._fail_job(job_id, "lesson_import", str(exc))

    # ------------------------------------------------------------------
    # Class sessions
    # ------------------------------------------------------------------

    def create_class_session(self, lesson_id: str, project_id: str) -> Dict[str, Any]:
        self.runtime._require_project(project_id)
        lesson = self.lesson_service.get_lesson(lesson_id)
        # 教案设计产出的课时必须先通过模拟测试才能开真实课堂；
        # 内置/导入/手动课时保持原有开课路径，不回溯设卡。
        metadata = dict(lesson.metadata or {})
        ready = metadata.get("ready_for_class")
        if isinstance(ready, str):
            ready = ready.strip().lower() == "true"
        if str(metadata.get("created_from") or "") == "lesson_design" and not ready:
            raise ValueError("教案还未通过模拟测试，不能开始真实课堂。")
        join_code = self._generate_join_code()
        with self.store.batch():
            session = self.store.create_class_session(
                lesson_id=lesson_id,
                project_id=project_id,
                join_code=join_code,
                # 真实课堂读取开课时刻的课时快照，之后的课时版本演进不影响已下课报告。
                metadata={
                    "lesson_title": lesson.title,
                    "lesson_snapshot": lesson.to_dict(),
                },
            )
            self.store.append_session_event(session.session_id, "session_start", payload={"lesson_title": lesson.title})
            self.store.add_recent_action(
                project_id,
                "Start class",
                f"Class session started for {lesson.title}.",
                status="success",
                metadata={"session_id": session.session_id},
            )
        return {"status": "success", "session": session.to_dict(), "student_join_url": self._student_join_url(join_code)}

    def get_class_session(self, session_id: str) -> Dict[str, Any]:
        session = self._require_session(session_id)
        return {"status": "success", "session": session.to_dict(), "student_join_url": self._student_join_url(session.join_code)}

    def list_class_sessions(self, lesson_id: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
        sessions = self.store.list_class_sessions(lesson_id=lesson_id, project_id=project_id)
        return {"status": "success", "items": [session.to_dict() for session in sessions]}

    def end_class_session(self, session_id: str) -> Dict[str, Any]:
        session = self._require_session(session_id)
        if session.status == "running":
            with self.store.batch():
                self.store.append_session_event(session_id, "session_end")
                session = self.store.end_class_session(session_id)
                self.store.add_recent_action(session.project_id, "End class", "Class session ended.", status="success")
        self._student_presence.pop(session_id, None)
        return {"status": "success", "session": session.to_dict()}

    def enter_session_stage(self, session_id: str, stage_id: str) -> Dict[str, Any]:
        session = self._require_session(session_id)
        if session.status != "running":
            raise ValueError("Class session has already ended")
        lesson = self.lesson_service.get_lesson(session.lesson_id)
        stage = lesson.find_stage(stage_id)
        if stage is None:
            raise KeyError(f"Unknown stage: {stage_id}")
        with self.store.batch():
            self.store.set_session_stage(session_id, stage_id)
            self.store.append_session_event(
                session_id,
                "stage_enter",
                stage_id=stage_id,
                payload={"stage_title": stage.get("title", ""), "planned_minutes": stage.get("minutes", 0)},
            )
            scene_result = self.apply_lesson_scene(session.project_id, session.lesson_id, stage_id)
        return {"status": "success", "session_id": session_id, "stage": stage, "scene": scene_result}

    def launch_session_question(
        self,
        session_id: str,
        stage_id: str = "",
        question_id: str = "",
        adhoc: Optional[Dict[str, Any]] = None,
        delivery: str = "student",
    ) -> Dict[str, Any]:
        session = self._require_session(session_id)
        if session.status != "running":
            raise ValueError("Class session has already ended")
        question: Optional[Dict[str, Any]] = None
        if question_id:
            lesson = self.lesson_service.get_lesson(session.lesson_id)
            for stage in lesson.stages:
                for item in stage.get("questions", []):
                    if str(item.get("question_id")) == question_id:
                        question = dict(item)
                        stage_id = stage_id or str(stage.get("stage_id") or "")
                        break
                if question:
                    break
            if question is None:
                raise KeyError(f"Unknown question: {question_id}")
        elif adhoc and str(adhoc.get("text") or "").strip():
            options = [str(option) for option in adhoc.get("options") or []]
            question = {
                "question_id": f"adhoc_{secrets.token_hex(4)}",
                "type": "choice" if options else "open",
                "text": str(adhoc["text"]).strip(),
                "options": options,
                "answer_index": adhoc.get("answer_index") if isinstance(adhoc.get("answer_index"), int) else None,
                "expected_points": [],
                "misconceptions": [],
            }
        else:
            raise ValueError("Question launch requires question_id or adhoc text")

        delivery_mode = str(delivery or "student").strip().lower()
        if delivery_mode not in {"student", "teacher_oral"}:
            raise ValueError(f"Unsupported question delivery: {delivery_mode}")

        active = {
            **question,
            "stage_id": stage_id or session.current_stage_id,
            "launched_at": self._utc_now(),
            "delivery": delivery_mode,
        }
        if delivery_mode == "teacher_oral":
            event = self.store.append_session_event(
                session_id,
                "teacher_question_presented",
                stage_id=str(active.get("stage_id") or ""),
                payload={
                    "question_id": active["question_id"],
                    "text": active["text"],
                    "type": active["type"],
                    "options": active["options"],
                    "delivery": "teacher_oral",
                },
            )
            return {"status": "success", "active_question": {}, "presented_question": active, "event": event}

        with self.store.batch():
            self.store.set_active_question(session_id, active)
            self.store.append_session_event(
                session_id,
                "question_launched",
                stage_id=stage_id,
                payload={
                    "question_id": active["question_id"],
                    "text": active["text"],
                    "type": active["type"],
                    "options": active["options"],
                },
            )
        return {"status": "success", "active_question": active}

    def close_session_question(self, session_id: str) -> Dict[str, Any]:
        session = self._require_session(session_id)
        active = dict(session.active_question or {})
        if not active.get("question_id"):
            return {"status": "success", "active_question": {}}
        tally = self._question_tally(session, str(active["question_id"]), active)
        with self.store.batch():
            self.store.append_session_event(
                session_id,
                "question_closed",
                stage_id=str(active.get("stage_id") or ""),
                payload={"question_id": active["question_id"], "tally": tally},
            )
            self.store.set_active_question(session_id, {})
        return {"status": "success", "tally": tally}

    def add_session_observation(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        session = self._require_session(session_id)
        if session.status != "running":
            raise ValueError("Class session has already ended")
        verdict = str(payload.get("verdict") or "").strip()
        if verdict not in {"correct", "partial", "misconception"}:
            raise ValueError(f"Unsupported observation verdict: {verdict}")
        event = self.store.append_session_event(
            session_id,
            "teacher_observation",
            stage_id=str(payload.get("stage_id") or ""),
            payload={
                "question_id": str(payload.get("question_id") or ""),
                "verdict": verdict,
                "tag": str(payload.get("tag") or ""),
                "note": str(payload.get("note") or ""),
            },
        )
        return {"status": "success", "event": event}

    def log_session_event(
        self,
        session_id: str,
        event_type: str,
        stage_id: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._require_session(session_id)
        allowed = {"annotation", "snapshot", "note", "assistant_exchange"}
        if event_type not in allowed:
            raise ValueError(f"Unsupported event type: {event_type}")
        event = self.store.append_session_event(session_id, event_type, stage_id=stage_id, payload=payload or {})
        return {"status": "success", "event": event}

    def session_live(self, session_id: str) -> Dict[str, Any]:
        session = self._require_session(session_id)
        active = dict(session.active_question or {})
        tally: Optional[Dict[str, Any]] = None
        if active.get("question_id"):
            tally = self._question_tally(session, str(active["question_id"]), active)
        return {
            "status": "success",
            "session_id": session_id,
            "session_status": session.status,
            "current_stage_id": session.current_stage_id,
            "active_question": active,
            "tally": tally,
            "joined_count": self._presence_count(session_id),
            "recent_events": session.events[-12:],
        }

    # ------------------------------------------------------------------
    # Student side
    # ------------------------------------------------------------------

    def student_state(self, join_code: str, nickname: str = "") -> Dict[str, Any]:
        session = self.store.find_session_by_join_code(join_code)
        if session is None:
            raise KeyError("Unknown or ended join code")
        if nickname.strip():
            self._touch_presence(session.session_id, nickname.strip())
        lesson = self.store.get_lesson(session.lesson_id)
        stage_title = ""
        if lesson is not None and session.current_stage_id:
            stage = lesson.find_stage(session.current_stage_id)
            if stage:
                stage_title = str(stage.get("title") or "")
        active = dict(session.active_question or {})
        public_question = {}
        if active.get("question_id"):
            public_question = {
                "question_id": active.get("question_id"),
                "type": active.get("type"),
                "text": active.get("text"),
                "options": active.get("options", []),
            }
        return {"status": "success", "session_status": session.status, "stage_title": stage_title, "active_question": public_question}

    def student_answer(self, join_code: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        session = self.store.find_session_by_join_code(join_code)
        if session is None:
            raise KeyError("Unknown or ended join code")
        active = dict(session.active_question or {})
        question_id = str(payload.get("question_id") or "")
        if not active.get("question_id") or question_id != str(active["question_id"]):
            raise ValueError("Question is not open for answers")
        nickname = str(payload.get("nickname") or "").strip()[:16] or "anonymous"
        response: Dict[str, Any] = {"nickname": nickname}
        if active.get("type") == "choice":
            choice_index = payload.get("choice_index")
            options = active.get("options") or []
            if not isinstance(choice_index, int) or not (0 <= choice_index < len(options)):
                raise ValueError("Invalid choice index")
            response["choice_index"] = choice_index
        else:
            text = str(payload.get("text") or "").strip()[:120]
            if not text:
                raise ValueError("Answer text is required")
            response["text"] = text
        with self.store.batch():
            entry = self.store.add_student_response(session.session_id, question_id, response)
            self.store.append_session_event(
                session.session_id,
                "student_response",
                stage_id=str(active.get("stage_id") or ""),
                payload={"question_id": question_id, **response},
            )
        self._touch_presence(session.session_id, nickname)
        return {"status": "success", "recorded": entry}

    # ------------------------------------------------------------------
    # After-class report
    # ------------------------------------------------------------------

    def submit_session_report(self, session_id: str) -> Dict[str, Any]:
        session = self._require_session(session_id)
        job = self.store.create_job(
            project_id=session.project_id,
            job_type="class_report",
            title="Generate class report",
            workflow_type="class_report",
            request={"session_id": session_id},
        )
        threading.Thread(target=self._run_session_report_job, args=(job.job_id, session_id), daemon=True).start()
        return {"status": "accepted", "job_id": job.job_id, "session_id": session_id}

    def _run_session_report_job(self, job_id: str, session_id: str) -> None:
        try:
            session = self._require_session(session_id)
            lesson = self.store.get_lesson(session.lesson_id)
            self.store.set_job_status(job_id, "running")
            self.store.update_job_stage(job_id, "analysis", "running", "Aggregating class events and answers.")
            statistics = self.report_service.build_statistics(session, lesson)
            self.store.update_job_stage(job_id, "analysis", "success", "Class statistics ready.")
            self.store.update_job_stage(job_id, "actions", "running", "Composing diagnosis.")
            diagnosis = self.report_service.compose_diagnosis(statistics)
            practice_recommendations = self.report_service.build_practice_recommendations(statistics, lesson)
            diagnosis_label = "minimax" if diagnosis.get("generator") == "minimax" else "rules"
            self.store.update_job_stage(job_id, "actions", "success", f"Diagnosis generated by {diagnosis_label}.")
            self.store.update_job_stage(job_id, "map", "skipped", "Report generation does not change the map.")

            markdown = self.report_service.render_markdown(statistics, diagnosis, practice_recommendations)
            output_dir = self.config.project_output_dir(session.project_id)
            markdown_path = self.config.unique_path(output_dir, f"class_report_{session_id[:12]}.md")
            markdown_path.write_text(markdown, encoding="utf-8")
            json_path = self.config.unique_path(output_dir, f"class_report_{session_id[:12]}.json")
            json_path.write_text(
                json.dumps(
                    {
                        "statistics": statistics,
                        "diagnosis": diagnosis,
                        "practice_recommendations": practice_recommendations,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            markdown_artifact = self.store.register_artifact(
                project_id=session.project_id,
                job_id=job_id,
                artifact_type="class_report",
                title=f"Class report: {statistics.get('lesson_title', '')}",
                path=str(markdown_path),
                metadata={"public_url": self.config.public_url_for_path(markdown_path), "session_id": session_id, "format": "markdown"},
            )
            self.store.register_artifact(
                project_id=session.project_id,
                job_id=job_id,
                artifact_type="class_report_data",
                title="Class report data",
                path=str(json_path),
                metadata={"public_url": self.config.public_url_for_path(json_path), "session_id": session_id, "format": "json"},
            )
            self.store.update_job_stage(job_id, "artifacts", "success", "Class report artifacts registered.")
            self.store.set_job_status(
                job_id,
                "completed",
                result={
                    "status": "success",
                    "workflow_type": "class_report",
                    "summary": f"Class report generated by {diagnosis_label}.",
                    "assistant_message": "After-class report is ready.",
                    "session_id": session_id,
                    "statistics": statistics,
                    "diagnosis": diagnosis,
                    "practice_recommendations": practice_recommendations,
                    "report_url": markdown_artifact.metadata.get("public_url", ""),
                    "stages": self.store.get_job(job_id).stages,
                },
            )
        except Exception as exc:  # pragma: no cover
            self.runtime._fail_job(job_id, "class_report", str(exc))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _question_tally(self, session: Any, question_id: str, question: Dict[str, Any]) -> Dict[str, Any]:
        responses = list(session.responses.get(question_id, []))
        options = question.get("options") or []
        counts = [0] * len(options)
        texts: List[Dict[str, Any]] = []
        for item in responses:
            choice = item.get("choice_index")
            if isinstance(choice, int) and 0 <= choice < len(counts):
                counts[choice] += 1
            elif str(item.get("text") or "").strip():
                texts.append({"nickname": item.get("nickname", ""), "text": item.get("text", "")})
        total = len(responses)
        answer_index = question.get("answer_index")
        correct_rate: Optional[float] = None
        if isinstance(answer_index, int) and 0 <= answer_index < len(counts) and total:
            correct_rate = round(counts[answer_index] / total, 4)
        return {
            "question_id": question_id,
            "total": total,
            "option_counts": counts,
            "answer_index": answer_index if isinstance(answer_index, int) else None,
            "correct_rate": correct_rate,
            "texts": texts[-30:],
        }

    def _touch_presence(self, session_id: str, nickname: str) -> None:
        self._student_presence.setdefault(session_id, {})[nickname] = time.time()

    def _presence_count(self, session_id: str, window_seconds: float = 90.0) -> int:
        bucket = self._student_presence.get(session_id, {})
        threshold = time.time() - window_seconds
        return sum(1 for last_seen in bucket.values() if last_seen >= threshold)

    def _generate_join_code(self) -> str:
        for _ in range(20):
            code = f"{secrets.randbelow(1000000):06d}"
            if self.store.find_session_by_join_code(code) is None:
                return code
        return f"{secrets.randbelow(100000000):08d}"

    def _student_join_url(self, join_code: str) -> str:
        base = os.getenv("WEBGIS_AI_PUBLIC_BASE_URL", "").strip().rstrip("/")
        if not base:
            base = f"http://{self._detect_lan_ip()}:{self.config.port}"
        return f"{base}/student/{join_code}"

    @staticmethod
    def _detect_lan_ip() -> str:
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.connect(("8.8.8.8", 80))
                return str(probe.getsockname()[0])
            finally:
                probe.close()
        except OSError:
            return "127.0.0.1"

    @staticmethod
    def _utc_now() -> str:
        from ..models import utc_now

        return utc_now()

    def _require_session(self, session_id: str):
        session = self.store.get_class_session(session_id)
        if not session:
            raise KeyError(f"Unknown class session: {session_id}")
        return session
