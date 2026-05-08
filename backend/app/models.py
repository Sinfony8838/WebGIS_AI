from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


WORKFLOW_STAGE_KEYS = ("analysis", "actions", "map", "artifacts")
ASSISTANT_V2_STAGE_KEYS = ("routing", "retrieval", "planning", "confirmation", "execution", "grounding", "artifacts")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_workflow_stages(default_status: str = "pending") -> Dict[str, Dict[str, str]]:
    return {
        stage: {
            "status": default_status,
            "summary": "",
            "detail": "",
        }
        for stage in WORKFLOW_STAGE_KEYS
    }


def build_dynamic_stages(
    stage_keys: Optional[List[str]] = None,
    default_status: str = "pending",
) -> Dict[str, Dict[str, str]]:
    keys = stage_keys or list(WORKFLOW_STAGE_KEYS)
    return {
        stage: {
            "status": default_status,
            "summary": "",
            "detail": "",
        }
        for stage in keys
    }


def build_assistant_v2_stages(default_status: str = "pending") -> Dict[str, Dict[str, str]]:
    return build_dynamic_stages(list(ASSISTANT_V2_STAGE_KEYS), default_status=default_status)


@dataclass
class LayerRecord:
    layer_id: str
    name: str
    kind: str
    source: str
    geometry_type: str
    visible: bool = True
    opacity: float = 1.0
    z_index: int = 0
    style: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        name: str,
        kind: str,
        source: str,
        geometry_type: str,
        layer_id: str = "",
        visible: bool = True,
        opacity: float = 1.0,
        z_index: int = 0,
        style: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "LayerRecord":
        return cls(
            layer_id=layer_id or f"layer_{uuid4().hex}",
            name=name,
            kind=kind,
            source=source,
            geometry_type=geometry_type,
            visible=visible,
            opacity=opacity,
            z_index=z_index,
            style=style or {},
            data=data or {},
            metadata=metadata or {},
        )

    def touch(self) -> None:
        self.updated_at = utc_now()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ArtifactRecord:
    artifact_id: str
    project_id: str
    job_id: str
    artifact_type: str
    title: str
    path: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        project_id: str,
        job_id: str,
        artifact_type: str,
        title: str,
        path: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ArtifactRecord":
        return cls(
            artifact_id=f"artifact_{uuid4().hex}",
            project_id=project_id,
            job_id=job_id,
            artifact_type=artifact_type,
            title=title,
            path=path,
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MessageRecord:
    message_id: str
    conversation_id: str
    role: str
    text: str
    assistant_mode: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        conversation_id: str,
        role: str,
        text: str,
        assistant_mode: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "MessageRecord":
        return cls(
            message_id=f"msg_{uuid4().hex}",
            conversation_id=conversation_id,
            role=role,
            text=text,
            assistant_mode=assistant_mode,
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConversationRecord:
    conversation_id: str
    project_id: str
    assistant_mode: str
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    raw_messages: List[Dict[str, Any]] = field(default_factory=list)
    running_summary: str = ""
    task_memory: Dict[str, Any] = field(default_factory=dict)
    pinned_state: Dict[str, Any] = field(default_factory=dict)
    last_map_grounding: Dict[str, Any] = field(default_factory=dict)
    message_ids: List[str] = field(default_factory=list)

    @classmethod
    def create(cls, project_id: str, assistant_mode: str) -> "ConversationRecord":
        return cls(
            conversation_id=f"conv_{uuid4().hex}",
            project_id=project_id,
            assistant_mode=assistant_mode,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConfirmationRecord:
    confirmation_id: str
    project_id: str
    conversation_id: str
    job_id: str
    assistant_mode: str
    status: str = "pending"
    title: str = ""
    reason: str = ""
    plan_fingerprint: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    expires_at: str = ""
    resolved_at: str = ""

    @classmethod
    def create(
        cls,
        project_id: str,
        conversation_id: str,
        job_id: str,
        assistant_mode: str,
        title: str,
        reason: str,
        plan_fingerprint: str = "",
        payload: Optional[Dict[str, Any]] = None,
        expires_at: str = "",
    ) -> "ConfirmationRecord":
        return cls(
            confirmation_id=f"confirm_{uuid4().hex}",
            project_id=project_id,
            conversation_id=conversation_id,
            job_id=job_id,
            assistant_mode=assistant_mode,
            title=title,
            reason=reason,
            plan_fingerprint=plan_fingerprint,
            payload=payload or {},
            expires_at=expires_at,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JobRecord:
    job_id: str
    project_id: str
    job_type: str
    title: str
    workflow_type: str = ""
    status: str = "queued"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    request: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    artifact_ids: List[str] = field(default_factory=list)
    stages: Dict[str, Dict[str, str]] = field(default_factory=build_workflow_stages)

    @classmethod
    def create(
        cls,
        project_id: str,
        job_type: str,
        title: str,
        workflow_type: str = "",
        request: Optional[Dict[str, Any]] = None,
        stages: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> "JobRecord":
        return cls(
            job_id=f"job_{uuid4().hex}",
            project_id=project_id,
            job_type=job_type,
            title=title,
            workflow_type=workflow_type,
            request=request or {},
            stages=stages or build_workflow_stages(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# PyQGIS Workflow data models
# ---------------------------------------------------------------------------

WORKFLOW_STATUSES = ("pending", "running", "success", "error", "cancelled")
WORKFLOW_STEP_STATUSES = ("pending", "running", "success", "error", "skipped")


@dataclass
class WorkflowError:
    """Structured error returned by validators / workers / executor."""
    code: str = "INTERNAL_ERROR"
    message: str = ""
    user_friendly: str = ""
    step_id: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowStepResult:
    """Result of a single workflow step (sent FastAPI <-> worker)."""
    step_id: str
    status: str = "pending"
    started_at: str = ""
    finished_at: str = ""
    outputs: Dict[str, Any] = field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowArtifact:
    """A user-facing output of a workflow (geojson/style/stats/png/summary)."""
    artifact_id: str
    workflow_id: str
    kind: str       # geojson | style | stats | png | summary | layout_pdf | other
    title: str
    relative_path: str   # relative to the workflow dir
    public_url: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        workflow_id: str,
        kind: str,
        title: str,
        relative_path: str,
        public_url: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "WorkflowArtifact":
        return cls(
            artifact_id=f"wfa_{uuid4().hex}",
            workflow_id=workflow_id,
            kind=kind,
            title=title,
            relative_path=relative_path,
            public_url=public_url,
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowRecord:
    """Full state of a PyQGIS workflow run, persisted in RuntimeStore."""
    workflow_id: str
    project_id: str
    user_message: str = ""
    intent: str = ""
    template_id: str = ""
    mode: str = "template"  # template | freeform
    workflow_json: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    steps: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    started_at: str = ""
    finished_at: str = ""

    @classmethod
    def create(
        cls,
        project_id: str,
        user_message: str = "",
        intent: str = "",
        template_id: str = "",
        mode: str = "template",
        workflow_json: Optional[Dict[str, Any]] = None,
    ) -> "WorkflowRecord":
        return cls(
            workflow_id=f"wf_{uuid4().hex}",
            project_id=project_id,
            user_message=user_message,
            intent=intent,
            template_id=template_id,
            mode=mode,
            workflow_json=workflow_json or {},
        )

    def touch(self) -> None:
        self.updated_at = utc_now()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectRecord:
    project_id: str
    name: str
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    job_ids: List[str] = field(default_factory=list)
    artifact_ids: List[str] = field(default_factory=list)
    layers: List[LayerRecord] = field(default_factory=list)
    enabled_templates: List[str] = field(default_factory=list)
    recent_actions: List[Dict[str, Any]] = field(default_factory=list)
    active_layer_id: str = ""
    base_map: Dict[str, Any] = field(default_factory=dict)
    view: Dict[str, Any] = field(
        default_factory=lambda: {
            "center": [104.0, 35.0],
            "zoom": 4,
            "extent": [73.0, 18.0, 135.0, 54.0],
        }
    )

    @classmethod
    def create(
        cls,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        base_map: Optional[Dict[str, Any]] = None,
    ) -> "ProjectRecord":
        return cls(
            project_id=f"project_{uuid4().hex}",
            name=name or "WebGIS Classroom Project",
            metadata=metadata or {},
            base_map=base_map or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["layers"] = [layer.to_dict() for layer in self.layers]
        return payload
