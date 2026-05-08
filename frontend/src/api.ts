import type {
  AssistantMode,
  AssistantInputMode,
  AssistantTarget,
  ArtifactRecord,
  BasemapCatalog,
  BasemapPreset,
  ChatMessage,
  ConversationResponse,
  HealthResponse,
  JobRecord,
  KnowledgeBaseItem,
  KnowledgeLayerRegisterResponse,
  KnowledgeManifestResponse,
  LessonResourceResponse,
  LessonResourceSet,
  MaterialWriteResponse,
  KnowledgeSearchResponse,
  KnowledgeTopicsResponse,
  LlmStatusResponse,
  LayersResponse,
  MapContext,
  PoiSearchResponse,
  ProjectRecord,
  RegionBinding,
  ResourceSearchResponse,
  ScreenSnapshot,
  WorkflowArtifactsResponse,
  WorkflowHistoryResponse,
  WorkflowRecord,
  WorkflowSubmitResponse,
  WorkflowTemplatesResponse
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:18999";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function getApiBase(): string {
  return API_BASE;
}

export async function fetchHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/health");
}

export async function fetchLlmStatus(): Promise<LlmStatusResponse> {
  return requestJson<LlmStatusResponse>("/llm/status");
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
  }
): Promise<{ job_id: string; conversation_id?: string; assistant_mode?: AssistantMode }> {
  return requestJson<{ job_id: string; conversation_id?: string; assistant_mode?: AssistantMode }>("/assistant/messages", {
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
      screen_snapshot: options?.screenSnapshot || {}
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
// PyQGIS workflow API
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
