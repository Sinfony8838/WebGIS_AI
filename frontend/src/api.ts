import type {
  AssistantTarget,
  ArtifactRecord,
  BasemapCatalog,
  BasemapPreset,
  HealthResponse,
  JobRecord,
  LlmStatusResponse,
  LayersResponse,
  MapContext,
  PoiSearchResponse,
  ProjectRecord,
  QgisLayersResponse,
  QgisStatusResponse,
  QgisToolResponse
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

export function buildQgisPreviewUrl(filePath: string, stamp: number): string {
  const normalized = filePath.trim();
  return `${API_BASE}/qgis/preview?file_path=${encodeURIComponent(normalized)}&t=${stamp}`;
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

export async function fetchQgisLayers(): Promise<QgisLayersResponse> {
  return requestJson<QgisLayersResponse>("/qgis/layers");
}

export async function executeQgisTool(
  toolName: string,
  toolParams: Record<string, unknown> = {}
): Promise<QgisToolResponse> {
  return requestJson<QgisToolResponse>(`/qgis/tools/${encodeURIComponent(toolName)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool_params: toolParams })
  });
}

export async function focusQgis(): Promise<QgisToolResponse> {
  return requestJson<QgisToolResponse>("/qgis/focus", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({})
  });
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
  target: AssistantTarget = "webgis"
): Promise<{ job_id: string }> {
  return requestJson<{ job_id: string }>("/assistant/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, message, map_context: mapContext, target })
  });
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
