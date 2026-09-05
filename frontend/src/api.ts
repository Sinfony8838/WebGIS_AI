import type {
  AssistantMode,
  AssistantInputMode,
  AssistantTarget,
  AuthAuditLog,
  AuthBootstrapStatus,
  AuthSession,
  AuthUser,
  ArtifactRecord,
  BasemapCatalog,
  BasemapPreset,
  CatalogDatasetDataResponse,
  ChatMessage,
  DatasetCatalogLayerResponse,
  ConversationResponse,
  DatasetCatalogResponse,
  DatasetStatsResponse,
  HealthResponse,
  ImageAttachment,
  JobRecord,
  KnowledgeBaseItem,
  KnowledgeLayerRegisterResponse,
  KnowledgeManifestResponse,
  ClassSessionRecord,
  ClassSessionResponse,
  LessonResourceResponse,
  LessonResourceSet,
  LessonDesignSession,
  LessonDesignTurnResult,
  LessonRecord,
  LessonStage,
  LessonRehearsalRecord,
  LessonRehearsalReport,
  LessonRehearsalCompleteResult,
  MaterialWriteResponse,
  KnowledgeSearchResponse,
  KnowledgeTopicsResponse,
  LlmStatusResponse,
  LayersResponse,
  MapContext,
  PoiSearchResponse,
  PopulationLessonPrepInput,
  PopulationLessonPrepResult,
  PopulationSourceCard,
  PopulationSourceVersion,
  PptRenderResponse,
  ProjectRecord,
  QgisStatusResponse,
  QuestionBankGroup,
  QuestionBankQuestion,
  QuestionBankSummary,
  QuestionRetrievalCandidate,
  RegionBinding,
  ResourceSearchResponse,
  ScreenSnapshot,
  SceneSnapshot,
  SessionLiveState,
  TeachingContext,
  TimelineData,
  TimelineGenerateResponse,
  TimelineSaveResponse,
  WorkflowArtifactsResponse,
  WorkflowHistoryResponse,
  WorkflowRecord,
  WorkflowSubmitResponse,
  WorkflowTemplatesResponse
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:18999";
let csrfToken = "";
let unauthorizedHandler: (() => void) | null = null;

export function setCsrfToken(value: string): void {
  csrfToken = value || "";
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const method = String(init?.method || "GET").toUpperCase();
  const headers = new Headers(init?.headers);
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) {
    headers.set("X-WebGIS-CSRF", csrfToken);
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      credentials: "include"
    });
  } catch (err) {
    throw new Error(
      `无法连接到后端服务 (${API_BASE})，请确认服务已启动`
    );
  }
  if (!response.ok) {
    if (response.status === 401) {
      csrfToken = "";
      unauthorizedHandler?.();
    }
    let message = `请求失败 (${response.status})`;
    try {
      const body = await response.json();
      if (body && typeof body.detail === "string") {
        message = body.detail;
      } else if (body && typeof body.detail === "object") {
        message = String(body.detail.message || body.detail.code || JSON.stringify(body.detail));
      }
    } catch {
      try {
        const text = await response.text();
        if (text) message = text;
      } catch { /* ignore */ }
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export async function fetchBootstrapStatus(): Promise<AuthBootstrapStatus> {
  return requestJson<AuthBootstrapStatus>("/auth/bootstrap-status");
}

export async function bootstrapAdmin(payload: {
  email: string;
  nickname: string;
  password: string;
  bootstrap_key?: string;
}): Promise<AuthSession> {
  const { bootstrap_key, ...body } = payload;
  const headers = new Headers({ "Content-Type": "application/json" });
  if (bootstrap_key) headers.set("X-WebGIS-Bootstrap-Key", bootstrap_key);
  const session = await requestJson<AuthSession>("/auth/bootstrap", {
    method: "POST",
    headers,
    body: JSON.stringify(body)
  });
  setCsrfToken(session.csrf_token);
  return session;
}

export async function loginUser(email: string, password: string): Promise<AuthSession> {
  const session = await requestJson<AuthSession>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password })
  });
  setCsrfToken(session.csrf_token);
  return session;
}

export async function fetchCurrentUser(): Promise<AuthSession> {
  const session = await requestJson<AuthSession>("/auth/me");
  setCsrfToken(session.csrf_token);
  return session;
}

export async function logoutUser(): Promise<void> {
  await requestJson("/auth/logout", { method: "POST" });
  setCsrfToken("");
}

export async function logoutAllSessions(): Promise<void> {
  await requestJson("/auth/logout-all", { method: "POST" });
  setCsrfToken("");
}

export async function changePassword(
  currentPassword: string,
  newPassword: string
): Promise<{ status: string; user: AuthUser }> {
  return requestJson("/auth/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword
    })
  });
}

export async function fetchAdminUsers(filters: {
  query?: string;
  role?: string;
  status?: string;
} = {}): Promise<{ status: string; items: AuthUser[] }> {
  const query = new URLSearchParams();
  if (filters.query) query.set("query", filters.query);
  if (filters.role) query.set("role", filters.role);
  if (filters.status) query.set("status", filters.status);
  const suffix = query.size ? `?${query.toString()}` : "";
  return requestJson(`/admin/users${suffix}`);
}

export async function createAdminUser(payload: {
  email: string;
  nickname: string;
  role: "admin" | "teacher";
}): Promise<{ status: string; user: AuthUser; temporary_password: string }> {
  return requestJson("/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function updateAdminUser(
  userId: string,
  patch: Partial<Pick<AuthUser, "nickname" | "email" | "role" | "status">>
): Promise<{ status: string; user: AuthUser }> {
  return requestJson(`/admin/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch)
  });
}

export async function resetAdminUserPassword(
  userId: string
): Promise<{ status: string; user: AuthUser; temporary_password: string }> {
  return requestJson(`/admin/users/${encodeURIComponent(userId)}/reset-password`, {
    method: "POST"
  });
}

export async function revokeAdminUserSessions(
  userId: string
): Promise<{ status: string; revoked: number }> {
  return requestJson(`/admin/users/${encodeURIComponent(userId)}/revoke-sessions`, {
    method: "POST"
  });
}

export async function fetchAuditLogs(limit = 100): Promise<{
  status: string;
  items: AuthAuditLog[];
}> {
  return requestJson(`/admin/audit-logs?limit=${encodeURIComponent(String(limit))}`);
}

export function getApiBase(): string {
  return API_BASE;
}

export function buildAuthenticatedUrl(path: string): string {
  if (!path) {
    return "";
  }
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  return `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function fetchHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/health");
}

export async function fetchLlmStatus(): Promise<LlmStatusResponse> {
  return requestJson<LlmStatusResponse>("/llm/status");
}

export async function fetchQgisStatus(): Promise<QgisStatusResponse> {
  return requestJson<QgisStatusResponse>("/qgis/status");
}

export async function fetchQgisLayers(): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>("/qgis/layers");
}

export async function executeQgisTool(toolName: string, params: Record<string, unknown>): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(`/qgis/tools/${encodeURIComponent(toolName)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params)
  });
}

export async function focusQgis(): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>("/qgis/focus", {
    method: "POST"
  });
}

export function buildQgisPreviewUrl(path: string, stamp = 0): string {
  const query = new URLSearchParams();
  query.set("path", path);
  if (stamp) {
    query.set("t", String(stamp));
  }
  return `${API_BASE}/qgis/preview?${query.toString()}`;
}

export async function fetchBasemaps(): Promise<BasemapCatalog> {
  return requestJson<BasemapCatalog>("/basemaps");
}

export async function createProject(name = "WebGIS 实时课堂"): Promise<ProjectRecord & { status: string }> {
  return requestJson<ProjectRecord & { status: string }>("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, metadata: { mode: "single_teacher_live_demo" } })
  });
}

export async function fetchProject(projectId: string): Promise<ProjectRecord & { status: string }> {
  return requestJson<ProjectRecord & { status: string }>(`/projects/${projectId}`);
}

export async function switchBasemap(projectId: string, basemapId: string): Promise<{ status: string; base_map: BasemapPreset }> {
  return requestJson<{ status: string; base_map: BasemapPreset }>(`/projects/${projectId}/basemap`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ basemap_id: basemapId })
  });
}

export async function fetchLayers(projectId: string): Promise<LayersResponse> {
  return requestJson<LayersResponse>(`/layers?project_id=${encodeURIComponent(projectId)}`);
}

export async function fetchDatasetCatalog(): Promise<DatasetCatalogResponse> {
  return requestJson<DatasetCatalogResponse>("/datasets/catalog");
}

// Read-only catalog GeoJSON fetch used by the 3D globe thematic layers.
// Cached per dataset id so toggling themes doesn't re-download files.
const catalogDataCache = new Map<string, Promise<CatalogDatasetDataResponse>>();

export function fetchCatalogDatasetData(datasetId: string): Promise<CatalogDatasetDataResponse> {
  let pending = catalogDataCache.get(datasetId);
  if (!pending) {
    pending = requestJson<CatalogDatasetDataResponse>(
      `/datasets/catalog/${encodeURIComponent(datasetId)}/data`
    ).catch((error) => {
      catalogDataCache.delete(datasetId);
      throw error;
    });
    catalogDataCache.set(datasetId, pending);
  }
  return pending;
}

export async function addCatalogDatasetLayer(
  projectId: string,
  datasetId: string
): Promise<DatasetCatalogLayerResponse> {
  return requestJson<DatasetCatalogLayerResponse>("/datasets/catalog/layers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, dataset_id: datasetId })
  });
}

export async function summarizeCatalogLayers(
  projectId: string,
  geometry: Record<string, unknown> | null,
  layerId = ""
): Promise<DatasetStatsResponse> {
  return requestJson<DatasetStatsResponse>("/datasets/catalog/statistics", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, layer_id: layerId, geometry: geometry || {} })
  });
}

export async function patchLayer(projectId: string, layerId: string, patch: Record<string, unknown>): Promise<void> {
  await requestJson("/layers", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, layer_id: layerId, patch })
  });
}

export async function runTemplate(projectId: string, templateId: string): Promise<{ job_id: string }> {
  return requestJson<{ job_id: string }>(`/templates/${templateId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, payload: {} })
  });
}

export async function sendAssistantMessage(
  projectId: string,
  message: string,
  mapContext: MapContext,
  target: AssistantTarget = "webgis",
  inputMode: AssistantInputMode = "text",
  options?: {
    assistantMode?: AssistantMode;
    conversationId?: string;
    history?: ChatMessage[];
    screenSnapshot?: ScreenSnapshot;
    teachingContext?: TeachingContext;
    imageAttachments?: Array<Pick<ImageAttachment, "artifact_id">>;
  }
): Promise<{ job_id: string; conversation_id?: string; assistant_mode?: AssistantMode; lesson_design?: LessonDesignSession }> {
  return requestJson<{ job_id: string; conversation_id?: string; assistant_mode?: AssistantMode; lesson_design?: LessonDesignSession }>("/assistant/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      message,
      map_context: mapContext,
      assistant_mode: options?.assistantMode || "",
      conversation_id: options?.conversationId || "",
      history: options?.history || [],
      target,
      input_mode: inputMode,
      screen_snapshot: options?.screenSnapshot || {},
      teaching_context: options?.teachingContext || mapContext.teaching_context || {},
      image_attachments: options?.imageAttachments || []
    })
  });
}

export async function uploadImageLibraryAsset(
  projectId: string,
  file: File,
  title = ""
): Promise<{ job_id: string; artifact: ArtifactRecord }> {
  const formData = new FormData();
  formData.set("project_id", projectId);
  formData.set("file", file);
  if (title.trim()) {
    formData.set("title", title.trim());
  }
  return requestJson<{ job_id: string; artifact: ArtifactRecord }>("/image-library/upload", {
    method: "POST",
    body: formData
  });
}

export async function generateImageLibraryAsset(
  projectId: string,
  prompt: string,
  options?: { title?: string; model?: string; aspectRatio?: string; promptOptimizer?: boolean }
): Promise<{ job_id: string; artifact: ArtifactRecord }> {
  return requestJson<{ job_id: string; artifact: ArtifactRecord }>("/image-generation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      prompt,
      title: options?.title || "",
      model: options?.model || "",
      aspect_ratio: options?.aspectRatio || "16:9",
      prompt_optimizer: options?.promptOptimizer ?? true,
      confirmed: true
    })
  });
}

export async function confirmAssistantAction(
  confirmationId: string,
  decision: "approve" | "reject" = "approve"
): Promise<{ job_id: string; confirmation_id: string; decision: "approve" | "reject" }> {
  return requestJson<{ job_id: string; confirmation_id: string; decision: "approve" | "reject" }>("/assistant/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmation_id: confirmationId, decision })
  });
}

export async function fetchConversation(conversationId: string): Promise<ConversationResponse> {
  return requestJson<ConversationResponse>(`/assistant/conversations/${encodeURIComponent(conversationId)}`);
}

export async function searchPoi(
  projectId: string,
  keyword: string,
  options: { mode: string; extent?: number[]; geometry?: Record<string, unknown> | null }
): Promise<PoiSearchResponse> {
  return requestJson<PoiSearchResponse>("/search/poi", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      keyword,
      mode: options.mode,
      extent: options.extent || [],
      geometry: options.geometry || {}
    })
  });
}

export async function uploadDataset(projectId: string, formData: FormData): Promise<{ job_id: string }> {
  formData.set("project_id", projectId);
  return requestJson<{ job_id: string }>("/datasets/upload", {
    method: "POST",
    body: formData
  });
}

export async function exportSnapshot(
  projectId: string,
  title: string,
  imageDataUrl: string,
  note = ""
): Promise<{ artifact: ArtifactRecord }> {
  return requestJson<{ artifact: ArtifactRecord }>("/exports/snapshot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, title, image_data_url: imageDataUrl, note })
  });
}

export async function fetchOutputs(projectId: string): Promise<{ items: ArtifactRecord[] }> {
  return requestJson<{ items: ArtifactRecord[] }>(`/outputs?project_id=${encodeURIComponent(projectId)}`);
}

export async function fetchJob(jobId: string): Promise<JobRecord> {
  return requestJson<JobRecord>(`/jobs/${jobId}`);
}

export async function fetchLessons(): Promise<{ status: string; items: LessonRecord[] }> {
  return requestJson<{ status: string; items: LessonRecord[] }>("/lessons");
}

export async function fetchLesson(lessonId: string): Promise<LessonRecord & { status: string }> {
  return requestJson<LessonRecord & { status: string }>(`/lessons/${encodeURIComponent(lessonId)}`);
}

export async function createLessonDesign(
  projectId: string,
  baseLessonId = "",
  requirements: Record<string, unknown> = {}
): Promise<LessonDesignSession & { status: string; capabilities?: unknown[] }> {
  return requestJson(`/lesson-design/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, base_lesson_id: baseLessonId, requirements })
  });
}

export async function fetchLessonDesign(designId: string): Promise<LessonDesignSession & { status: string }> {
  return requestJson(`/lesson-design/sessions/${encodeURIComponent(designId)}`);
}

export async function turnLessonDesign(
  designId: string,
  message: string,
  revision?: number,
  step?: string
): Promise<LessonDesignTurnResult> {
  return requestJson(`/lesson-design/sessions/${encodeURIComponent(designId)}/turns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, expected_revision: revision, step })
  });
}

export async function resolveLessonDesignSection(
  designId: string,
  sectionId: string,
  decision: "accept" | "revise" | "edit",
  teacherNote = "",
  revision?: number,
  value?: unknown
): Promise<{ status: string; design: LessonDesignSession }> {
  return requestJson(`/lesson-design/sessions/${encodeURIComponent(designId)}/sections/${encodeURIComponent(sectionId)}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, teacher_note: teacherNote, expected_revision: revision, value })
  });
}

export async function finalizeLessonDesign(
  designId: string,
  revision?: number,
  applyBase = false
): Promise<{ status: string; lesson: LessonRecord; design: LessonDesignSession; capability_report: Record<string, unknown> }> {
  return requestJson(`/lesson-design/sessions/${encodeURIComponent(designId)}/finalize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_revision: revision, apply_base: applyBase })
  });
}

export async function exportLessonDocx(
  lessonId: string,
  projectId: string,
  designId = ""
): Promise<{ status: string; artifact: ArtifactRecord; job_id: string }> {
  return requestJson(`/lessons/${encodeURIComponent(lessonId)}/exports/docx`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, design_id: designId })
  });
}

// ------------------------------------------------------------------
// 题库（question bank）
// ------------------------------------------------------------------

export async function importQuestionBanks(
  projectId: string,
  files: File[]
): Promise<{ job_id: string }> {
  const formData = new FormData();
  formData.set("project_id", projectId);
  for (const file of files) {
    formData.append("files", file);
  }
  return requestJson<{ job_id: string }>("/question-banks/import", {
    method: "POST",
    body: formData
  });
}

export async function fetchQuestionBanks(projectId: string): Promise<{ status: string; items: QuestionBankSummary[] }> {
  return requestJson(`/question-banks?project_id=${encodeURIComponent(projectId)}`);
}

export async function deleteQuestionBank(bankId: string): Promise<{ status: string }> {
  return requestJson(`/question-banks/${encodeURIComponent(bankId)}`, { method: "DELETE" });
}

export async function fetchQuestionBankQuestions(
  bankId: string,
  options: {
    section?: string;
    type?: string;
    answerComplete?: boolean;
    search?: string;
    page?: number;
    pageSize?: number;
  } = {}
): Promise<{ status: string; items: QuestionBankQuestion[]; total: number; page: number; page_size: number }> {
  const params = new URLSearchParams();
  if (options.section) params.set("section", options.section);
  if (options.type) params.set("type", options.type);
  if (options.answerComplete !== undefined) params.set("answer_complete", String(options.answerComplete));
  if (options.search) params.set("search", options.search);
  if (options.page) params.set("page", String(options.page));
  if (options.pageSize) params.set("page_size", String(options.pageSize));
  const query = params.toString();
  return requestJson(`/question-banks/${encodeURIComponent(bankId)}/questions${query ? `?${query}` : ""}`);
}

export async function fetchQuestionBankGroup(
  bankId: string,
  groupKey: string
): Promise<{ status: string; group: QuestionBankGroup }> {
  return requestJson(`/question-banks/${encodeURIComponent(bankId)}/groups/${encodeURIComponent(groupKey)}`);
}

export async function searchQuestionBanks(payload: {
  project_id: string;
  bank_ids?: string[];
  topic?: string;
  knowledge?: string;
  objectives?: string[];
  type?: string;
  exclude_ids?: string[];
  limit?: number;
}): Promise<{
  status: string;
  items: QuestionBankQuestion[];
  candidates_count: number;
  generator: string;
  query: Record<string, unknown>;
}> {
  return requestJson("/question-banks/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: payload.project_id,
      bank_ids: payload.bank_ids || [],
      topic: payload.topic || "",
      knowledge: payload.knowledge || "",
      objectives: payload.objectives || [],
      type: payload.type || "",
      exclude_ids: payload.exclude_ids || [],
      limit: payload.limit ?? 5
    })
  });
}

export async function bindLessonDesignQuestion(
  designId: string,
  payload: {
    stage_id: string;
    question_id?: string;
    manual?: Record<string, unknown>;
    action?: "add" | "remove";
    position?: number | null;
    expected_revision?: number;
  }
): Promise<{ status: string; message: string; design: LessonDesignSession; stage: LessonStage }> {
  return requestJson(`/lesson-design/sessions/${encodeURIComponent(designId)}/questions/bind`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      stage_id: payload.stage_id,
      question_id: payload.question_id || "",
      manual: payload.manual || null,
      action: payload.action || "add",
      position: payload.position ?? null,
      expected_revision: payload.expected_revision
    })
  });
}

// ------------------------------------------------------------------
// 上课模拟测试（lesson rehearsal）
// ------------------------------------------------------------------

export async function createLessonRehearsal(
  projectId: string,
  lessonId: string
): Promise<{ status: string; rehearsal: LessonRehearsalRecord; resumed: boolean }> {
  return requestJson("/lesson-rehearsals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, lesson_id: lessonId })
  });
}

export async function fetchLessonRehearsal(rehearsalId: string): Promise<{ status: string; rehearsal: LessonRehearsalRecord }> {
  return requestJson(`/lesson-rehearsals/${encodeURIComponent(rehearsalId)}`);
}

export async function listLessonRehearsals(
  projectId: string,
  lessonId = ""
): Promise<{ status: string; items: LessonRehearsalRecord[] }> {
  const params = new URLSearchParams({ project_id: projectId });
  if (lessonId) params.set("lesson_id", lessonId);
  return requestJson(`/lesson-rehearsals?${params.toString()}`);
}

export async function updateLessonRehearsal(
  rehearsalId: string,
  payload: {
    patch?: Record<string, unknown>;
    question_bind?: {
      stage_id: string;
      question_id?: string;
      manual?: Record<string, unknown>;
      position?: number | null;
    };
    question_remove?: { stage_id: string; question_id: string };
    image_bind?: {
      stage_id: string;
      question_id: string;
      image: { url: string; width?: number; height?: number; order?: number };
    };
    scene_capture?: { stage_id: string; snapshot: SceneSnapshot };
    test_result?: { key: string; passed: boolean; note?: string };
    expected_revision?: number;
  }
): Promise<{ status: string; rehearsal: LessonRehearsalRecord }> {
  return requestJson(`/lesson-rehearsals/${encodeURIComponent(rehearsalId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function applyRehearsalStageScene(
  rehearsalId: string,
  stageId: string
): Promise<{ status: string; visualization?: unknown; globe?: import("./types").LessonGlobeScene }> {
  return requestJson(`/lesson-rehearsals/${encodeURIComponent(rehearsalId)}/apply-scene`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stage_id: stageId })
  });
}

export async function fetchLessonRehearsalReport(
  rehearsalId: string
): Promise<{ status: string; rehearsal_id: string; revision: number; report: LessonRehearsalReport }> {
  return requestJson(`/lesson-rehearsals/${encodeURIComponent(rehearsalId)}/report`);
}

export async function completeLessonRehearsal(
  rehearsalId: string,
  expectedRevision?: number
): Promise<LessonRehearsalCompleteResult> {
  return requestJson(`/lesson-rehearsals/${encodeURIComponent(rehearsalId)}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_revision: expectedRevision })
  });
}

export async function cancelLessonRehearsal(
  rehearsalId: string
): Promise<{ status: string; rehearsal: LessonRehearsalRecord }> {
  return requestJson(`/lesson-rehearsals/${encodeURIComponent(rehearsalId)}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" }
  });
}

export async function updateLesson(
  lessonId: string,
  payload: Partial<Pick<LessonRecord, "title" | "subject" | "grade" | "objectives" | "stages" | "metadata" | "plan">>
): Promise<LessonRecord & { status: string }> {
  return requestJson<LessonRecord & { status: string }>(`/lessons/${encodeURIComponent(lessonId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function importLesson(projectId: string, text: string): Promise<{ job_id: string }> {
  return requestJson<{ job_id: string }>("/lessons/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, text })
  });
}

export async function applyLessonScene(
  lessonId: string,
  stageId: string,
  projectId: string
): Promise<{ status: string; visualization?: unknown; globe?: import("./types").LessonGlobeScene }> {
  return requestJson<{ status: string; visualization?: unknown; globe?: import("./types").LessonGlobeScene }>(
    `/lessons/${encodeURIComponent(lessonId)}/stages/${encodeURIComponent(stageId)}/scene/apply`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId })
    }
  );
}

export async function captureLessonScene(
  lessonId: string,
  stageId: string,
  snapshot: SceneSnapshot
): Promise<{ status: string; scene: unknown }> {
  return requestJson<{ status: string; scene: unknown }>(
    `/lessons/${encodeURIComponent(lessonId)}/stages/${encodeURIComponent(stageId)}/scene/capture`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ snapshot })
    }
  );
}

export async function createClassSession(lessonId: string, projectId: string): Promise<ClassSessionResponse> {
  return requestJson<ClassSessionResponse>("/class-sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lesson_id: lessonId, project_id: projectId })
  });
}

export async function fetchClassSessions(params: {
  lessonId?: string;
  projectId?: string;
} = {}): Promise<{ status: string; items: ClassSessionRecord[] }> {
  const query = new URLSearchParams();
  if (params.lessonId) query.set("lesson_id", params.lessonId);
  if (params.projectId) query.set("project_id", params.projectId);
  return requestJson<{ status: string; items: ClassSessionRecord[] }>(
    `/class-sessions${query.toString() ? `?${query}` : ""}`
  );
}

export async function endClassSession(sessionId: string): Promise<ClassSessionResponse> {
  return requestJson<ClassSessionResponse>(`/class-sessions/${encodeURIComponent(sessionId)}/end`, {
    method: "POST"
  });
}

export async function enterSessionStage(
  sessionId: string,
  stageId: string
): Promise<{ status: string; session_id: string; scene?: { globe?: import("./types").LessonGlobeScene } }> {
  return requestJson<{ status: string; session_id: string; scene?: { globe?: import("./types").LessonGlobeScene } }>(`/class-sessions/${encodeURIComponent(sessionId)}/stage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stage_id: stageId })
  });
}

export async function fetchPopulationSources(
  projectId: string,
  version = ""
): Promise<{ status: string; version: string; pack_fingerprint: string; items: PopulationSourceCard[] }> {
  const query = new URLSearchParams({ project_id: projectId });
  if (version) query.set("version", version);
  return requestJson(`/population-sources?${query.toString()}`);
}

export async function fetchPopulationSourceVersions(
  projectId: string
): Promise<{ status: string; active_version: string; versions: PopulationSourceVersion[] }> {
  return requestJson(`/population-sources/versions?project_id=${encodeURIComponent(projectId)}`);
}

export async function activatePopulationSourceVersion(
  projectId: string,
  version: string
): Promise<{ status: string; active_version: string; pack_fingerprint: string }> {
  return requestJson(`/projects/${encodeURIComponent(projectId)}/population-source-version`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ version })
  });
}

export async function preparePopulationLesson(
  projectId: string,
  lessonId: string,
  input: PopulationLessonPrepInput
): Promise<{ status: string; capability: string; job_id: string; lesson_id: string }> {
  return requestJson("/lesson-prep/population", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      lesson_id: lessonId,
      ...input
    })
  });
}

export async function resolvePopulationLessonPrep(
  changeSetId: string,
  decision: "apply" | "reject",
  acceptedStageIds: string[] = []
): Promise<{ status: string; decision: string; lesson?: LessonRecord }> {
  return requestJson(`/lesson-prep/change-sets/${encodeURIComponent(changeSetId)}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, accepted_stage_ids: acceptedStageIds })
  });
}

export function populationLessonPrepResult(job: JobRecord): PopulationLessonPrepResult | null {
  if (job.status !== "completed" || !job.result?.change_set) {
    return null;
  }
  return job.result as unknown as PopulationLessonPrepResult;
}

export async function launchSessionQuestion(
  sessionId: string,
  payload: {
    question_id?: string;
    stage_id?: string;
    adhoc?: Record<string, unknown>;
    delivery?: "student" | "teacher_oral";
  }
): Promise<{ status: string; active_question: Record<string, unknown> }> {
  return requestJson<{ status: string; active_question: Record<string, unknown> }>(
    `/class-sessions/${encodeURIComponent(sessionId)}/questions/launch`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }
  );
}

export async function closeSessionQuestion(sessionId: string): Promise<{ status: string }> {
  return requestJson<{ status: string }>(`/class-sessions/${encodeURIComponent(sessionId)}/questions/close`, {
    method: "POST"
  });
}

export async function addSessionObservation(
  sessionId: string,
  payload: { stage_id?: string; question_id?: string; verdict: string; tag?: string; note?: string }
): Promise<{ status: string }> {
  return requestJson<{ status: string }>(`/class-sessions/${encodeURIComponent(sessionId)}/observations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function logSessionEvent(
  sessionId: string,
  payload: { event_type: "snapshot" | "annotation" | "note" | "assistant_exchange"; stage_id?: string; payload?: Record<string, unknown> }
): Promise<{ status: string }> {
  return requestJson<{ status: string }>(`/class-sessions/${encodeURIComponent(sessionId)}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function fetchSessionLive(sessionId: string): Promise<SessionLiveState> {
  return requestJson<SessionLiveState>(`/class-sessions/${encodeURIComponent(sessionId)}/live`);
}

export async function generateSessionReport(sessionId: string): Promise<{ status: string; job_id: string }> {
  return requestJson<{ status: string; job_id: string }>(`/class-sessions/${encodeURIComponent(sessionId)}/report`, {
    method: "POST"
  });
}

export async function fetchKbManifest(): Promise<KnowledgeManifestResponse> {
  return requestJson<KnowledgeManifestResponse>("/kb/manifest");
}

export async function fetchKbTopics(): Promise<KnowledgeTopicsResponse> {
  return requestJson<KnowledgeTopicsResponse>("/kb/topics");
}

export async function searchKb(params: {
  query?: string;
  topic?: string;
  region?: string;
  tag?: string;
  limit?: number;
}): Promise<KnowledgeSearchResponse> {
  const query = new URLSearchParams();
  if (params.query) {
    query.set("query", params.query);
  }
  if (params.topic) {
    query.set("topic", params.topic);
  }
  if (params.region) {
    query.set("region", params.region);
  }
  if (params.tag) {
    query.set("tag", params.tag);
  }
  query.set("limit", String(params.limit ?? 20));
  return requestJson<KnowledgeSearchResponse>(`/kb/search?${query.toString()}`);
}

export async function upsertKbItem(item: Partial<KnowledgeBaseItem>): Promise<KnowledgeLayerRegisterResponse> {
  return requestJson<KnowledgeLayerRegisterResponse>("/kb/items", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item })
  });
}

export async function registerKbLayer(
  projectId: string,
  layerId: string,
  metadata: Record<string, unknown> = {}
): Promise<KnowledgeLayerRegisterResponse> {
  return requestJson<KnowledgeLayerRegisterResponse>("/kb/layers/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      layer_id: layerId,
      metadata
    })
  });
}

export async function searchResources(params: {
  query?: string;
  scope?: "all" | "kb" | "web" | "materials";
  limit?: number;
}): Promise<ResourceSearchResponse> {
  const query = new URLSearchParams();
  if (params.query) {
    query.set("query", params.query);
  }
  query.set("scope", params.scope || "all");
  query.set("limit", String(params.limit ?? 12));
  return requestJson<ResourceSearchResponse>(`/resources/search?${query.toString()}`);
}

export async function uploadKbMaterial(
  kbItemId: string,
  formData: FormData,
  regionBinding: RegionBinding = {}
): Promise<MaterialWriteResponse> {
  formData.set("kb_item_id", kbItemId);
  formData.set("region_binding", JSON.stringify(regionBinding));
  return requestJson<MaterialWriteResponse>("/kb/materials/upload", {
    method: "POST",
    body: formData
  });
}

export async function createKbMaterialLink(payload: {
  kb_item_id: string;
  url: string;
  title?: string;
  description?: string;
  material_type?: string;
  thumbnail_url?: string;
  region_binding?: RegionBinding;
}): Promise<MaterialWriteResponse> {
  return requestJson<MaterialWriteResponse>("/kb/materials/link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function fetchLessonResources(projectId: string): Promise<LessonResourceResponse> {
  return requestJson<LessonResourceResponse>(`/projects/${projectId}/lesson-resources`);
}

export async function saveLessonResourceSet(
  projectId: string,
  item: Partial<LessonResourceSet>
): Promise<LessonResourceResponse & { item: LessonResourceSet }> {
  return requestJson<LessonResourceResponse & { item: LessonResourceSet }>(`/projects/${projectId}/lesson-resources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item })
  });
}

export async function activateLessonResourceSet(
  projectId: string,
  setId: string,
  patch: Partial<LessonResourceSet> = { active: true }
): Promise<LessonResourceResponse> {
  return requestJson<LessonResourceResponse>(`/projects/${projectId}/lesson-resources/${encodeURIComponent(setId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patch })
  });
}


// ── Teaching Maps ──────────────────────────────────────────

export interface TeachingMapItem {
  id: string;
  name: string;
  category: string;
  category_order: number;
  bounds: [number, number, number, number];
  view: { center: [number, number]; zoom: number };
  opacity: number;
  keywords: string[];
  asset_url: string;
}

export interface TeachingMapsResponse {
  status: string;
  items: TeachingMapItem[];
}

export interface TeachingMapToggleResponse {
  status: string;
  layer: Record<string, any> | null;
  view: { center?: [number, number]; zoom?: number };
}

export async function fetchTeachingMaps(): Promise<TeachingMapsResponse> {
  return requestJson<TeachingMapsResponse>("/teaching-maps");
}

export async function toggleTeachingMap(
  projectId: string,
  mapId: string,
  visible: boolean
): Promise<TeachingMapToggleResponse> {
  return requestJson<TeachingMapToggleResponse>(`/projects/${projectId}/teaching-maps/${encodeURIComponent(mapId)}/toggle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ visible })
  });
}

export async function fetchActiveTeachingMaps(
  projectId: string
): Promise<{ status: string; active: string[] }> {
  return requestJson<{ status: string; active: string[] }>(`/projects/${projectId}/teaching-maps/active`);
}

// ---------------------------------------------------------------------------
// GIS workflow API
// ---------------------------------------------------------------------------

export async function listWorkflowTemplates(): Promise<WorkflowTemplatesResponse> {
  return requestJson<WorkflowTemplatesResponse>("/workflow/templates");
}

export async function submitWorkflow(payload: {
  project_id: string;
  message: string;
  mode?: string;
  template_id?: string;
  parameters?: Record<string, unknown>;
}): Promise<WorkflowSubmitResponse> {
  return requestJson<WorkflowSubmitResponse>("/workflow/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: payload.project_id,
      message: payload.message,
      mode: payload.mode || "template",
      template_id: payload.template_id || "",
      parameters: payload.parameters || {}
    })
  });
}

export async function fetchWorkflow(workflowId: string): Promise<WorkflowRecord & { status: string }> {
  return requestJson<WorkflowRecord & { status: string }>(`/workflow/${encodeURIComponent(workflowId)}`);
}

export async function fetchWorkflowArtifacts(
  workflowId: string
): Promise<WorkflowArtifactsResponse> {
  return requestJson<WorkflowArtifactsResponse>(`/workflow/${encodeURIComponent(workflowId)}/artifacts`);
}

export async function fetchWorkflowHistory(projectId: string): Promise<WorkflowHistoryResponse> {
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return requestJson<WorkflowHistoryResponse>(`/workflow/history${query}`);
}

export function buildWorkflowStreamUrl(workflowId: string): string {
  return `${API_BASE}/workflow/${encodeURIComponent(workflowId)}/stream`;
}

export function buildWorkflowFileUrl(publicUrl: string): string {
  if (!publicUrl) {
    return "";
  }
  if (/^https?:\/\//i.test(publicUrl)) {
    return publicUrl;
  }
  return `${API_BASE}${publicUrl.startsWith("/") ? publicUrl : `/${publicUrl}`}`;
}

export function buildPublicFileUrl(publicUrl: string): string {
  if (!publicUrl) {
    return "";
  }
  if (/^https?:\/\//i.test(publicUrl)) {
    return publicUrl;
  }
  return `${API_BASE}${publicUrl.startsWith("/") ? publicUrl : `/${publicUrl}`}`;
}

export async function renderPptx(file: File): Promise<PptRenderResponse> {
  const formData = new FormData();
  formData.set("file", file);
  const response = await requestJson<PptRenderResponse>("/ppt/render", {
    method: "POST",
    body: formData
  });
  return {
    ...response,
    slides: response.slides.map((slide) => ({
      ...slide,
      image_url: buildPublicFileUrl(slide.image_url)
    }))
  };
}

// ── Timeline API ────────────────────────────────────────────

export async function generateTimeline(
  projectId: string,
  formData: FormData
): Promise<TimelineGenerateResponse> {
  return requestJson<TimelineGenerateResponse>(
    `/projects/${encodeURIComponent(projectId)}/timeline/generate`,
    { method: "POST", body: formData }
  );
}

export async function fetchTimeline(projectId: string): Promise<{
  status: string;
  timeline: TimelineData | null;
}> {
  return requestJson(`/projects/${encodeURIComponent(projectId)}/timeline`);
}

export async function updateTimeline(
  projectId: string,
  patch: Record<string, unknown>
): Promise<TimelineSaveResponse> {
  return requestJson<TimelineSaveResponse>(
    `/projects/${encodeURIComponent(projectId)}/timeline`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patch }),
    }
  );
}
