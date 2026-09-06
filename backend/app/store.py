from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from uuid import uuid4

from .models import (
    ArtifactRecord,
    ClassSessionRecord,
    ConfirmationRecord,
    ConversationRecord,
    JobRecord,
    LayerRecord,
    LessonDesignRecord,
    LessonRecord,
    LessonRehearsalRecord,
    MessageRecord,
    ProjectRecord,
    WorkflowRecord,
    build_workflow_stages,
    utc_now,
)


LEGACY_REGION_LAYER_ID = "builtin_population_regions"
LEGACY_REGION_TEMPLATE_ID = "population_distribution"


class RuntimeStore:
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self._lock = threading.RLock()
        self.projects: Dict[str, ProjectRecord] = {}
        self.jobs: Dict[str, JobRecord] = {}
        self.artifacts: Dict[str, ArtifactRecord] = {}
        self.lessons: Dict[str, LessonRecord] = {}
        self.lesson_designs: Dict[str, LessonDesignRecord] = {}
        self.lesson_rehearsals: Dict[str, LessonRehearsalRecord] = {}
        self.class_sessions: Dict[str, ClassSessionRecord] = {}
        self.conversations: Dict[str, ConversationRecord] = {}
        self.messages: Dict[str, MessageRecord] = {}
        self.confirmations: Dict[str, ConfirmationRecord] = {}
        self.workflows: Dict[str, WorkflowRecord] = {}
        self._batch_depth = 0
        self._batch_dirty = False
        self._load()

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Coalesce every mutation inside the block into a single state-file
        write.  ``_save()`` rewrites the whole file, so multi-mutation flows
        (e.g. applying a lesson stage scene) should wrap their store calls."""
        with self._lock:
            self._batch_depth += 1
            try:
                yield
            finally:
                self._batch_depth -= 1
                if self._batch_depth == 0 and self._batch_dirty:
                    self._batch_dirty = False
                    self._write_state_file()

    def _load(self) -> None:
        if not self.state_file.exists():
            return
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Runtime state payload must be an object")

            self.projects = {}
            migrated_legacy_projects = False
            for project_id, data in payload.get("projects", {}).items():
                layers = [LayerRecord(**layer) for layer in data.pop("layers", [])]
                project = ProjectRecord(**data)
                project.layers = layers
                if self._remove_legacy_region_demo_layers(project):
                    migrated_legacy_projects = True
                self.projects[project_id] = project
            self.jobs = {job_id: JobRecord(**data) for job_id, data in payload.get("jobs", {}).items()}
            self.artifacts = {
                artifact_id: ArtifactRecord(**data) for artifact_id, data in payload.get("artifacts", {}).items()
            }
            self.lessons = {
                lesson_id: LessonRecord(**{**data, "plan": data.get("plan") or {}})
                for lesson_id, data in payload.get("lessons", {}).items()
            }
            self.lesson_designs = {
                design_id: LessonDesignRecord(**data)
                for design_id, data in payload.get("lesson_designs", {}).items()
            }
            self.lesson_rehearsals = {
                rehearsal_id: LessonRehearsalRecord(**data)
                for rehearsal_id, data in payload.get("lesson_rehearsals", {}).items()
            }
            self.class_sessions = {
                session_id: ClassSessionRecord(**data)
                for session_id, data in payload.get("class_sessions", {}).items()
            }
            self.conversations = {
                conversation_id: ConversationRecord(**self._normalize_conversation_payload(data))
                for conversation_id, data in payload.get("conversations", {}).items()
            }
            self.messages = {
                message_id: MessageRecord(**data) for message_id, data in payload.get("messages", {}).items()
            }
            self.confirmations = {
                confirmation_id: ConfirmationRecord(**data)
                for confirmation_id, data in payload.get("confirmations", {}).items()
            }
            self.workflows = {
                workflow_id: WorkflowRecord(**data)
                for workflow_id, data in payload.get("workflows", {}).items()
            }
            if migrated_legacy_projects:
                self._save()
        except json.JSONDecodeError:
            self._quarantine_corrupt_state("invalid_json")
            self.projects = {}
            self.jobs = {}
            self.artifacts = {}
            self.lessons = {}
            self.lesson_designs = {}
            self.lesson_rehearsals = {}
            self.class_sessions = {}
            self.conversations = {}
            self.messages = {}
            self.confirmations = {}
            self.workflows = {}
        except Exception:
            self._quarantine_corrupt_state("invalid_schema")
            self.projects = {}
            self.jobs = {}
            self.artifacts = {}
            self.lessons = {}
            self.lesson_designs = {}
            self.lesson_rehearsals = {}
            self.class_sessions = {}
            self.conversations = {}
            self.messages = {}
            self.confirmations = {}
            self.workflows = {}

    @staticmethod
    def _remove_legacy_region_demo_layers(project: ProjectRecord) -> bool:
        """Discard the retired rectangular seven-region demo when restoring.

        Projects created before the province-boundary population template was
        introduced serialized the old, synthetic rectangles into runtime.json.
        Leaving those layers in the saved project made them reappear in both
        2D and 3D views after a page refresh.  A visual-query result in the
        same old scene is transient as well, so it is cleared with the demo.
        """
        if not any(RuntimeStore._is_legacy_region_demo_layer(layer) for layer in project.layers):
            return False

        project.layers = [
            layer
            for layer in project.layers
            if not RuntimeStore._is_legacy_region_demo_layer(layer)
            and not layer.layer_id.startswith("visual_query_")
        ]
        project.enabled_templates = [
            template_id
            for template_id in project.enabled_templates
            if template_id != LEGACY_REGION_TEMPLATE_ID
        ]
        remaining_layer_ids = {layer.layer_id for layer in project.layers}
        if project.active_layer_id not in remaining_layer_ids:
            project.active_layer_id = ""
        return True

    @staticmethod
    def _is_legacy_region_demo_layer(layer: LayerRecord) -> bool:
        if layer.layer_id != LEGACY_REGION_LAYER_ID:
            return False
        features = (layer.data or {}).get("features")
        return bool(features) and all(RuntimeStore._is_axis_aligned_rectangle(feature) for feature in features)

    @staticmethod
    def _is_axis_aligned_rectangle(feature: Dict[str, Any]) -> bool:
        geometry = (feature or {}).get("geometry") or {}
        if geometry.get("type") != "Polygon":
            return False
        coordinates = geometry.get("coordinates") or []
        if len(coordinates) != 1:
            return False
        ring = coordinates[0]
        if not isinstance(ring, list) or len(ring) != 5 or ring[0] != ring[-1]:
            return False
        try:
            corners = {(float(point[0]), float(point[1])) for point in ring[:-1]}
        except (IndexError, TypeError, ValueError):
            return False
        if len(corners) != 4:
            return False
        x_values = {point[0] for point in corners}
        y_values = {point[1] for point in corners}
        return len(x_values) == 2 and len(y_values) == 2 and corners == {
            (x_value, y_value)
            for x_value in x_values
            for y_value in y_values
        }

    def _save(self) -> None:
        if self._batch_depth > 0:
            self._batch_dirty = True
            return
        self._write_state_file()

    def _write_state_file(self) -> None:
        """Persist the complete runtime state once.

        Keeping the actual file write separate from ``_save`` makes the batch
        contract testable: mutations may mark a batch dirty many times, but a
        completed classroom action still reaches disk exactly once.
        """
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "projects": {project_id: project.to_dict() for project_id, project in self.projects.items()},
            "jobs": {job_id: job.to_dict() for job_id, job in self.jobs.items()},
            "artifacts": {artifact_id: artifact.to_dict() for artifact_id, artifact in self.artifacts.items()},
            "lessons": {lesson_id: lesson.to_dict() for lesson_id, lesson in self.lessons.items()},
            "lesson_designs": {
                design_id: design.to_dict() for design_id, design in self.lesson_designs.items()
            },
            "lesson_rehearsals": {
                rehearsal_id: rehearsal.to_dict()
                for rehearsal_id, rehearsal in self.lesson_rehearsals.items()
            },
            "class_sessions": {
                session_id: session.to_dict()
                for session_id, session in self.class_sessions.items()
            },
            "conversations": {
                conversation_id: conversation.to_dict() for conversation_id, conversation in self.conversations.items()
            },
            "messages": {message_id: message.to_dict() for message_id, message in self.messages.items()},
            "confirmations": {
                confirmation_id: confirmation.to_dict()
                for confirmation_id, confirmation in self.confirmations.items()
            },
            "workflows": {
                workflow_id: workflow.to_dict()
                for workflow_id, workflow in self.workflows.items()
            },
        }
        # Runtime state can include large GeoJSON coordinate arrays.  Pretty
        # printing multiplies that hot-path payload and every mutation rewrites
        # the complete file, so retain readable Unicode but use compact JSON.
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        temp_path = self.state_file.with_suffix(f"{self.state_file.suffix}.{uuid4().hex}.tmp")
        try:
            temp_path.write_text(serialized, encoding="utf-8")
            last_error: Optional[Exception] = None
            for _ in range(3):
                try:
                    temp_path.replace(self.state_file)
                    last_error = None
                    break
                except PermissionError as exc:
                    last_error = exc
                    time.sleep(0.05)
            if last_error is not None:
                raise last_error
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _quarantine_corrupt_state(self, reason: str) -> None:
        if not self.state_file.exists():
            return
        backup_path = self.state_file.with_name(
            f"{self.state_file.stem}.corrupt_{reason}_{uuid4().hex}{self.state_file.suffix}"
        )
        try:
            self.state_file.replace(backup_path)
        except OSError:
            return

    def _normalize_conversation_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(payload or {})
        normalized.setdefault("raw_messages", [])
        normalized.setdefault("running_summary", "")
        normalized.setdefault("task_memory", {})
        normalized.setdefault("pinned_state", {})
        normalized.setdefault("last_map_grounding", {})
        normalized.setdefault("message_ids", [])
        normalized.setdefault("assistant_mode", "tool")
        normalized.setdefault("updated_at", normalized.get("created_at") or utc_now())
        return normalized

    def create_project(
        self,
        name: Optional[str] = None,
        owner_user_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        base_map: Optional[Dict[str, Any]] = None,
    ) -> ProjectRecord:
        with self._lock:
            project = ProjectRecord.create(
                name=name,
                owner_user_id=owner_user_id,
                metadata=metadata,
                base_map=base_map,
            )
            self.projects[project.project_id] = project
            self._save()
            return project

    def assign_unowned_records(self, owner_user_id: str) -> Dict[str, int]:
        """Idempotently attach legacy teacher-created records to bootstrap admin."""
        projects = 0
        lessons = 0
        with self.batch():
            for project in self.projects.values():
                if not project.owner_user_id:
                    project.owner_user_id = owner_user_id
                    project.updated_at = utc_now()
                    projects += 1
                    self._save()
            for lesson in self.lessons.values():
                if lesson.source != "builtin" and not lesson.owner_user_id:
                    lesson.owner_user_id = owner_user_id
                    lesson.touch()
                    lessons += 1
                    self._save()
        return {"projects": projects, "lessons": lessons}

    def get_project(self, project_id: str) -> Optional[ProjectRecord]:
        with self._lock:
            return self.projects.get(project_id)

    def create_conversation(self, project_id: str, assistant_mode: str) -> ConversationRecord:
        with self._lock:
            if project_id not in self.projects:
                raise KeyError(f"Unknown project: {project_id}")
            conversation = ConversationRecord.create(project_id=project_id, assistant_mode=assistant_mode)
            self.conversations[conversation.conversation_id] = conversation
            self._save()
            return conversation

    def get_conversation(self, conversation_id: str) -> Optional[ConversationRecord]:
        with self._lock:
            return self.conversations.get(conversation_id)

    def save_conversation(self, conversation: ConversationRecord) -> ConversationRecord:
        with self._lock:
            conversation.updated_at = utc_now()
            self.conversations[conversation.conversation_id] = conversation
            self._save()
            return conversation

    def append_conversation_message(
        self,
        conversation_id: str,
        role: str,
        text: str,
        assistant_mode: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MessageRecord:
        with self._lock:
            conversation = self.conversations[conversation_id]
            message = MessageRecord.create(
                conversation_id=conversation_id,
                role=role,
                text=text,
                assistant_mode=assistant_mode or conversation.assistant_mode,
                metadata=metadata,
            )
            self.messages[message.message_id] = message
            conversation.message_ids.append(message.message_id)
            conversation.raw_messages.append(message.to_dict())
            conversation.updated_at = utc_now()
            self._save()
            return message

    def list_conversation_messages(self, conversation_id: str) -> List[MessageRecord]:
        with self._lock:
            conversation = self.conversations.get(conversation_id)
            if not conversation:
                return []
            return [self.messages[message_id] for message_id in conversation.message_ids if message_id in self.messages]

    def create_confirmation(
        self,
        project_id: str,
        conversation_id: str,
        job_id: str,
        assistant_mode: str,
        title: str,
        reason: str,
        plan_fingerprint: str = "",
        payload: Optional[Dict[str, Any]] = None,
        expires_at: str = "",
    ) -> ConfirmationRecord:
        with self._lock:
            confirmation = ConfirmationRecord.create(
                project_id=project_id,
                conversation_id=conversation_id,
                job_id=job_id,
                assistant_mode=assistant_mode,
                title=title,
                reason=reason,
                plan_fingerprint=plan_fingerprint,
                payload=payload,
                expires_at=expires_at,
            )
            self.confirmations[confirmation.confirmation_id] = confirmation
            self._save()
            return confirmation

    def get_confirmation(self, confirmation_id: str) -> Optional[ConfirmationRecord]:
        with self._lock:
            return self.confirmations.get(confirmation_id)

    def resolve_confirmation(self, confirmation_id: str, status: str) -> ConfirmationRecord:
        with self._lock:
            confirmation = self.confirmations[confirmation_id]
            confirmation.status = status
            confirmation.updated_at = utc_now()
            confirmation.resolved_at = utc_now()
            self._save()
            return confirmation

    def save_project(self, project: ProjectRecord) -> ProjectRecord:
        with self._lock:
            project.updated_at = utc_now()
            self.projects[project.project_id] = project
            self._save()
            return project

    def upsert_layer(self, project_id: str, layer: LayerRecord) -> LayerRecord:
        with self._lock:
            project = self.projects[project_id]
            for index, existing in enumerate(project.layers):
                if existing.layer_id == layer.layer_id:
                    layer.created_at = existing.created_at
                    layer.data_rev = existing.data_rev + 1
                    layer.touch()
                    project.layers[index] = layer
                    project.updated_at = utc_now()
                    self._save()
                    return layer
            layer.touch()
            project.layers.append(layer)
            project.updated_at = utc_now()
            self._save()
            return layer

    def patch_layer(self, project_id: str, layer_id: str, patch: Dict[str, Any]) -> LayerRecord:
        with self._lock:
            project = self.projects[project_id]
            for layer in project.layers:
                if layer.layer_id != layer_id:
                    continue
                if "name" in patch and patch["name"]:
                    layer.name = str(patch["name"])
                if "visible" in patch:
                    layer.visible = bool(patch["visible"])
                if "opacity" in patch and patch["opacity"] is not None:
                    layer.opacity = max(0.0, min(1.0, float(patch["opacity"])))
                if "z_index" in patch and patch["z_index"] is not None:
                    layer.z_index = int(patch["z_index"])
                if "style" in patch and isinstance(patch["style"], dict):
                    layer.style = {**layer.style, **patch["style"]}
                if "metadata" in patch and isinstance(patch["metadata"], dict):
                    layer.metadata = {**layer.metadata, **patch["metadata"]}
                if "data" in patch and isinstance(patch["data"], dict):
                    layer.data = patch["data"]
                    layer.data_rev += 1
                layer.touch()
                if patch.get("active"):
                    project.active_layer_id = layer.layer_id
                project.updated_at = utc_now()
                self._save()
                return layer
            raise KeyError(f"Unknown layer: {layer_id}")

    def remove_layer(self, project_id: str, layer_id: str) -> bool:
        with self._lock:
            project = self.projects[project_id]
            remaining = [layer for layer in project.layers if layer.layer_id != layer_id]
            if len(remaining) == len(project.layers):
                return False
            project.layers = remaining
            if project.active_layer_id == layer_id:
                project.active_layer_id = ""
            project.updated_at = utc_now()
            self._save()
            return True

    def add_recent_action(
        self,
        project_id: str,
        title: str,
        detail: str,
        status: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            project = self.projects[project_id]
            project.recent_actions.append(
                {
                    "title": title,
                    "detail": detail,
                    "status": status,
                    "metadata": metadata or {},
                    "timestamp": utc_now(),
                }
            )
            project.recent_actions = project.recent_actions[-12:]
            project.updated_at = utc_now()
            self._save()

    def set_view(self, project_id: str, view_patch: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            project = self.projects[project_id]
            project.view = {**project.view, **(view_patch or {})}
            project.updated_at = utc_now()
            self._save()
            return project.view

    def set_basemap(self, project_id: str, base_map: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            project = self.projects[project_id]
            project.base_map = dict(base_map or {})
            project.updated_at = utc_now()
            self._save()
            return project.base_map

    def set_active_layer(self, project_id: str, layer_id: str) -> None:
        with self._lock:
            project = self.projects[project_id]
            project.active_layer_id = layer_id
            project.updated_at = utc_now()
            self._save()

    def enable_template(self, project_id: str, template_id: str) -> None:
        with self._lock:
            project = self.projects[project_id]
            if template_id not in project.enabled_templates:
                project.enabled_templates.append(template_id)
            project.updated_at = utc_now()
            self._save()

    def create_job(
        self,
        project_id: str,
        job_type: str,
        title: str,
        request: Optional[Dict[str, Any]] = None,
        workflow_type: str = "",
        stages: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> JobRecord:
        with self._lock:
            if project_id not in self.projects:
                raise KeyError(f"Unknown project: {project_id}")
            job = JobRecord.create(
                project_id=project_id,
                job_type=job_type,
                title=title,
                workflow_type=workflow_type,
                request=request,
                stages=stages or build_workflow_stages(),
            )
            self.jobs[job.job_id] = job
            project = self.projects[project_id]
            project.job_ids.append(job.job_id)
            project.updated_at = utc_now()
            self._save()
            return job

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            return self.jobs.get(job_id)

    def set_job_status(
        self,
        job_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: str = "",
    ) -> JobRecord:
        with self._lock:
            job = self.jobs[job_id]
            job.status = status
            job.updated_at = utc_now()
            if result is not None:
                job.result = result
            if error:
                job.error = error
            self._save()
            return job

    def append_job_step(self, job_id: str, title: str, detail: str, status: str = "info") -> JobRecord:
        with self._lock:
            job = self.jobs[job_id]
            job.steps.append(
                {
                    "title": title,
                    "detail": detail,
                    "status": status,
                    "timestamp": utc_now(),
                }
            )
            job.updated_at = utc_now()
            self._save()
            return job

    def update_job_stage(
        self,
        job_id: str,
        stage_name: str,
        status: str,
        summary: str = "",
        detail: str = "",
    ) -> JobRecord:
        with self._lock:
            job = self.jobs[job_id]
            if stage_name not in job.stages:
                job.stages[stage_name] = {"status": status, "summary": summary, "detail": detail}
            else:
                job.stages[stage_name]["status"] = status
                job.stages[stage_name]["summary"] = summary
                job.stages[stage_name]["detail"] = detail
            job.updated_at = utc_now()
            self._save()
            return job

    def register_artifact(
        self,
        project_id: str,
        job_id: str,
        artifact_type: str,
        title: str,
        path: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRecord:
        with self._lock:
            artifact = ArtifactRecord.create(
                project_id=project_id,
                job_id=job_id,
                artifact_type=artifact_type,
                title=title,
                path=path,
                metadata=metadata,
            )
            self.artifacts[artifact.artifact_id] = artifact
            self.jobs[job_id].artifact_ids.append(artifact.artifact_id)
            self.jobs[job_id].updated_at = utc_now()
            project = self.projects[project_id]
            project.artifact_ids.append(artifact.artifact_id)
            project.updated_at = utc_now()
            self._save()
            return artifact

    def get_artifact(self, artifact_id: str) -> Optional[ArtifactRecord]:
        with self._lock:
            return self.artifacts.get(artifact_id)

    def list_outputs(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            artifacts = list(self.artifacts.values())
            if project_id:
                artifacts = [artifact for artifact in artifacts if artifact.project_id == project_id]
            artifacts.sort(key=lambda artifact: artifact.created_at, reverse=True)
            return [artifact.to_dict() for artifact in artifacts]

    # ------------------------------------------------------------------
    # Lessons
    # ------------------------------------------------------------------

    def upsert_lesson(self, lesson: LessonRecord) -> LessonRecord:
        with self._lock:
            lesson.touch()
            self.lessons[lesson.lesson_id] = lesson
            self._save()
            return lesson

    def get_lesson(self, lesson_id: str) -> Optional[LessonRecord]:
        with self._lock:
            return self.lessons.get(lesson_id)

    def list_lessons(self) -> List[LessonRecord]:
        with self._lock:
            lessons = list(self.lessons.values())
            lessons.sort(key=lambda lesson: lesson.created_at)
            return lessons

    def delete_lesson(self, lesson_id: str) -> None:
        with self._lock:
            if lesson_id not in self.lessons:
                raise KeyError(f"Unknown lesson: {lesson_id}")
            del self.lessons[lesson_id]
            self._save()

    # ------------------------------------------------------------------
    # Lesson design sessions
    # ------------------------------------------------------------------

    def upsert_lesson_design(self, design: LessonDesignRecord) -> LessonDesignRecord:
        with self._lock:
            design.touch()
            self.lesson_designs[design.design_id] = design
            self._save()
            return design

    def get_lesson_design(self, design_id: str) -> Optional[LessonDesignRecord]:
        with self._lock:
            return self.lesson_designs.get(design_id)

    def list_lesson_designs(
        self,
        project_id: str = "",
        owner_user_id: str = "",
        active_only: bool = False,
    ) -> List[LessonDesignRecord]:
        with self._lock:
            designs = list(self.lesson_designs.values())
            if project_id:
                designs = [item for item in designs if item.project_id == project_id]
            if owner_user_id:
                designs = [item for item in designs if item.owner_user_id == owner_user_id]
            if active_only:
                designs = [item for item in designs if item.status == "active"]
            designs.sort(key=lambda item: item.updated_at, reverse=True)
            return designs


    # ------------------------------------------------------------------
    # Lesson rehearsals
    # ------------------------------------------------------------------

    def upsert_lesson_rehearsal(self, rehearsal: LessonRehearsalRecord) -> LessonRehearsalRecord:
        with self._lock:
            rehearsal.touch()
            self.lesson_rehearsals[rehearsal.rehearsal_id] = rehearsal
            self._save()
            return rehearsal

    def get_lesson_rehearsal(self, rehearsal_id: str) -> Optional[LessonRehearsalRecord]:
        with self._lock:
            return self.lesson_rehearsals.get(rehearsal_id)

    def list_lesson_rehearsals(
        self,
        project_id: str = "",
        lesson_id: str = "",
        owner_user_id: str = "",
        status: str = "",
    ) -> List[LessonRehearsalRecord]:
        with self._lock:
            items = list(self.lesson_rehearsals.values())
            if project_id:
                items = [item for item in items if item.project_id == project_id]
            if lesson_id:
                items = [item for item in items if item.lesson_id == lesson_id]
            if owner_user_id:
                items = [item for item in items if item.owner_user_id == owner_user_id]
            if status:
                items = [item for item in items if item.status == status]
            items.sort(key=lambda item: item.created_at, reverse=True)
            return items

    # ------------------------------------------------------------------
    # Class sessions
    # ------------------------------------------------------------------

    def create_class_session(
        self,
        lesson_id: str,
        project_id: str,
        join_code: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ClassSessionRecord:
        with self._lock:
            session = ClassSessionRecord.create(
                lesson_id=lesson_id,
                project_id=project_id,
                join_code=join_code,
                metadata=metadata,
            )
            self.class_sessions[session.session_id] = session
            self._save()
            return session

    def get_class_session(self, session_id: str) -> Optional[ClassSessionRecord]:
        with self._lock:
            return self.class_sessions.get(session_id)

    def list_class_sessions(
        self,
        lesson_id: Optional[str] = None,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[ClassSessionRecord]:
        with self._lock:
            sessions = list(self.class_sessions.values())
            if lesson_id:
                sessions = [session for session in sessions if session.lesson_id == lesson_id]
            if project_id:
                sessions = [session for session in sessions if session.project_id == project_id]
            if status:
                sessions = [session for session in sessions if session.status == status]
            sessions.sort(key=lambda session: session.started_at, reverse=True)
            return sessions

    def find_session_by_join_code(self, join_code: str) -> Optional[ClassSessionRecord]:
        with self._lock:
            code = (join_code or "").strip()
            if not code:
                return None
            for session in self.class_sessions.values():
                if session.join_code == code and session.status == "running":
                    return session
            return None

    def append_session_event(
        self,
        session_id: str,
        event_type: str,
        stage_id: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self.class_sessions[session_id]
            event = {
                "event_id": f"event_{uuid4().hex[:12]}",
                "type": event_type,
                "timestamp": utc_now(),
                "stage_id": stage_id or session.current_stage_id,
                "payload": payload or {},
            }
            session.events.append(event)
            session.touch()
            self._save()
            return event

    def set_session_stage(self, session_id: str, stage_id: str) -> ClassSessionRecord:
        with self._lock:
            session = self.class_sessions[session_id]
            session.current_stage_id = stage_id
            session.touch()
            self._save()
            return session

    def set_active_question(self, session_id: str, question: Dict[str, Any]) -> ClassSessionRecord:
        with self._lock:
            session = self.class_sessions[session_id]
            session.active_question = dict(question or {})
            session.touch()
            self._save()
            return session

    def add_student_response(
        self,
        session_id: str,
        question_id: str,
        response: Dict[str, Any],
    ) -> Dict[str, Any]:
        with self._lock:
            session = self.class_sessions[session_id]
            responses = session.responses.setdefault(question_id, [])
            nickname = str(response.get("nickname") or "").strip()
            if nickname:
                responses[:] = [item for item in responses if str(item.get("nickname") or "") != nickname]
            entry = {**response, "timestamp": utc_now()}
            responses.append(entry)
            session.touch()
            self._save()
            return entry

    def end_class_session(self, session_id: str) -> ClassSessionRecord:
        with self._lock:
            session = self.class_sessions[session_id]
            session.status = "ended"
            session.ended_at = utc_now()
            session.active_question = {}
            session.touch()
            self._save()
            return session

    # ------------------------------------------------------------------
    # Workflow records (backend GIS workflow main line)
    # ------------------------------------------------------------------

    def create_workflow(self, workflow: WorkflowRecord) -> WorkflowRecord:
        with self._lock:
            self.workflows[workflow.workflow_id] = workflow
            self._save()
            return workflow

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowRecord]:
        with self._lock:
            return self.workflows.get(workflow_id)

    def save_workflow(self, workflow: WorkflowRecord) -> WorkflowRecord:
        with self._lock:
            workflow.touch()
            self.workflows[workflow.workflow_id] = workflow
            self._save()
            return workflow

    def list_workflows(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self.workflows.values())
            if project_id:
                items = [w for w in items if w.project_id == project_id]
            items.sort(key=lambda w: w.created_at, reverse=True)
            return [w.to_dict() for w in items]
