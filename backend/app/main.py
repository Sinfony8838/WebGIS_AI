from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .config import AppConfig
from .runtime import WebGISRuntime
from .services.ppt_renderer import PptRenderError, render_pptx_to_images


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
    assistant_mode: str = ""
    conversation_id: str = ""
    history: list[Dict[str, Any]] = Field(default_factory=list)
    target: str = "webgis"
    input_mode: str = "text"
    screen_snapshot: Dict[str, Any] = Field(default_factory=dict)


class AssistantConfirmRequest(BaseModel):
    confirmation_id: str
    decision: str = "approve"


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


class KnowledgeItemRequest(BaseModel):
    item: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeLayerRegisterRequest(BaseModel):
    project_id: str
    layer_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeMaterialLinkRequest(BaseModel):
    kb_item_id: str
    url: str
    title: str = ""
    description: str = ""
    material_type: str = "link"
    thumbnail_url: str = ""
    region_binding: Dict[str, Any] = Field(default_factory=dict)


class LessonResourceSetRequest(BaseModel):
    item: Dict[str, Any] = Field(default_factory=dict)


class LessonResourceSetPatchRequest(BaseModel):
    patch: Dict[str, Any] = Field(default_factory=dict)


class TeachingMapToggleRequest(BaseModel):
    visible: bool = True


class WorkflowSubmitRequest(BaseModel):
    project_id: str
    message: str = ""
    mode: str = "template"
    template_id: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health() -> Dict[str, Any]:
    return runtime.health()


@app.get("/llm/status")
def llm_status() -> Dict[str, Any]:
    return runtime.llm_status()


@app.get("/files/{file_path:path}")
def get_public_file(file_path: str) -> FileResponse:
    try:
        resolved = config.resolve_public_path(file_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(resolved)


@app.get("/teaching-maps")
def list_teaching_maps() -> Dict[str, Any]:
    return runtime.list_teaching_maps()


@app.post("/projects/{project_id}/teaching-maps/{map_id}/toggle")
def toggle_teaching_map(project_id: str, map_id: str, body: TeachingMapToggleRequest) -> Dict[str, Any]:
    try:
        return runtime.toggle_teaching_map(project_id, map_id, body.visible)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/projects/{project_id}/teaching-maps/active")
def get_active_teaching_maps(project_id: str) -> Dict[str, Any]:
    try:
        return runtime.get_active_teaching_maps(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/kb/manifest")
def get_kb_manifest() -> Dict[str, Any]:
    return runtime.kb_manifest()


@app.get("/kb/search")
def search_kb(
    query: str = Query(""),
    topic: str = Query(""),
    region: str = Query(""),
    tag: str = Query(""),
    limit: int = Query(20),
) -> Dict[str, Any]:
    return runtime.kb_search(query=query, topic=topic, region=region, tag=tag, limit=limit)


@app.get("/kb/topics")
def get_kb_topics() -> Dict[str, Any]:
    return runtime.kb_topics()


@app.post("/kb/items")
def upsert_kb_item(request: KnowledgeItemRequest) -> Dict[str, Any]:
    try:
        return runtime.kb_upsert_item(request.item)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/kb/layers/register")
def register_kb_layer(request: KnowledgeLayerRegisterRequest) -> Dict[str, Any]:
    try:
        return runtime.kb_register_layer(request.project_id, request.layer_id, request.metadata)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/kb/materials/upload")
async def upload_kb_material(
    kb_item_id: str = Form(...),
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    material_type: str = Form(""),
    region_binding: str = Form("{}"),
) -> Dict[str, Any]:
    try:
        raw_binding = json.loads(region_binding or "{}")
        if not isinstance(raw_binding, dict):
            raise ValueError("region_binding must be an object")
        raw = await file.read()
        return runtime.kb_upload_material(
            kb_item_id=kb_item_id,
            filename=file.filename or "material.dat",
            raw_bytes=raw,
            title=title,
            description=description,
            material_type=material_type,
            region_binding=raw_binding,
        )
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="region_binding must be valid JSON") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/kb/materials/link")
def link_kb_material(request: KnowledgeMaterialLinkRequest) -> Dict[str, Any]:
    try:
        return runtime.kb_link_material(
            kb_item_id=request.kb_item_id,
            url=request.url,
            title=request.title,
            description=request.description,
            material_type=request.material_type,
            thumbnail_url=request.thumbnail_url,
            region_binding=request.region_binding,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/resources/search")
def search_resources(
    query: str = Query(""),
    scope: str = Query("all"),
    limit: int = Query(12),
) -> Dict[str, Any]:
    return runtime.resource_search(query=query, scope=scope, limit=limit)


@app.get("/basemaps")
def list_basemaps() -> Dict[str, Any]:
    return runtime.list_basemaps()


@app.get("/tiles/weather/{layer}/{z}/{x}/{y}.png")
def get_weather_tile(layer: str, z: int, x: int, y: int) -> Response:
    try:
        content, content_type = runtime.fetch_weather_tile(layer, z, x, y)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=content, media_type=content_type, headers={"Cache-Control": "public, max-age=300"})


@app.get("/tiles/weather/{z}/{x}/{y}.png")
def get_default_weather_tile(z: int, x: int, y: int) -> Response:
    return get_weather_tile("precipitation_new", z, x, y)


@app.post("/projects")
def create_project(request: CreateProjectRequest) -> Dict[str, Any]:
    return runtime.create_project(name=request.name or None, metadata=request.metadata)


@app.get("/projects/{project_id}")
def get_project(project_id: str) -> Dict[str, Any]:
    try:
        return runtime.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/projects/{project_id}/lesson-resources")
def list_lesson_resources(project_id: str) -> Dict[str, Any]:
    try:
        return runtime.list_lesson_resources(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/projects/{project_id}/lesson-resources")
def save_lesson_resource_set(project_id: str, request: LessonResourceSetRequest) -> Dict[str, Any]:
    try:
        return runtime.save_lesson_resource_set(project_id, request.item)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/projects/{project_id}/lesson-resources/{set_id}")
def patch_lesson_resource_set(project_id: str, set_id: str, request: LessonResourceSetPatchRequest) -> Dict[str, Any]:
    try:
        return runtime.activate_lesson_resource_set(project_id, set_id, request.patch)
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
        return runtime.submit_assistant_message(
            request.project_id,
            request.message,
            request.map_context,
            request.assistant_mode,
            request.conversation_id,
            request.history,
            request.target,
            request.input_mode,
            request.screen_snapshot,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/assistant/confirm")
def confirm_assistant_action(request: AssistantConfirmRequest) -> Dict[str, Any]:
    try:
        return runtime.confirm_assistant_action(request.confirmation_id, decision=request.decision)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/assistant/conversations/{conversation_id}")
def get_assistant_conversation(conversation_id: str) -> Dict[str, Any]:
    try:
        return runtime.get_conversation(conversation_id)
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


@app.post("/ppt/render")
async def render_ppt(file: UploadFile = File(...)) -> Dict[str, Any]:
    try:
        raw = await file.read()
        return render_pptx_to_images(config, file.filename or "presentation.pptx", raw)
    except PptRenderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_dict()) from exc


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


# ---------------------------------------------------------------------------
# GIS workflow endpoints
# ---------------------------------------------------------------------------


@app.get("/workflow/templates")
def list_workflow_templates() -> Dict[str, Any]:
    return runtime.list_workflow_templates()


@app.post("/workflow/submit")
def submit_workflow(payload: WorkflowSubmitRequest) -> Dict[str, Any]:
    if not payload.project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    try:
        return runtime.submit_workflow(
            project_id=payload.project_id,
            message=payload.message,
            mode=payload.mode,
            template_id=payload.template_id,
            parameters=payload.parameters,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/workflow/history")
def workflow_history(project_id: Optional[str] = None) -> Dict[str, Any]:
    return runtime.list_workflows(project_id=project_id)


@app.get("/workflow/{workflow_id}")
def get_workflow(workflow_id: str) -> Dict[str, Any]:
    try:
        return runtime.get_workflow(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/workflow/{workflow_id}/artifacts")
def get_workflow_artifacts(workflow_id: str) -> Dict[str, Any]:
    try:
        return runtime.list_workflow_artifacts(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/workflow/{workflow_id}/stream")
def stream_workflow(workflow_id: str):
    def event_stream():
        for event in runtime.stream_workflow_events(workflow_id):
            event_type = str(event.get("type") or "message")
            data = json.dumps(event.get("payload") or {}, ensure_ascii=False)
            yield f"event: {event_type}\ndata: {data}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/workflow-files/{workflow_id}/{relative_path:path}")
def serve_workflow_file(workflow_id: str, relative_path: str):
    try:
        path = runtime.resolve_workflow_file(workflow_id, relative_path)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    media_type = None
    suffix = path.suffix.lower()
    if suffix == ".geojson":
        media_type = "application/geo+json"
    elif suffix == ".json":
        media_type = "application/json"
    elif suffix == ".png":
        media_type = "image/png"
    elif suffix == ".md":
        media_type = "text/markdown; charset=utf-8"
    return FileResponse(path, media_type=media_type)


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


class TimelinePatchRequest(BaseModel):
    patch: Dict[str, Any] = Field(default_factory=dict)


@app.post("/projects/{project_id}/timeline/generate")
async def generate_timeline(
    project_id: str,
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    try:
        raw = await file.read()
        return runtime.generate_timeline(
            project_id=project_id,
            filename=file.filename or "lesson.txt",
            raw_bytes=raw,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/{project_id}/timeline")
def get_timeline(project_id: str) -> Dict[str, Any]:
    try:
        return runtime.get_timeline(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/projects/{project_id}/timeline")
def update_timeline(project_id: str, request: TimelinePatchRequest) -> Dict[str, Any]:
    try:
        return runtime.update_timeline(project_id, request.patch)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
