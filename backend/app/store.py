from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .models import (
    ArtifactRecord,
    ConfirmationRecord,
    ConversationRecord,
    JobRecord,
    LayerRecord,
    MessageRecord,
    ProjectRecord,
    WorkflowRecord,
    build_workflow_stages,
    utc_now,
)


class RuntimeStore:
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self._lock = threading.RLock()
        self.projects: Dict[str, ProjectRecord] = {}
        self.jobs: Dict[str, JobRecord] = {}
        self.artifacts: Dict[str, ArtifactRecord] = {}
        self.conversations: Dict[str, ConversationRecord] = {}
        self.messages: Dict[str, MessageRecord] = {}
        self.confirmations: Dict[str, ConfirmationRecord] = {}
        self.workflows: Dict[str, WorkflowRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_file.exists():
            return
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Runtime state payload must be an object")

            self.projects = {}
            for project_id, data in payload.get("projects", {}).items():
                layers = [LayerRecord(**layer) for layer in data.pop("layers", [])]
                project = ProjectRecord(**data)
                project.layers = layers
                self.projects[project_id] = project
            self.jobs = {job_id: JobRecord(**data) for job_id, data in payload.get("jobs", {}).items()}
            self.artifacts = {
                artifact_id: ArtifactRecord(**data) for artifact_id, data in payload.get("artifacts", {}).items()
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
        except json.JSONDecodeError:
            self._quarantine_corrupt_state("invalid_json")
            self.projects = {}
            self.jobs = {}
            self.artifacts = {}
            self.conversations = {}
            self.messages = {}
            self.confirmations = {}
            self.workflows = {}
        except Exception:
            self._quarantine_corrupt_state("invalid_schema")
            self.projects = {}
            self.jobs = {}
            self.artifacts = {}
            self.conversations = {}
            self.messages = {}
            self.confirmations = {}
            self.workflows = {}

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "projects": {project_id: project.to_dict() for project_id, project in self.projects.items()},
            "jobs": {job_id: job.to_dict() for job_id, job in self.jobs.items()},
            "artifacts": {artifact_id: artifact.to_dict() for artifact_id, artifact in self.artifacts.items()},
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
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
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
        metadata: Optional[Dict[str, Any]] = None,
        base_map: Optional[Dict[str, Any]] = None,
    ) -> ProjectRecord:
        with self._lock:
            project = ProjectRecord.create(name=name, metadata=metadata, base_map=base_map)
            self.projects[project.project_id] = project
            self._save()
            return project

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
                layer.touch()
                if patch.get("active"):
                    project.active_layer_id = layer.layer_id
                project.updated_at = utc_now()
                self._save()
                return layer
            raise KeyError(f"Unknown layer: {layer_id}")

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
