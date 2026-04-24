from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


WORKFLOW_STAGE_KEYS = ("analysis", "actions", "map", "artifacts")


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

