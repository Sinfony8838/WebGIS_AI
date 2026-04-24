from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .models import ArtifactRecord, JobRecord, LayerRecord, ProjectRecord, build_workflow_stages, utc_now


class RuntimeStore:
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self._lock = threading.RLock()
        self.projects: Dict[str, ProjectRecord] = {}
        self.jobs: Dict[str, JobRecord] = {}
        self.artifacts: Dict[str, ArtifactRecord] = {}
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
        except json.JSONDecodeError:
            self._quarantine_corrupt_state("invalid_json")
            self.projects = {}
            self.jobs = {}
            self.artifacts = {}
        except Exception:
            self._quarantine_corrupt_state("invalid_schema")
            self.projects = {}
            self.jobs = {}
            self.artifacts = {}

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "projects": {project_id: project.to_dict() for project_id, project in self.projects.items()},
            "jobs": {job_id: job.to_dict() for job_id, job in self.jobs.items()},
            "artifacts": {artifact_id: artifact.to_dict() for artifact_id, artifact in self.artifacts.items()},
        }
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        temp_path = self.state_file.with_suffix(f"{self.state_file.suffix}.{uuid4().hex}.tmp")
        try:
            temp_path.write_text(serialized, encoding="utf-8")
            temp_path.replace(self.state_file)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

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
