from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import AppConfig
from .runtime import WebGISRuntime


config = AppConfig()
runtime = WebGISRuntime(config=config)

app = FastAPI(title="WebGIS-AI Runtime", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateProjectRequest(BaseModel):
    name: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LayerPatchRequest(BaseModel):
    project_id: str
    layer_id: str
    patch: Dict[str, Any] = Field(default_factory=dict)


class AssistantMessageRequest(BaseModel):
    project_id: str
    message: str
    map_context: Dict[str, Any] = Field(default_factory=dict)
    target: str = "webgis"


class TemplateRunRequest(BaseModel):
    project_id: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class SetBasemapRequest(BaseModel):
    basemap_id: str


class PoiSearchRequest(BaseModel):
    project_id: str
    keyword: str
    mode: str = "view"
    extent: list[float] = Field(default_factory=list)
    geometry: Dict[str, Any] = Field(default_factory=dict)


class ExportSnapshotRequest(BaseModel):
    project_id: str
    title: str = "课堂导图"
    image_data_url: str
    note: str = ""


class QgisToolRequest(BaseModel):
    tool_params: Dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health() -> Dict[str, Any]:
    return runtime.health()


@app.get("/llm/status")
def llm_status() -> Dict[str, Any]:
    return runtime.llm_status()


@app.get("/qgis/status")
def qgis_status() -> Dict[str, Any]:
    return runtime.qgis_status()


@app.get("/qgis/layers")
def qgis_layers() -> Dict[str, Any]:
    try:
        return runtime.qgis_layers()
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/qgis/tools/{tool_name}")
def run_qgis_tool(tool_name: str, request: QgisToolRequest) -> Dict[str, Any]:
    try:
        return runtime.qgis_execute_tool(tool_name, request.tool_params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/qgis/focus")
def focus_qgis() -> Dict[str, Any]:
    payload = runtime.qgis_focus()
    if payload.get("status") == "error":
        raise HTTPException(status_code=400, detail=payload.get("message") or "Failed to focus QGIS")
    return payload


@app.get("/qgis/preview")
def qgis_preview(file_path: str = Query(...)) -> FileResponse:
    requested = Path(file_path).expanduser()
    if not requested.is_absolute():
        raise HTTPException(status_code=400, detail="Preview path must be absolute")
    if requested.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="Unsupported preview file type")

    resolved = requested.resolve()
    allowed_roots = [config.outputs_dir.resolve(), Path("C:/Users/Public").resolve()]
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Preview path is outside allowed roots")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Preview file not found")
    return FileResponse(resolved)


@app.get("/files/{file_path:path}")
def get_public_file(file_path: str) -> FileResponse:
    try:
        resolved = config.resolve_public_path(file_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(resolved)


@app.get("/basemaps")
def list_basemaps() -> Dict[str, Any]:
    return runtime.list_basemaps()


@app.post("/projects")
def create_project(request: CreateProjectRequest) -> Dict[str, Any]:
    return runtime.create_project(name=request.name or None, metadata=request.metadata)


@app.get("/projects/{project_id}")
def get_project(project_id: str) -> Dict[str, Any]:
    try:
        return runtime.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/projects/{project_id}/basemap")
def patch_project_basemap(project_id: str, request: SetBasemapRequest) -> Dict[str, Any]:
    try:
        return runtime.set_basemap(project_id, request.basemap_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/layers")
def list_layers(project_id: str = Query(...)) -> Dict[str, Any]:
    try:
        return runtime.list_layers(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/layers")
def patch_layer(request: LayerPatchRequest) -> Dict[str, Any]:
    try:
        return runtime.patch_layer(request.project_id, request.layer_id, request.patch)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/assistant/messages")
def submit_assistant_message(request: AssistantMessageRequest) -> Dict[str, Any]:
    try:
        return runtime.submit_assistant_message(request.project_id, request.message, request.map_context, request.target)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/templates/{template_id}/run")
def run_template(template_id: str, request: TemplateRunRequest) -> Dict[str, Any]:
    try:
        return runtime.submit_template(request.project_id, template_id, request.payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/datasets/upload")
async def upload_dataset(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    dataset_name: str = Form(""),
    lat_field: str = Form(""),
    lon_field: str = Form(""),
    west: str = Form(""),
    south: str = Form(""),
    east: str = Form(""),
    north: str = Form(""),
) -> Dict[str, Any]:
    try:
        bounds = [float(value) for value in (west, south, east, north) if str(value).strip()]
        raw = await file.read()
        return runtime.upload_dataset(
            project_id=project_id,
            filename=file.filename or "upload.dat",
            raw_bytes=raw,
            dataset_name=dataset_name,
            lat_field=lat_field,
            lon_field=lon_field,
            image_bounds=bounds or None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/search/poi")
def search_poi(request: PoiSearchRequest) -> Dict[str, Any]:
    try:
        return runtime.search_poi(
            request.project_id,
            keyword=request.keyword,
            mode=request.mode,
            extent=request.extent,
            geometry=request.geometry,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/exports/snapshot")
def export_snapshot(request: ExportSnapshotRequest) -> Dict[str, Any]:
    try:
        return runtime.export_snapshot(
            request.project_id,
            title=request.title,
            image_data_url=request.image_data_url,
            note=request.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> Dict[str, Any]:
    try:
        return runtime.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/jobs/{job_id}/stream")
def stream_job(job_id: str):
    def event_stream():
        last_version: Optional[str] = None
        started = time.time()
        while time.time() - started < 180:
            try:
                payload = runtime.get_job(job_id)
            except KeyError:
                yield 'event: error\ndata: {"message":"job_not_found"}\n\n'
                return
            version = payload.get("updated_at", "")
            if version != last_version:
                yield f"event: job\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_version = version
            if payload.get("status") in {"completed", "failed"}:
                return
            time.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str) -> Dict[str, Any]:
    try:
        return runtime.get_artifact(artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/outputs")
def list_outputs(project_id: Optional[str] = None) -> Dict[str, Any]:
    return runtime.list_outputs(project_id=project_id)
