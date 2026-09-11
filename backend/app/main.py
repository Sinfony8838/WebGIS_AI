from __future__ import annotations

import asyncio
import json
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .config import AppConfig
from .runtime import WebGISRuntime
from .services.minimax_image_client import MiniMaxImageError
from .services.ppt_renderer import PptRenderError, render_pptx_to_images
from .services.auth import AuthContext, AuthError, AuthService


config = AppConfig()
runtime = WebGISRuntime(config=config)
auth_service = (
    AuthService(
        config.auth_db_path,
        idle_minutes=config.session_idle_minutes,
        max_hours=config.session_max_hours,
    )
    if config.auth_mode == "users"
    else None
)

LESSON_DESIGN_REQUEST_HINTS = (
    "共创教案", "教案共创", "备一节课", "生成整节教案", "设计整节课", "规划整节课", "完整课时",
    "逐步设计教案", "教案助手", "完整教案",
)

app = FastAPI(title="WebGIS-AI Runtime", version="1.1.0")


SESSION_COOKIE = "webgis_ai_session"
PUBLIC_AUTH_PATHS = {
    "/health",
    "/auth/bootstrap-status",
    "/auth/bootstrap",
    "/auth/login",
    "/auth/register",
}
REGISTRATION_MAX_BODY_BYTES = 8192
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _extract_access_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    header_token = request.headers.get("X-WebGIS-AI-Token", "")
    if header_token.strip():
        return header_token.strip()
    return request.query_params.get("access_token", "").strip()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _registration_client_ip(request: Request) -> str:
    # CF-Connecting-IP is only honored when the deployment explicitly opts in;
    # the header is trivially forgeable everywhere else.
    if config.trust_proxy_headers:
        forwarded = request.headers.get("CF-Connecting-IP", "").strip()
        if forwarded:
            return forwarded.split(",")[0].strip()[:128]
    return _client_ip(request)


def _local_user() -> Dict[str, Any]:
    return {
        "user_id": "local_admin",
        "email": "local@localhost.invalid",
        "nickname": "本机管理员",
        "role": "admin",
        "status": "active",
        "must_change_password": False,
    }


def _auth_error_response(error: AuthError) -> JSONResponse:
    return JSONResponse({"detail": error.detail()}, status_code=error.status_code)


@app.middleware("http")
async def require_access_token(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    if config.auth_mode == "disabled":
        request.state.auth = AuthContext(
            user=_local_user(),
            session_id="",
            csrf_hash="",
        )
        return await call_next(request)

    if config.auth_mode == "legacy_token":
        if request.url.path in config.auth_exempt_path_set():
            return await call_next(request)
        supplied = _extract_access_token(request)
        if not supplied or not secrets.compare_digest(supplied, config.auth_token.strip()):
            return JSONResponse(
                {"detail": {"code": "AUTH_REQUIRED", "message": "请先登录。"}},
                status_code=401,
            )
        request.state.auth = AuthContext(
            user=_local_user(),
            session_id="",
            csrf_hash="",
        )
        return await call_next(request)

    if request.url.path in PUBLIC_AUTH_PATHS:
        return await call_next(request)

    service = auth_service
    if service is None:
        return JSONResponse(
            {"detail": {"code": "AUTH_UNAVAILABLE", "message": "鉴权服务未初始化。"}},
            status_code=503,
        )

    context = service.authenticate(request.cookies.get(SESSION_COOKIE, ""))
    if context is None:
        return JSONResponse(
            {"detail": {"code": "AUTH_REQUIRED", "message": "登录已失效，请重新登录。"}},
            status_code=401,
        )
    request.state.auth = context

    if context.user.get("must_change_password") and request.url.path not in {
        "/auth/me",
        "/auth/change-password",
        "/auth/logout",
        "/auth/logout-all",
    }:
        return JSONResponse(
            {
                "detail": {
                    "code": "PASSWORD_CHANGE_REQUIRED",
                    "message": "请先修改临时密码。",
                }
            },
            status_code=403,
        )

    if request.method not in SAFE_METHODS:
        origin = request.headers.get("Origin", "").rstrip("/")
        if origin and origin not in {item.rstrip("/") for item in config.cors_origins()}:
            return JSONResponse(
                {"detail": {"code": "ORIGIN_REJECTED", "message": "请求来源不受信任。"}},
                status_code=403,
            )
        if not service.verify_csrf(context, request.headers.get("X-WebGIS-CSRF", "")):
            return JSONResponse(
                {"detail": {"code": "CSRF_FAILED", "message": "安全令牌失效，请刷新页面。"}},
                status_code=403,
            )
    return await call_next(request)


# Wrap authentication too, so allowed browser origins can read 401/403 errors.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins(),
    allow_methods=["*"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-WebGIS-AI-Token",
        "X-WebGIS-CSRF",
        "X-WebGIS-Bootstrap-Key",
    ],
    allow_credentials=True,
)


def _current_auth(request: Request) -> AuthContext:
    context = getattr(request.state, "auth", None)
    if context is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_REQUIRED", "message": "请先登录。"},
        )
    return context


def _require_admin(request: Request) -> AuthContext:
    context = _current_auth(request)
    if context.user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN", "message": "需要管理员权限。"},
        )
    return context


def _require_project_access(request: Request, project_id: str) -> Any:
    project = runtime.store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Unknown project")
    context = _current_auth(request)
    if context.user.get("role") != "admin" and project.owner_user_id != context.user.get("user_id"):
        raise HTTPException(status_code=404, detail="Unknown project")
    return project


def _require_lesson_design_access(request: Request, design_id: str) -> Any:
    design = runtime.store.get_lesson_design(design_id)
    if design is None:
        raise HTTPException(status_code=404, detail="Unknown lesson design")
    _require_project_access(request, design.project_id)
    context = _current_auth(request)
    if context.user.get("role") != "admin" and design.owner_user_id != context.user.get("user_id"):
        raise HTTPException(status_code=404, detail="Unknown lesson design")
    return design


def _require_lesson_access(request: Request, lesson_id: str) -> Any:
    lesson = runtime.store.get_lesson(lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Unknown lesson")
    context = _current_auth(request)
    if (
        lesson.source != "builtin"
        and context.user.get("role") != "admin"
        and lesson.owner_user_id != context.user.get("user_id")
    ):
        raise HTTPException(status_code=404, detail="Unknown lesson")
    return lesson


def _require_job_access(request: Request, job_id: str) -> Any:
    job = runtime.store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    _require_project_access(request, job.project_id)
    return job


def _require_workflow_access(request: Request, workflow_id: str) -> Any:
    workflow = runtime.store.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Unknown workflow")
    _require_project_access(request, workflow.project_id)
    return workflow


def _require_artifact_access(request: Request, artifact_id: str) -> Any:
    artifact = runtime.store.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Unknown artifact")
    _require_project_access(request, artifact.project_id)
    return artifact


def _require_session_access(request: Request, session_id: str) -> Any:
    session = runtime.store.get_class_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown class session")
    _require_project_access(request, session.project_id)
    return session


def _require_conversation_access(request: Request, conversation_id: str) -> Any:
    conversation = runtime.store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Unknown conversation")
    _require_project_access(request, conversation.project_id)
    return conversation


def _require_confirmation_access(request: Request, confirmation_id: str) -> Any:
    confirmation = runtime.store.get_confirmation(confirmation_id)
    if confirmation is None:
        raise HTTPException(status_code=404, detail="Unknown confirmation")
    _require_project_access(request, confirmation.project_id)
    return confirmation


def _session_cookie(response: Response, session_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=max(3600, config.session_max_hours * 3600),
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
    )


def _grant_response_files(request: Request, payload: Any) -> None:
    if auth_service is None:
        return
    context = _current_auth(request)
    user_id = str(context.user.get("user_id") or "")
    if not user_id:
        return

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)
        elif isinstance(value, str) and value.startswith("/files/"):
            try:
                auth_service.grant_file(user_id, config.resolve_public_path(value[len("/files/"):]))
            except (AuthError, ValueError):
                pass

    visit(payload)


class CreateProjectRequest(BaseModel):
    name: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AuthBootstrapRequest(BaseModel):
    email: str
    nickname: str = ""
    password: str


class AuthLoginRequest(BaseModel):
    email: str
    password: str


class AuthRegisterRequest(BaseModel):
    email: str = Field(max_length=254)
    nickname: str = Field(default="", max_length=80)
    organization: str = Field(default="", max_length=120)
    application_note: str = Field(default="", max_length=300)
    password: str = Field(max_length=128)


class AdminRegistrationReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class AdminUserCreateRequest(BaseModel):
    email: str
    nickname: str = ""
    role: str = "teacher"


class AdminUserPatchRequest(BaseModel):
    nickname: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None


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
    image_attachments: list[Dict[str, Any]] = Field(default_factory=list)


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
    preserve_view: bool = False


class CatalogStatisticsRequest(BaseModel):
    project_id: str
    layer_id: str = ""
    geometry: Dict[str, Any] = Field(default_factory=dict)


class ExportSnapshotRequest(BaseModel):
    project_id: str
    title: str = "课堂导图"
    image_data_url: str
    note: str = ""


class ImageGenerationRequest(BaseModel):
    project_id: str
    prompt: str
    title: str = ""
    model: str = ""
    aspect_ratio: str = "16:9"
    prompt_optimizer: bool = True
    confirmed: bool = False


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


class ArtifactLoadLayerRequest(BaseModel):
    project_id: str


class ResourceSaveRequest(BaseModel):
    project_id: str
    title: str = ""
    url: str
    summary: str = ""
    source: str = ""
    type: str = ""
    thumbnail_url: str = ""


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
    plan: Dict[str, Any] = Field(default_factory=dict)


class LessonDesignCreateRequest(BaseModel):
    project_id: str
    base_lesson_id: str = ""
    requirements: Dict[str, Any] = Field(default_factory=dict)


class LessonDesignTurnRequest(BaseModel):
    message: str
    step: str = ""
    expected_revision: Optional[int] = None


class LessonDesignResolveRequest(BaseModel):
    decision: str = "accept"
    teacher_note: str = ""
    value: Any = None
    expected_revision: Optional[int] = None


class LessonDesignFinalizeRequest(BaseModel):
    expected_revision: Optional[int] = None
    apply_base: bool = False


class LessonRehearsalCreateRequest(BaseModel):
    project_id: str
    lesson_id: str


class LessonRehearsalUpdateRequest(BaseModel):
    patch: Optional[Dict[str, Any]] = None
    question_bind: Optional[Dict[str, Any]] = None
    question_remove: Optional[Dict[str, Any]] = None
    image_bind: Optional[Dict[str, Any]] = None
    scene_capture: Optional[Dict[str, Any]] = None
    test_result: Optional[Dict[str, Any]] = None
    expected_revision: int = Field(ge=0)


class LessonRehearsalCompleteRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class LessonRehearsalStageRequest(BaseModel):
    stage_id: str


class LessonDocxExportRequest(BaseModel):
    project_id: str = ""
    design_id: str = ""


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


class SessionPresentationRequest(BaseModel):
    stage_id: str
    target: str = "stage"


class QuestionLaunchRequest(BaseModel):
    stage_id: str = ""
    question_id: str = ""
    adhoc: Dict[str, Any] = Field(default_factory=dict)
    delivery: str = "student"


class QuestionTimerRequest(BaseModel):
    action: str


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


class QuestionBankSearchRequest(BaseModel):
    project_id: str
    bank_ids: list[str] = Field(default_factory=list)
    topic: str = ""
    knowledge: str = ""
    objectives: list[str] = Field(default_factory=list)
    type: str = ""
    exclude_ids: list[str] = Field(default_factory=list)
    limit: int = 5


class LessonDesignQuestionBindRequest(BaseModel):
    stage_id: str
    question_id: str = ""
    manual: Dict[str, Any] = Field(default_factory=dict)
    action: str = "add"
    position: Optional[int] = None
    expected_revision: Optional[int] = None


@app.get("/health")
def health() -> Dict[str, Any]:
    return runtime.health()


@app.get("/auth/bootstrap-status")
def auth_bootstrap_status() -> Dict[str, Any]:
    if config.auth_mode != "users" or auth_service is None:
        return {
            "status": "success",
            "auth_mode": config.auth_mode,
            "registration_mode": "closed",
            "required": False,
        }
    return {
        "status": "success",
        "auth_mode": "users",
        "registration_mode": config.registration_mode,
        "required": not auth_service.has_users(),
    }


@app.post("/auth/register")
def auth_register(request: Request, payload: AuthRegisterRequest) -> Response:
    """Public self-registration endpoint.

    Answers duplicate emails and internal failures with the same stable
    response as a fresh submission so the endpoint cannot be used to probe
    accounts; the real reason is only in the admin-visible audit log.
    Never creates a session or sets a cookie, in any mode.
    """
    if config.auth_mode != "users" or auth_service is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "AUTH_MODE_DISABLED", "message": "当前未启用用户模式。"},
        )
    if config.registration_mode == "closed":
        raise HTTPException(
            status_code=403,
            detail={"code": "REGISTRATION_CLOSED", "message": "当前未开放注册。"},
        )
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(
            status_code=415,
            detail={"code": "UNSUPPORTED_MEDIA_TYPE", "message": "请求内容类型不受支持。"},
        )
    try:
        content_length = int(request.headers.get("content-length") or 0)
    except ValueError:
        content_length = 0
    if content_length > REGISTRATION_MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "PAYLOAD_TOO_LARGE", "message": "请求内容过大。"},
        )
    client_ip = _registration_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")
    try:
        if config.registration_mode == "open":
            outcome = auth_service.register_open(
                payload.email,
                payload.nickname,
                payload.password,
                organization=payload.organization,
                application_note=payload.application_note,
                ip_address=client_ip,
                user_agent=user_agent,
            )
            message = "注册完成，请使用新账号登录。"
            status = "created"
        else:
            outcome = auth_service.submit_registration(
                payload.email,
                payload.nickname,
                payload.password,
                organization=payload.organization,
                application_note=payload.application_note,
                ip_address=client_ip,
                user_agent=user_agent,
            )
            message = "注册申请已提交，管理员审核通过后方可登录。"
            status = "submitted"
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    # Same body for fresh submissions and duplicates: the specific outcome is
    # recorded in the audit log, never on the public wire.
    return JSONResponse({"status": status, "message": message})


@app.post("/auth/bootstrap")
def auth_bootstrap(request: Request, payload: AuthBootstrapRequest) -> Response:
    if config.auth_mode != "users" or auth_service is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "AUTH_MODE_DISABLED", "message": "当前未启用用户模式。"},
        )
    client_ip = _client_ip(request)
    local = client_ip in {"127.0.0.1", "::1", "localhost", "testclient"}
    supplied_key = request.headers.get("X-WebGIS-Bootstrap-Key", "")
    key_ok = bool(config.bootstrap_key) and secrets.compare_digest(
        supplied_key,
        config.bootstrap_key,
    )
    if not local and not key_ok:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "BOOTSTRAP_FORBIDDEN",
                "message": "远程初始化需要启动密钥。",
            },
        )
    try:
        result = auth_service.bootstrap(
            payload.email,
            payload.nickname,
            payload.password,
            ip_address=client_ip,
            user_agent=request.headers.get("User-Agent", ""),
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    try:
        migration = runtime.store.assign_unowned_records(result["user"]["user_id"])
    except Exception as exc:
        migration = {
            "projects": 0,
            "lessons": 0,
            "pending": True,
            "message": f"Legacy ownership migration will be retried: {exc}",
        }
    response = JSONResponse(
        {
            "status": "success",
            "user": result["user"],
            "csrf_token": result["csrf_token"],
            "expires_at": result["expires_at"],
            "migration": migration,
        }
    )
    _session_cookie(response, result["session_token"])
    return response


@app.post("/auth/login")
def auth_login(request: Request, payload: AuthLoginRequest) -> Response:
    if config.auth_mode != "users" or auth_service is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "AUTH_MODE_DISABLED", "message": "当前未启用用户模式。"},
        )
    try:
        result = auth_service.login(
            payload.email,
            payload.password,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("User-Agent", ""),
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    try:
        migration = runtime.store.assign_unowned_records(
            auth_service.bootstrap_owner_user_id()
        )
    except Exception:
        migration = {"projects": 0, "lessons": 0, "pending": True}
    response = JSONResponse(
        {
            "status": "success",
            "user": result["user"],
            "csrf_token": result["csrf_token"],
            "expires_at": result["expires_at"],
            "migration": migration,
        }
    )
    _session_cookie(response, result["session_token"])
    return response


@app.get("/auth/me")
def auth_me(request: Request) -> Dict[str, Any]:
    context = _current_auth(request)
    csrf_token = auth_service.csrf_for_session(context) if auth_service and context.session_id else ""
    if auth_service:
        try:
            runtime.store.assign_unowned_records(auth_service.bootstrap_owner_user_id())
        except Exception:
            pass
    return {
        "status": "success",
        "user": context.user,
        "csrf_token": csrf_token,
    }


@app.post("/auth/logout")
def auth_logout(request: Request) -> Response:
    context = _current_auth(request)
    if auth_service and context.session_id:
        auth_service.logout(
            context.session_id,
            actor_user_id=str(context.user["user_id"]),
            ip_address=_client_ip(request),
        )
    response = JSONResponse({"status": "success"})
    _clear_session_cookie(response)
    return response


@app.post("/auth/logout-all")
def auth_logout_all(request: Request) -> Response:
    context = _current_auth(request)
    if auth_service:
        auth_service.revoke_user_sessions(
            str(context.user["user_id"]),
            actor_user_id=str(context.user["user_id"]),
            action="logout_all",
            ip_address=_client_ip(request),
        )
    response = JSONResponse({"status": "success"})
    _clear_session_cookie(response)
    return response


@app.post("/auth/change-password")
def auth_change_password(request: Request, payload: PasswordChangeRequest) -> Dict[str, Any]:
    context = _current_auth(request)
    if auth_service is None:
        raise HTTPException(status_code=409, detail="Password management is unavailable")
    try:
        user = auth_service.change_password(
            str(context.user["user_id"]),
            payload.current_password,
            payload.new_password,
            current_session_id=context.session_id,
            ip_address=_client_ip(request),
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    return {"status": "success", "user": user}


@app.get("/admin/users")
def admin_list_users(
    request: Request,
    query: str = "",
    role: str = "",
    status: str = "",
) -> Dict[str, Any]:
    _require_admin(request)
    if auth_service is None:
        return {"status": "success", "items": []}
    return {
        "status": "success",
        "items": auth_service.list_users(query=query, role=role, status=status),
    }


@app.post("/admin/users")
def admin_create_user(request: Request, payload: AdminUserCreateRequest) -> Dict[str, Any]:
    context = _require_admin(request)
    if auth_service is None:
        raise HTTPException(status_code=409, detail="User management is unavailable")
    try:
        result = auth_service.create_user(
            actor_user_id=str(context.user["user_id"]),
            email=payload.email,
            nickname=payload.nickname,
            role=payload.role,
            ip_address=_client_ip(request),
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    return {"status": "success", **result}


@app.patch("/admin/users/{user_id}")
def admin_update_user(
    user_id: str,
    request: Request,
    payload: AdminUserPatchRequest,
) -> Dict[str, Any]:
    context = _require_admin(request)
    if auth_service is None:
        raise HTTPException(status_code=409, detail="User management is unavailable")
    patch = {key: value for key, value in payload.model_dump().items() if value is not None}
    try:
        user = auth_service.update_user(
            user_id,
            patch,
            actor_user_id=str(context.user["user_id"]),
            ip_address=_client_ip(request),
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    return {"status": "success", "user": user}


@app.get("/admin/registration-requests")
def admin_registration_requests(
    request: Request,
    status: str = "",
    query: str = "",
) -> Dict[str, Any]:
    _require_admin(request)
    if auth_service is None:
        return {"status": "success", "items": [], "pending_count": 0}
    return {
        "status": "success",
        "items": auth_service.list_registration_requests(query=query, status=status),
        "pending_count": auth_service.count_pending_registration_requests(),
    }


@app.post("/admin/registration-requests/{request_id}/review")
def admin_review_registration_request(
    request_id: str,
    request: Request,
    payload: AdminRegistrationReviewRequest,
) -> Dict[str, Any]:
    context = _require_admin(request)
    if auth_service is None:
        raise HTTPException(status_code=409, detail="User management is unavailable")
    try:
        reviewed = auth_service.review_registration_request(
            request_id,
            payload.decision,
            actor_user_id=str(context.user["user_id"]),
            ip_address=_client_ip(request),
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    return {"status": "success", "request": reviewed}


@app.post("/admin/users/{user_id}/reset-password")
def admin_reset_password(user_id: str, request: Request) -> Dict[str, Any]:
    context = _require_admin(request)
    if auth_service is None:
        raise HTTPException(status_code=409, detail="User management is unavailable")
    try:
        result = auth_service.reset_password(
            user_id,
            actor_user_id=str(context.user["user_id"]),
            ip_address=_client_ip(request),
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    return {"status": "success", **result}


@app.post("/admin/users/{user_id}/revoke-sessions")
def admin_revoke_sessions(user_id: str, request: Request) -> Dict[str, Any]:
    context = _require_admin(request)
    if auth_service is None:
        raise HTTPException(status_code=409, detail="User management is unavailable")
    try:
        auth_service.get_user(user_id)
        count = auth_service.revoke_user_sessions(
            user_id,
            actor_user_id=str(context.user["user_id"]),
            ip_address=_client_ip(request),
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    return {"status": "success", "revoked": count}


@app.get("/admin/audit-logs")
def admin_audit_logs(request: Request, limit: int = 100) -> Dict[str, Any]:
    _require_admin(request)
    return {
        "status": "success",
        "items": auth_service.list_audit_logs(limit=limit) if auth_service else [],
    }


@app.get("/llm/status")
def llm_status() -> Dict[str, Any]:
    return runtime.llm_status()


@app.get("/files/{file_path:path}")
def get_public_file(file_path: str, request: Request) -> FileResponse:
    try:
        resolved = config.resolve_public_path(file_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    context = _current_auth(request)
    if context.user.get("role") != "admin":
        relative = file_path.replace("\\", "/").lstrip("/")
        globally_visible = relative.startswith("uploads/teaching_maps/")
        matching = [
            artifact
            for artifact in runtime.store.artifacts.values()
            if Path(artifact.path).resolve() == resolved.resolve()
        ]
        project_owned = bool(matching) and any(
            (
                runtime.store.get_project(item.project_id) is not None
                and runtime.store.get_project(item.project_id).owner_user_id
                == context.user.get("user_id")
            )
            for item in matching
        )
        explicitly_owned = bool(
            auth_service
            and auth_service.can_access_file(str(context.user["user_id"]), resolved)
        )
        if not globally_visible and not project_owned and not explicitly_owned:
            raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(resolved)


@app.get("/teaching-maps")
def list_teaching_maps() -> Dict[str, Any]:
    return runtime.list_teaching_maps()


@app.post("/projects/{project_id}/teaching-maps/{map_id}/toggle")
def toggle_teaching_map(
    project_id: str,
    map_id: str,
    body: TeachingMapToggleRequest,
    request: Request,
) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    try:
        return runtime.toggle_teaching_map(project_id, map_id, body.visible)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/projects/{project_id}/teaching-maps/active")
def get_active_teaching_maps(project_id: str, request: Request) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    try:
        return runtime.get_active_teaching_maps(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/kb/manifest")
def get_kb_manifest(request: Request) -> Dict[str, Any]:
    context = _current_auth(request)
    return runtime.kb_manifest(
        owner_user_id=str(context.user["user_id"]),
        include_all=context.user.get("role") == "admin",
    )


@app.get("/kb/search")
def search_kb(
    request: Request,
    query: str = Query(""),
    topic: str = Query(""),
    region: str = Query(""),
    tag: str = Query(""),
    limit: int = Query(20),
) -> Dict[str, Any]:
    context = _current_auth(request)
    return runtime.kb_search(
        query=query,
        topic=topic,
        region=region,
        tag=tag,
        limit=limit,
        owner_user_id=str(context.user["user_id"]),
        include_all=context.user.get("role") == "admin",
    )


@app.get("/kb/topics")
def get_kb_topics(request: Request) -> Dict[str, Any]:
    context = _current_auth(request)
    return runtime.kb_topics(
        owner_user_id=str(context.user["user_id"]),
        include_all=context.user.get("role") == "admin",
    )


@app.post("/kb/items")
def upsert_kb_item(payload: KnowledgeItemRequest, request: Request) -> Dict[str, Any]:
    context = _current_auth(request)
    try:
        return runtime.kb_upsert_item(
            payload.item,
            owner_user_id=str(context.user["user_id"]),
            include_all=context.user.get("role") == "admin",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/kb/layers/register")
def register_kb_layer(payload: KnowledgeLayerRegisterRequest, request: Request) -> Dict[str, Any]:
    context = _current_auth(request)
    _require_project_access(request, payload.project_id)
    try:
        return runtime.kb_register_layer(
            payload.project_id,
            payload.layer_id,
            payload.metadata,
            owner_user_id=str(context.user["user_id"]),
            include_all=context.user.get("role") == "admin",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/kb/materials/upload")
async def upload_kb_material(
    request: Request,
    kb_item_id: str = Form(...),
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    material_type: str = Form(""),
    region_binding: str = Form("{}"),
) -> Dict[str, Any]:
    context = _current_auth(request)
    try:
        raw_binding = json.loads(region_binding or "{}")
        if not isinstance(raw_binding, dict):
            raise ValueError("region_binding must be an object")
        raw = await file.read()
        result = runtime.kb_upload_material(
            kb_item_id=kb_item_id,
            filename=file.filename or "material.dat",
            raw_bytes=raw,
            title=title,
            description=description,
            material_type=material_type,
            region_binding=raw_binding,
            owner_user_id=str(context.user["user_id"]),
            include_all=context.user.get("role") == "admin",
        )
        _grant_response_files(request, result)
        return result
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="region_binding must be valid JSON") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/kb/materials/link")
def link_kb_material(payload: KnowledgeMaterialLinkRequest, request: Request) -> Dict[str, Any]:
    context = _current_auth(request)
    try:
        return runtime.kb_link_material(
            kb_item_id=payload.kb_item_id,
            url=payload.url,
            title=payload.title,
            description=payload.description,
            material_type=payload.material_type,
            thumbnail_url=payload.thumbnail_url,
            region_binding=payload.region_binding,
            owner_user_id=str(context.user["user_id"]),
            include_all=context.user.get("role") == "admin",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/resources/search")
def search_resources(
    request: Request,
    query: str = Query(""),
    scope: str = Query("all"),
    limit: int = Query(12),
) -> Dict[str, Any]:
    context = _current_auth(request)
    return runtime.resource_search(
        query=query,
        scope=scope,
        limit=limit,
        owner_user_id=str(context.user["user_id"]),
        include_all=context.user.get("role") == "admin",
    )


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
def create_project(request: Request, payload: CreateProjectRequest) -> Dict[str, Any]:
    context = _current_auth(request)
    return runtime.create_project(
        name=payload.name or None,
        metadata=payload.metadata,
        owner_user_id=str(context.user["user_id"]),
    )


@app.get("/projects")
def list_projects(request: Request) -> Dict[str, Any]:
    context = _current_auth(request)
    return runtime.list_projects(
        owner_user_id=str(context.user["user_id"]),
        include_all=context.user.get("role") == "admin",
    )


@app.get("/projects/{project_id}")
def get_project(project_id: str, request: Request) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    try:
        return runtime.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/projects/{project_id}/lesson-resources")
def list_lesson_resources(project_id: str, request: Request) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    try:
        return runtime.list_lesson_resources(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/projects/{project_id}/lesson-resources")
def save_lesson_resource_set(
    project_id: str,
    payload: LessonResourceSetRequest,
    request: Request,
) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    try:
        return runtime.save_lesson_resource_set(project_id, payload.item)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/projects/{project_id}/lesson-resources/{set_id}")
def patch_lesson_resource_set(
    project_id: str,
    set_id: str,
    payload: LessonResourceSetPatchRequest,
    request: Request,
) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    try:
        return runtime.activate_lesson_resource_set(project_id, set_id, payload.patch)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/projects/{project_id}/basemap")
def patch_project_basemap(
    project_id: str,
    payload: SetBasemapRequest,
    request: Request,
) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    try:
        return runtime.set_basemap(project_id, payload.basemap_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/layers")
def list_layers(request: Request, project_id: str = Query(...)) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    try:
        return runtime.list_layers(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/layers")
def patch_layer(payload: LayerPatchRequest, request: Request) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    try:
        return runtime.patch_layer(payload.project_id, payload.layer_id, payload.patch)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/layers/{layer_id}")
def delete_layer(layer_id: str, request: Request, project_id: str = Query(...)) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    try:
        return runtime.delete_layer(project_id, layer_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/assistant/messages")
def submit_assistant_message(
    payload: AssistantMessageRequest,
    request: Request,
) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    try:
        response = runtime.submit_assistant_message(
            payload.project_id,
            payload.message,
            payload.map_context,
            payload.assistant_mode,
            payload.conversation_id,
            payload.history,
            payload.target,
            payload.input_mode,
            payload.screen_snapshot,
            payload.teaching_context,
            payload.image_attachments,
        )
        assistant_message = str(payload.message or "")
        wants_lesson_design = any(hint in assistant_message for hint in LESSON_DESIGN_REQUEST_HINTS) or (
            "教案" in assistant_message and any(token in assistant_message for token in ("共创", "设计", "生成", "备课", "规划"))
        )
        if wants_lesson_design and not assistant_message.lstrip().startswith("GeoBot 头脑风暴："):
            context = _current_auth(request)
            base_lesson_id = str((payload.teaching_context or {}).get("lesson_id") or "")
            if base_lesson_id:
                _require_lesson_access(request, base_lesson_id)
            response["lesson_design"] = runtime.classroom.create_lesson_design(
                payload.project_id,
                str(context.user["user_id"]),
                base_lesson_id,
                {"trigger": "assistant", "initial_request": payload.message},
            )
        return response
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/image-library/upload")
async def upload_image_library_asset(
    request: Request,
    project_id: str = Form(...),
    file: UploadFile = File(...),
    title: str = Form(""),
) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    try:
        raw = await file.read()
        return runtime.upload_image_asset(
            project_id=project_id,
            filename=file.filename or "uploaded_image",
            raw_bytes=raw,
            title=title,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/image-generation")
def generate_image(payload: ImageGenerationRequest, request: Request) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    if not payload.confirmed:
        raise HTTPException(status_code=409, detail="图片生成会产生 MiniMax API 费用，请先确认本次付费调用。")
    try:
        return runtime.generate_image_asset(
            project_id=payload.project_id,
            prompt=payload.prompt,
            title=payload.title,
            model=payload.model,
            aspect_ratio=payload.aspect_ratio,
            prompt_optimizer=payload.prompt_optimizer,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MiniMaxImageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/assistant/confirm")
def confirm_assistant_action(
    payload: AssistantConfirmRequest,
    request: Request,
) -> Dict[str, Any]:
    _require_confirmation_access(request, payload.confirmation_id)
    try:
        return runtime.confirm_assistant_action(payload.confirmation_id, decision=payload.decision)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/assistant/conversations/{conversation_id}")
def get_assistant_conversation(conversation_id: str, request: Request) -> Dict[str, Any]:
    _require_conversation_access(request, conversation_id)
    try:
        return runtime.get_conversation(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _websocket_authorized(websocket: "WebSocket") -> bool:
    """Mirror of the HTTP auth middleware for the voice WebSocket.

    HTTP middleware does not intercept WebSocket scopes, so the handshake is
    authenticated here. CSRF is skipped because the handshake is a GET and
    cannot carry custom headers; the session cookie (users mode) or the
    ``access_token`` query parameter (legacy token mode) is checked instead.
    """
    if config.auth_mode == "disabled":
        return True
    if config.auth_mode == "legacy_token":
        supplied = websocket.query_params.get("access_token", "").strip()
        return bool(supplied) and secrets.compare_digest(supplied, config.auth_token.strip())
    if auth_service is None:
        return False
    return auth_service.authenticate(websocket.cookies.get(SESSION_COOKIE, "")) is not None


async def _reject_voice_stream(
    websocket: "WebSocket",
    state: str,
    detail: str,
    code: int = 4403,
    *,
    accepted: bool = False,
) -> None:
    """Accept, explain why the stream cannot start, then close.

    The JSON event arrives before the close so the frontend can show the
    actionable reason (model missing / load failed / permission) instead of a
    bare close code.
    """
    if not accepted:
        await websocket.accept()
    try:
        await websocket.send_text(json.dumps({"type": "error", "reason": state, "detail": detail}, ensure_ascii=False))
    except Exception:  # client already gone
        pass
    await websocket.close(code=code)


@app.websocket("/assistant/voice/stream")
async def assistant_voice_stream(websocket: "WebSocket") -> None:
    # Not authorized: close with 4401 so the frontend can fall back to
    # browser speech recognition instead of retrying forever.
    if not _websocket_authorized(websocket):
        await websocket.close(code=4401)
        return
    engine = runtime.voice_asr
    status = engine.status()
    if not status["available"] and status.get("state") == "initializing":
        # The recognizer is warming up in the background; wait briefly so a
        # browser that connects right after backend start still gets audio.
        for _ in range(100):  # up to ~10s
            await asyncio.sleep(0.1)
            status = engine.status()
            if status["available"] or status.get("state") != "initializing":
                break
    if not status["available"]:
        await _reject_voice_stream(websocket, str(status.get("state") or "unavailable"), str(status.get("reason") or ""))
        return
    await websocket.accept()
    try:
        session = engine.create_session()
    except Exception as exc:  # lazy recognizer load failed between checks
        await _reject_voice_stream(websocket, "load_failed", str(exc), accepted=True)
        return
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            pcm = message.get("bytes")
            if pcm:
                for event in session.feed(pcm):
                    await websocket.send_text(json.dumps(event, ensure_ascii=False))
                continue
            text = message.get("text")
            if text == "flush":
                final = session.flush()
                if final:
                    await websocket.send_text(json.dumps(final, ensure_ascii=False))
                break
    except WebSocketDisconnect:
        pass
    finally:
        session.close()


@app.post("/templates/{template_id}/run")
def run_template(
    template_id: str,
    payload: TemplateRunRequest,
    request: Request,
) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    try:
        return runtime.submit_template(payload.project_id, template_id, payload.payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/datasets/upload")
async def upload_dataset(
    request: Request,
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
    _require_project_access(request, project_id)
    try:
        bounds = [float(value) for value in (west, south, east, north) if str(value).strip()]
        raw = await file.read()
        result = runtime.upload_dataset(
            project_id=project_id,
            filename=file.filename or "upload.dat",
            raw_bytes=raw,
            dataset_name=dataset_name,
            lat_field=lat_field,
            lon_field=lon_field,
            image_bounds=bounds or None,
        )
        _grant_response_files(request, result)
        return result
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
def add_dataset_catalog_layer(payload: CatalogLayerRequest, request: Request) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    try:
        return runtime.add_catalog_dataset_layer(payload.project_id, payload.dataset_id, preserve_view=payload.preserve_view)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/datasets/catalog/statistics")
def summarize_dataset_catalog_layers(
    payload: CatalogStatisticsRequest,
    request: Request,
) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    try:
        return runtime.summarize_catalog_layers(
            payload.project_id,
            geometry=payload.geometry,
            layer_id=payload.layer_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/ppt/render")
async def render_ppt(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    try:
        raw = await file.read()
        result = render_pptx_to_images(config, file.filename or "presentation.pptx", raw)
        _grant_response_files(request, result)
        return result
    except PptRenderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_dict()) from exc


@app.post("/search/poi")
def search_poi(payload: PoiSearchRequest, request: Request) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    try:
        return runtime.search_poi(
            payload.project_id,
            keyword=payload.keyword,
            mode=payload.mode,
            extent=payload.extent,
            geometry=payload.geometry,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/exports/snapshot")
def export_snapshot(payload: ExportSnapshotRequest, request: Request) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    try:
        return runtime.export_snapshot(
            payload.project_id,
            title=payload.title,
            image_data_url=payload.image_data_url,
            note=payload.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/lessons")
def list_lessons(request: Request) -> Dict[str, Any]:
    context = _current_auth(request)
    return runtime.classroom.list_lessons(
        owner_user_id=str(context.user["user_id"]),
        include_all=context.user.get("role") == "admin",
    )


@app.get("/lesson-design/sessions")
def list_lesson_design_sessions(project_id: str, request: Request) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    context = _current_auth(request)
    designs = runtime.store.list_lesson_designs(
        project_id=project_id,
        owner_user_id=str(context.user["user_id"]) if context.user.get("role") != "admin" else "",
    )
    return {"status": "success", "items": [item.to_dict() for item in designs]}


@app.post("/lesson-design/sessions")
def create_lesson_design_session(payload: LessonDesignCreateRequest, request: Request) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    context = _current_auth(request)
    if payload.base_lesson_id:
        _require_lesson_access(request, payload.base_lesson_id)
    try:
        return runtime.classroom.create_lesson_design(
            payload.project_id,
            str(context.user["user_id"]),
            payload.base_lesson_id,
            payload.requirements,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/lesson-design/sessions/{design_id}")
def get_lesson_design_session(design_id: str, request: Request) -> Dict[str, Any]:
    _require_lesson_design_access(request, design_id)
    try:
        result = runtime.classroom.get_lesson_design(design_id)
        _grant_response_files(request, result)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/lesson-design/sessions/{design_id}/turns")
def turn_lesson_design(design_id: str, payload: LessonDesignTurnRequest, request: Request) -> Dict[str, Any]:
    _require_lesson_design_access(request, design_id)
    try:
        result = runtime.classroom.turn_lesson_design(design_id, payload.message, payload.expected_revision, payload.step)
        _grant_response_files(request, result)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409 if "更新" in str(exc) else 400, detail=str(exc)) from exc


@app.post("/lesson-design/sessions/{design_id}/questions/bind")
def bind_lesson_design_question(design_id: str, payload: LessonDesignQuestionBindRequest, request: Request) -> Dict[str, Any]:
    _require_lesson_design_access(request, design_id)
    try:
        result = runtime.classroom.bind_lesson_design_question(
            design_id,
            payload.stage_id,
            question_id=payload.question_id,
            manual=payload.manual or None,
            action=payload.action,
            position=payload.position,
            expected_revision=payload.expected_revision,
        )
        _grant_response_files(request, result)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409 if "更新" in str(exc) else 400, detail=str(exc)) from exc


@app.post("/lesson-design/sessions/{design_id}/sections/{section_id}/resolve")
def resolve_lesson_design_section(design_id: str, section_id: str, payload: LessonDesignResolveRequest, request: Request) -> Dict[str, Any]:
    _require_lesson_design_access(request, design_id)
    try:
        result = runtime.classroom.resolve_lesson_design(design_id, section_id, payload.decision, payload.teacher_note, payload.expected_revision, payload.value)
        _grant_response_files(request, result)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409 if "更新" in str(exc) else 400, detail=str(exc)) from exc


@app.post("/lesson-design/sessions/{design_id}/finalize")
def finalize_lesson_design(design_id: str, payload: LessonDesignFinalizeRequest, request: Request) -> Dict[str, Any]:
    _require_lesson_design_access(request, design_id)
    try:
        result = runtime.classroom.finalize_lesson_design(design_id, payload.expected_revision, payload.apply_base)
        _grant_response_files(request, result)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409 if "更新" in str(exc) else 400, detail=str(exc)) from exc


def _require_rehearsal_access(request: Request, rehearsal_id: str) -> Any:
    rehearsal = runtime.store.get_lesson_rehearsal(rehearsal_id)
    if rehearsal is None:
        raise HTTPException(status_code=404, detail="Unknown lesson rehearsal")
    _require_project_access(request, rehearsal.project_id)
    context = _current_auth(request)
    if context.user.get("role") != "admin" and rehearsal.owner_user_id != context.user.get("user_id"):
        raise HTTPException(status_code=404, detail="Unknown lesson rehearsal")
    return rehearsal


@app.post("/lesson-rehearsals")
def create_lesson_rehearsal(payload: LessonRehearsalCreateRequest, request: Request) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    _require_lesson_access(request, payload.lesson_id)
    context = _current_auth(request)
    try:
        return runtime.classroom.create_lesson_rehearsal(
            payload.project_id,
            payload.lesson_id,
            owner_user_id=str(context.user.get("user_id") or ""),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/lesson-rehearsals")
def list_lesson_rehearsals(project_id: str, request: Request, lesson_id: str = Query(""), status: str = Query("")) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    return runtime.classroom.list_lesson_rehearsals(project_id=project_id, lesson_id=lesson_id, status=status)


@app.get("/lesson-rehearsals/{rehearsal_id}")
def get_lesson_rehearsal(rehearsal_id: str, request: Request) -> Dict[str, Any]:
    _require_rehearsal_access(request, rehearsal_id)
    return runtime.classroom.get_lesson_rehearsal(rehearsal_id)


@app.patch("/lesson-rehearsals/{rehearsal_id}")
def update_lesson_rehearsal(rehearsal_id: str, payload: LessonRehearsalUpdateRequest, request: Request) -> Dict[str, Any]:
    _require_rehearsal_access(request, rehearsal_id)
    try:
        return runtime.classroom.update_lesson_rehearsal(
            rehearsal_id,
            patch=payload.patch,
            question_bind=payload.question_bind,
            question_remove=payload.question_remove,
            image_bind=payload.image_bind,
            scene_capture=payload.scene_capture,
            test_result=payload.test_result,
            expected_revision=payload.expected_revision,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409 if "已更新" in str(exc) else 400, detail=str(exc)) from exc


@app.post("/lesson-rehearsals/{rehearsal_id}/apply-scene")
def apply_rehearsal_stage_scene(rehearsal_id: str, payload: LessonRehearsalStageRequest, request: Request) -> Dict[str, Any]:
    _require_rehearsal_access(request, rehearsal_id)
    try:
        return runtime.classroom.apply_rehearsal_stage_scene(rehearsal_id, payload.stage_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/lesson-rehearsals/{rehearsal_id}/report")
def lesson_rehearsal_report(rehearsal_id: str, request: Request) -> Dict[str, Any]:
    _require_rehearsal_access(request, rehearsal_id)
    return runtime.classroom.lesson_rehearsal_report(rehearsal_id)


@app.post("/lesson-rehearsals/{rehearsal_id}/complete")
def complete_lesson_rehearsal(rehearsal_id: str, payload: LessonRehearsalCompleteRequest, request: Request) -> Dict[str, Any]:
    _require_rehearsal_access(request, rehearsal_id)
    try:
        result = runtime.classroom.complete_lesson_rehearsal(rehearsal_id, expected_revision=payload.expected_revision)
        _grant_response_files(request, result)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409 if "已更新" in str(exc) else 400, detail=str(exc)) from exc


@app.post("/lesson-rehearsals/{rehearsal_id}/cancel")
def cancel_lesson_rehearsal(rehearsal_id: str, request: Request) -> Dict[str, Any]:
    _require_rehearsal_access(request, rehearsal_id)
    try:
        return runtime.classroom.cancel_lesson_rehearsal(rehearsal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_question_bank_access(request: Request, bank_id: str) -> Any:
    try:
        bank = runtime.classroom.question_bank.get_bank(bank_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _require_project_access(request, bank["project_id"])


@app.post("/question-banks/import")
async def import_question_banks(
    request: Request,
    project_id: str = Form(...),
    files: List[UploadFile] = File(...),
) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    if not files:
        raise HTTPException(status_code=400, detail="未选择任何文件。")
    if len(files) > 4:
        raise HTTPException(status_code=400, detail="单次导入最多 4 个文件。")
    payload = []
    for upload in files:
        raw = await upload.read()
        payload.append({"filename": upload.filename or "题库.docx", "raw": raw})
    context = _current_auth(request)
    return runtime.classroom.submit_question_bank_import(
        project_id,
        payload,
        owner_user_id=str(context.user.get("user_id") or ""),
    )


@app.get("/question-banks")
def list_question_banks(project_id: str, request: Request) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    result = runtime.classroom.list_question_banks(project_id)
    _grant_response_files(request, result)
    return result


@app.delete("/question-banks/{bank_id}")
def delete_question_bank(bank_id: str, request: Request) -> Dict[str, Any]:
    _require_question_bank_access(request, bank_id)
    return runtime.classroom.delete_question_bank(bank_id)


@app.get("/question-banks/{bank_id}/questions")
def list_question_bank_questions(
    bank_id: str,
    request: Request,
    section: str = Query(""),
    type: str = Query(""),
    answer_complete: Optional[bool] = Query(None),
    search: str = Query(""),
    page: int = Query(1),
    page_size: int = Query(20),
) -> Dict[str, Any]:
    _require_question_bank_access(request, bank_id)
    try:
        result = runtime.classroom.get_question_bank_questions(
            bank_id,
            section=section,
            qtype=type,
            answer_complete=answer_complete,
            search=search,
            page=page,
            page_size=page_size,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _grant_response_files(request, result)
    return result


@app.get("/question-banks/{bank_id}/groups/{group_key}")
def get_question_bank_group(bank_id: str, group_key: str, request: Request) -> Dict[str, Any]:
    _require_question_bank_access(request, bank_id)
    try:
        result = runtime.classroom.get_question_bank_group(bank_id, group_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _grant_response_files(request, result)
    return result


@app.post("/question-banks/search")
def search_question_banks(payload: QuestionBankSearchRequest, request: Request) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    for bank_id in payload.bank_ids:
        _require_question_bank_access(request, bank_id)
    try:
        result = runtime.classroom.search_question_banks(
            payload.project_id,
            bank_ids=payload.bank_ids,
            topic=payload.topic,
            knowledge=payload.knowledge,
            objectives=payload.objectives,
            qtype=payload.type,
            exclude_ids=payload.exclude_ids,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _grant_response_files(request, result)
    return result


@app.get("/population-sources/versions")
def list_population_source_versions(request: Request, project_id: str = Query("")) -> Dict[str, Any]:
    if project_id:
        _require_project_access(request, project_id)
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
    request: Request,
    project_id: str = Query(""),
    version: str = Query(""),
) -> Dict[str, Any]:
    if project_id:
        _require_project_access(request, project_id)
    try:
        return runtime.list_population_sources(project_id=project_id, version=version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/population-sources/{source_id}")
def get_population_source(
    source_id: str,
    request: Request,
    project_id: str = Query(""),
    version: str = Query(""),
    expected_fingerprint: str = Query(""),
) -> Dict[str, Any]:
    if project_id:
        _require_project_access(request, project_id)
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
    payload: PopulationSourceVersionRequest,
    request: Request,
) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    try:
        return runtime.activate_population_source_version(project_id, payload.version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/lesson-prep/population")
def prepare_population_lesson(
    payload: PopulationLessonPrepRequest,
    request: Request,
) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    _require_lesson_access(request, payload.lesson_id)
    try:
        return runtime.classroom.submit_population_lesson_prep(payload.project_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/lesson-prep/change-sets/{job_id}/resolve")
def resolve_population_lesson_change_set(
    job_id: str,
    payload: PopulationChangeSetResolveRequest,
    request: Request,
) -> Dict[str, Any]:
    _require_job_access(request, job_id)
    try:
        return runtime.classroom.resolve_population_lesson_prep(
            job_id,
            payload.decision,
            accepted_stage_ids=payload.accepted_stage_ids,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/lessons")
def create_lesson(payload: LessonPayloadRequest, request: Request) -> Dict[str, Any]:
    context = _current_auth(request)
    return runtime.classroom.create_lesson(
        payload.model_dump(),
        owner_user_id=str(context.user["user_id"]),
    )


@app.get("/lessons/{lesson_id}")
def get_lesson(lesson_id: str, request: Request) -> Dict[str, Any]:
    _require_lesson_access(request, lesson_id)
    try:
        return runtime.classroom.get_lesson(lesson_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/lessons/{lesson_id}")
def update_lesson(lesson_id: str, payload: LessonPayloadRequest, request: Request) -> Dict[str, Any]:
    lesson = _require_lesson_access(request, lesson_id)
    if lesson.source == "builtin":
        raise HTTPException(status_code=403, detail="Built-in lessons are read-only")
    try:
        return runtime.classroom.update_lesson(lesson_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/lessons/{lesson_id}")
def delete_lesson(lesson_id: str, request: Request) -> Dict[str, Any]:
    lesson = _require_lesson_access(request, lesson_id)
    if lesson.source == "builtin":
        raise HTTPException(status_code=403, detail="Built-in lessons are read-only")
    try:
        return runtime.classroom.delete_lesson(lesson_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/lessons/import")
def import_lesson(payload: LessonImportRequest, request: Request) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    context = _current_auth(request)
    try:
        return runtime.classroom.submit_lesson_import(
            payload.project_id,
            payload.text,
            owner_user_id=str(context.user["user_id"]),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/lessons/{lesson_id}/exports/docx")
def export_lesson_docx(lesson_id: str, payload: LessonDocxExportRequest, request: Request) -> Dict[str, Any]:
    lesson = _require_lesson_access(request, lesson_id)
    project_id = str(payload.project_id or (lesson.metadata or {}).get("project_id") or "")
    if not project_id:
        context = _current_auth(request)
        projects = [p for p in runtime.store.projects.values() if p.owner_user_id == context.user.get("user_id") or context.user.get("role") == "admin"]
        if len(projects) == 1:
            project_id = projects[0].project_id
    if not project_id:
        raise HTTPException(status_code=400, detail="请指定项目")
    _require_project_access(request, project_id)
    if payload.design_id:
        design = _require_lesson_design_access(request, payload.design_id)
        if design.project_id != project_id:
            raise HTTPException(status_code=400, detail="教案会话不属于当前项目")
    try:
        return runtime.classroom.export_lesson_docx(lesson_id, project_id, payload.design_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/lessons/{lesson_id}/stages/{stage_id}/scene/apply")
def apply_lesson_scene(lesson_id: str, stage_id: str, payload: SceneApplyRequest, request: Request) -> Dict[str, Any]:
    _require_lesson_access(request, lesson_id)
    _require_project_access(request, payload.project_id)
    try:
        return runtime.classroom.apply_lesson_scene(payload.project_id, lesson_id, stage_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/lessons/{lesson_id}/stages/{stage_id}/scene/capture")
def capture_lesson_scene(lesson_id: str, stage_id: str, payload: SceneCaptureRequest, request: Request) -> Dict[str, Any]:
    lesson = _require_lesson_access(request, lesson_id)
    if lesson.source == "builtin":
        raise HTTPException(status_code=403, detail="Built-in lessons are read-only")
    try:
        return runtime.classroom.capture_lesson_scene(lesson_id, stage_id, payload.snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/class-sessions")
def create_class_session(payload: ClassSessionCreateRequest, request: Request) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    _require_lesson_access(request, payload.lesson_id)
    try:
        return runtime.classroom.create_class_session(payload.lesson_id, payload.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/class-sessions")
def list_class_sessions(
    request: Request,
    lesson_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    if project_id:
        _require_project_access(request, project_id)
    if lesson_id:
        _require_lesson_access(request, lesson_id)
    response = runtime.classroom.list_class_sessions(lesson_id=lesson_id, project_id=project_id)
    context = _current_auth(request)
    if context.user.get("role") != "admin" and not project_id:
        response["items"] = [
            item
            for item in response.get("items", [])
            if (
                (project := runtime.store.get_project(str(item.get("project_id") or ""))) is not None
                and project.owner_user_id == context.user.get("user_id")
            )
        ]
    return response


@app.get("/class-sessions/{session_id}")
def get_class_session(session_id: str, request: Request) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        return runtime.classroom.get_class_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/end")
def end_class_session(session_id: str, request: Request) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        return runtime.classroom.end_class_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/stage")
def enter_session_stage(session_id: str, payload: SessionStageRequest, request: Request) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        return runtime.classroom.enter_session_stage(session_id, payload.stage_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/presentation")
def present_session_scene(session_id: str, payload: SessionPresentationRequest, request: Request) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        return runtime.classroom.present_session_scene(session_id, payload.stage_id, payload.target)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/questions/launch")
def launch_session_question(session_id: str, payload: QuestionLaunchRequest, request: Request) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        return runtime.classroom.launch_session_question(
            session_id,
            stage_id=payload.stage_id,
            question_id=payload.question_id,
            adhoc=payload.adhoc,
            delivery=payload.delivery,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/questions/close")
def close_session_question(session_id: str, request: Request) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        return runtime.classroom.close_session_question(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/questions/timer")
def update_session_question_timer(session_id: str, payload: QuestionTimerRequest, request: Request) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        return runtime.classroom.update_question_timer(session_id, payload.action)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/questions/reveal")
def reveal_session_question(session_id: str, request: Request) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        return runtime.classroom.reveal_session_question(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/class-sessions/{session_id}/questions/explanation")
def get_question_explanation(session_id: str, request: Request) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        return runtime.classroom.get_question_explanation(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/observations")
def add_session_observation(session_id: str, payload: ObservationRequest, request: Request) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        return runtime.classroom.add_session_observation(session_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/events")
def log_session_event(session_id: str, payload: SessionEventRequest, request: Request) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        return runtime.classroom.log_session_event(
            session_id,
            event_type=payload.event_type,
            stage_id=payload.stage_id,
            payload=payload.payload,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/class-sessions/{session_id}/review-history")
def session_review_history(session_id: str, request: Request) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        return runtime.classroom.session_review_history(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/class-sessions/{session_id}/report")
def generate_session_report(session_id: str, request: Request) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        return runtime.classroom.submit_session_report(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class PracticeSelectionRequest(BaseModel):
    token: str
    selected_ids: List[str]


@app.post("/class-sessions/{session_id}/practice-export")
def export_session_practice(session_id: str, request: Request, payload: Optional[PracticeSelectionRequest] = None, background: bool = False) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        selection = payload.model_dump() if payload is not None else None
        if background:
            return runtime.classroom.submit_session_practice(session_id, selection)
        return runtime.classroom.export_session_practice(session_id, selection)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/class-sessions/{session_id}/live")
def session_live(session_id: str, request: Request) -> Dict[str, Any]:
    _require_session_access(request, session_id)
    try:
        return runtime.classroom.session_live(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> Dict[str, Any]:
    _require_job_access(request, job_id)
    try:
        return runtime.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/jobs/{job_id}/stream")
def stream_job(job_id: str, request: Request):
    _require_job_access(request, job_id)
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
            runtime.store.wait_for_job_update(job_id, str(version), timeout=1.0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, request: Request) -> Dict[str, Any]:
    _require_artifact_access(request, artifact_id)
    try:
        return runtime.get_artifact(artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/outputs")
def list_outputs(request: Request, project_id: Optional[str] = None) -> Dict[str, Any]:
    if project_id:
        _require_project_access(request, project_id)
    response = runtime.list_outputs(project_id=project_id)
    context = _current_auth(request)
    if context.user.get("role") != "admin" and not project_id:
        response["items"] = [
            item
            for item in response.get("items", [])
            if (
                (project := runtime.store.get_project(str(item.get("project_id") or ""))) is not None
                and project.owner_user_id == context.user.get("user_id")
            )
        ]
    return response


@app.post("/outputs/{artifact_id}/load-layer")
def load_output_layer(artifact_id: str, payload: ArtifactLoadLayerRequest, request: Request) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    try:
        return runtime.load_output_as_layer(payload.project_id, artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/outputs/{artifact_id}")
def delete_output(artifact_id: str, request: Request, project_id: str = Query(...)) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    try:
        return runtime.delete_output(project_id, artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/resources/save")
def save_resource_result(payload: ResourceSaveRequest, request: Request) -> Dict[str, Any]:
    _require_project_access(request, payload.project_id)
    context = _current_auth(request)
    try:
        return runtime.save_resource_result(
            payload.project_id,
            {
                "title": payload.title,
                "url": payload.url,
                "summary": payload.summary,
                "source": payload.source,
                "type": payload.type,
                "thumbnail_url": payload.thumbnail_url,
            },
            owner_user_id=str(context.user["user_id"]),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# GIS workflow endpoints
# ---------------------------------------------------------------------------


@app.get("/workflow/templates")
def list_workflow_templates() -> Dict[str, Any]:
    return runtime.list_workflow_templates()


@app.post("/workflow/submit")
def submit_workflow(payload: WorkflowSubmitRequest, request: Request) -> Dict[str, Any]:
    if not payload.project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    _require_project_access(request, payload.project_id)
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
def workflow_history(request: Request, project_id: Optional[str] = None) -> Dict[str, Any]:
    if project_id:
        _require_project_access(request, project_id)
    response = runtime.list_workflows(project_id=project_id)
    context = _current_auth(request)
    if context.user.get("role") != "admin" and not project_id:
        response["items"] = [
            item
            for item in response.get("items", [])
            if (
                (project := runtime.store.get_project(str(item.get("project_id") or ""))) is not None
                and project.owner_user_id == context.user.get("user_id")
            )
        ]
    return response


@app.get("/workflow/{workflow_id}")
def get_workflow(workflow_id: str, request: Request) -> Dict[str, Any]:
    _require_workflow_access(request, workflow_id)
    try:
        return runtime.get_workflow(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/workflow/{workflow_id}/cancel")
def cancel_workflow(workflow_id: str, request: Request) -> Dict[str, Any]:
    _require_workflow_access(request, workflow_id)
    try:
        return runtime.cancel_workflow(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/workflow/{workflow_id}/artifacts")
def get_workflow_artifacts(workflow_id: str, request: Request) -> Dict[str, Any]:
    _require_workflow_access(request, workflow_id)
    try:
        return runtime.list_workflow_artifacts(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/workflow/{workflow_id}/stream")
def stream_workflow(workflow_id: str, request: Request):
    _require_workflow_access(request, workflow_id)
    def event_stream():
        for event in runtime.stream_workflow_events(workflow_id):
            event_type = str(event.get("type") or "message")
            data = json.dumps(event.get("payload") or {}, ensure_ascii=False)
            yield f"event: {event_type}\ndata: {data}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/workflow-files/{workflow_id}/{relative_path:path}")
def serve_workflow_file(workflow_id: str, relative_path: str, request: Request):
    _require_workflow_access(request, workflow_id)
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
    request: Request,
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    _require_project_access(request, project_id)
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
def get_timeline(project_id: str, request: Request) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    try:
        return runtime.get_timeline(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/projects/{project_id}/timeline")
def update_timeline(project_id: str, payload: TimelinePatchRequest, request: Request) -> Dict[str, Any]:
    _require_project_access(request, project_id)
    try:
        return runtime.update_timeline(project_id, payload.patch)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
