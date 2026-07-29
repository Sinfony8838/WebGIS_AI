from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .config import AppConfig
from .runtime import WebGISRuntime
from .services.student_page import render_student_page
from .services.ppt_renderer import PptRenderError, render_pptx_to_images


config = AppConfig()
runtime = WebGISRuntime(config=config)

app = FastAPI(title="WebGIS-AI Runtime", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins(),
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "X-WebGIS-AI-Token"],
)


def _extract_access_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    header_token = request.headers.get("X-WebGIS-AI-Token", "")
    if header_token.strip():
        return header_token.strip()
    return request.query_params.get("access_token", "").strip()


@app.middleware("http")
async def require_access_token(request: Request, call_next):
    if request.method == "OPTIONS" or not config.auth_enabled():
        return await call_next(request)
    if request.url.path in config.auth_exempt_path_set():
        return await call_next(request)

    supplied = _extract_access_token(request)
    if not supplied or not secrets.compare_digest(supplied, config.auth_token.strip()):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


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
    teaching_context: Dict[str, Any] = Field(default_factory=dict)


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


class CatalogLayerRequest(BaseModel):
    project_id: str
    dataset_id: str


class CatalogStatisticsRequest(BaseModel):
    project_id: str
    layer_id: str = ""
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


class LessonPayloadRequest(BaseModel):
    title: str = ""
    subject: str = "鍦扮悊"
    grade: str = ""
    objectives: list[str] = Field(default_factory=list)
    stages: list[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LessonImportRequest(BaseModel):
    project_id: str
    text: str


class PopulationSourceVersionRequest(BaseModel):
    version: str


class PopulationLessonPrepRequest(BaseModel):
    project_id: str
    lesson_id: str
    objective: str = ""
    grade: str = ""
    duration_minutes: Optional[int] = None
    region: str = "中国"
    years: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    source_version: str = ""


class PopulationChangeSetResolveRequest(BaseModel):
    decision: str = "apply"
    accepted_stage_ids: list[str] = Field(default_factory=list)


class SceneApplyRequest(BaseModel):
    project_id: str


class SceneCaptureRequest(BaseModel):
    snapshot: Dict[str, Any] = Field(default_factory=dict)


class ClassSessionCreateRequest(BaseModel):
    lesson_id: str
    project_id: str


class SessionStageRequest(BaseModel):
    stage_id: str


class QuestionLaunchRequest(BaseModel):
    stage_id: str = ""
    question_id: str = ""
    adhoc: Dict[str, Any] = Field(default_factory=dict)


class ObservationRequest(BaseModel):
    stage_id: str = ""
    question_id: str = ""
    verdict: str
    tag: str = ""
    note: str = ""


class SessionEventRequest(BaseModel):
    event_type: str
    stage_id: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)


class StudentAnswerRequest(BaseModel):
    nickname: str = ""
    question_id: str
    choice_index: Optional[int] = None
    text: str = ""


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


@app.get("/projects")
def list_projects() -> Dict[str, Any]:
    return runtime.list_projects()


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
            request.teaching_context,
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


@app.get("/datasets/catalog")
def list_dataset_catalog() -> Dict[str, Any]:
    return runtime.list_dataset_catalog()


@app.get("/datasets/catalog/{dataset_id}/data")
def get_dataset_catalog_data(dataset_id: str) -> Dict[str, Any]:
    try:
        return runtime.get_catalog_dataset_data(dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/datasets/catalog/layers")
def add_dataset_catalog_layer(request: CatalogLayerRequest) -> Dict[str, Any]:
    try:
        return runtime.add_catalog_dataset_layer(request.project_id, request.dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/datasets/catalog/statistics")
def summarize_dataset_catalog_layers(request: CatalogStatisticsRequest) -> Dict[str, Any]:
    try:
        return runtime.summarize_catalog_layers(
            request.project_id,
            geometry=request.geometry,
            layer_id=request.layer_id,
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


@app.get("/lessons")
def list_lessons() -> Dict[str, Any]:
    return runtime.classroom.list_lessons()


@app.get("/population-sources/versions")
def list_population_source_versions(project_id: str = Query("")) -> Dict[str, Any]:
    try:
        return runtime.list_population_source_versions(project_id=project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/population-sources/versions/compare")
def compare_population_source_versions(
    from_version: str = Query(...),
    to_version: str = Query(...),
) -> Dict[str, Any]:
    try:
        return runtime.compare_population_source_versions(from_version, to_version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/population-sources")
def list_population_sources(
    project_id: str = Query(""),
    version: str = Query(""),
) -> Dict[str, Any]:
    try:
        return runtime.list_population_sources(project_id=project_id, version=version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/population-sources/{source_id}")
def get_population_source(
    source_id: str,
    project_id: str = Query(""),
    version: str = Query(""),
    expected_fingerprint: str = Query(""),
) -> Dict[str, Any]:
    try:
        return runtime.get_population_source(
            source_id,
            project_id=project_id,
            version=version,
            expected_fingerprint=expected_fingerprint,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/{project_id}/population-source-version")
def activate_population_source_version(
    project_id: str,
    request: PopulationSourceVersionRequest,
) -> Dict[str, Any]:
    try:
        return runtime.activate_population_source_version(project_id, request.version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/lesson-prep/population")
def prepare_population_lesson(request: PopulationLessonPrepRequest) -> Dict[str, Any]:
    try:
        return runtime.classroom.submit_population_lesson_prep(request.project_id, request.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/lesson-prep/change-sets/{job_id}/resolve")
def resolve_population_lesson_change_set(
    job_id: str,
    request: PopulationChangeSetResolveRequest,
) -> Dict[str, Any]:
    try:
        return runtime.classroom.resolve_population_lesson_prep(
            job_id,
            request.decision,
            accepted_stage_ids=request.accepted_stage_ids,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/lessons")
def create_lesson(request: LessonPayloadRequest) -> Dict[str, Any]:
    return runtime.classroom.create_lesson(request.model_dump())


@app.get("/lessons/{lesson_id}")
def get_lesson(lesson_id: str) -> Dict[str, Any]:
    try:
        return runtime.classroom.get_lesson(lesson_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/lessons/{lesson_id}")
def update_lesson(lesson_id: str, request: LessonPayloadRequest) -> Dict[str, Any]:
    try:
        return runtime.classroom.update_lesson(lesson_id, request.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/lessons/{lesson_id}")
def delete_lesson(lesson_id: str) -> Dict[str, Any]:
    try:
        return runtime.classroom.delete_lesson(lesson_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/lessons/import")
def import_lesson(request: LessonImportRequest) -> Dict[str, Any]:
    try:
        return runtime.classroom.submit_lesson_import(request.project_id, request.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/lessons/{lesson_id}/stages/{stage_id}/scene/apply")
def apply_lesson_scene(lesson_id: str, stage_id: str, request: SceneApplyRequest) -> Dict[str, Any]:
    try:
        return runtime.classroom.apply_lesson_scene(request.project_id, lesson_id, stage_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/lessons/{lesson_id}/stages/{stage_id}/scene/capture")
def capture_lesson_scene(lesson_id: str, stage_id: str, request: SceneCaptureRequest) -> Dict[str, Any]:
    try:
        return runtime.classroom.capture_lesson_scene(lesson_id, stage_id, request.snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/class-sessions")
def create_class_session(request: ClassSessionCreateRequest) -> Dict[str, Any]:
    try:
        return runtime.classroom.create_class_session(request.lesson_id, request.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/class-sessions")
def list_class_sessions(lesson_id: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    return runtime.classroom.list_class_sessions(lesson_id=lesson_id, project_id=project_id)


@app.get("/class-sessions/{session_id}")
def get_class_session(session_id: str) -> Dict[str, Any]:
    try:
        return runtime.classroom.get_class_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/end")
def end_class_session(session_id: str) -> Dict[str, Any]:
    try:
        return runtime.classroom.end_class_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/stage")
def enter_session_stage(session_id: str, request: SessionStageRequest) -> Dict[str, Any]:
    try:
        return runtime.classroom.enter_session_stage(session_id, request.stage_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/questions/launch")
def launch_session_question(session_id: str, request: QuestionLaunchRequest) -> Dict[str, Any]:
    try:
        return runtime.classroom.launch_session_question(
            session_id,
            stage_id=request.stage_id,
            question_id=request.question_id,
            adhoc=request.adhoc,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/questions/close")
def close_session_question(session_id: str) -> Dict[str, Any]:
    try:
        return runtime.classroom.close_session_question(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/observations")
def add_session_observation(session_id: str, request: ObservationRequest) -> Dict[str, Any]:
    try:
        return runtime.classroom.add_session_observation(session_id, request.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/events")
def log_session_event(session_id: str, request: SessionEventRequest) -> Dict[str, Any]:
    try:
        return runtime.classroom.log_session_event(
            session_id,
            event_type=request.event_type,
            stage_id=request.stage_id,
            payload=request.payload,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/report")
def generate_session_report(session_id: str) -> Dict[str, Any]:
    try:
        return runtime.classroom.submit_session_report(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/class-sessions/{session_id}/live")
def session_live(session_id: str) -> Dict[str, Any]:
    try:
        return runtime.classroom.session_live(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/student/{join_code}", response_class=HTMLResponse)
def student_page(join_code: str) -> HTMLResponse:
    return HTMLResponse(render_student_page(join_code))


@app.get("/api/student/{join_code}/state")
def student_state(join_code: str, nickname: str = "") -> Dict[str, Any]:
    try:
        return runtime.classroom.student_state(join_code, nickname=nickname)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/student/{join_code}/answers")
def student_answer(join_code: str, request: StudentAnswerRequest) -> Dict[str, Any]:
    try:
        return runtime.classroom.student_answer(join_code, request.model_dump())
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
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"LLM 服务不可用: {exc}") from exc


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
