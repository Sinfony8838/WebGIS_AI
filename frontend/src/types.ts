export type BasemapLayerDescriptor = {
  layer_id: string;
  title: string;
  kind: string;
  urls: string[];
  attribution?: string;
  opacity: number;
  z_index: number;
  class_name?: string;
  cross_origin?: string;
};

export type BasemapPreset = {
  id: string;
  title: string;
  description: string;
  type: string;
  provider: string;
  layers: BasemapLayerDescriptor[];
  legacy?: boolean;
};

export type BasemapCatalog = {
  status?: string;
  default_id: string;
  items: BasemapPreset[];
};

export type LayerRecord = {
  layer_id: string;
  name: string;
  kind: string;
  source: string;
  geometry_type: string;
  visible: boolean;
  opacity: number;
  z_index: number;
  style: Record<string, unknown>;
  data: Record<string, unknown>;
  metadata: Record<string, unknown>;
};

export type ArtifactRecord = {
  artifact_id: string;
  project_id: string;
  job_id: string;
  artifact_type: string;
  title: string;
  path: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type RecentAction = {
  title: string;
  detail: string;
  status: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
};

export type ProjectRecord = {
  project_id: string;
  name: string;
  metadata: Record<string, unknown>;
  view: {
    center: [number, number];
    zoom: number;
    extent?: [number, number, number, number];
  };
  base_map: BasemapPreset;
  active_layer_id: string;
  enabled_templates: string[];
  recent_actions: RecentAction[];
  layers: LayerRecord[];
};

export type LayersResponse = {
  status: string;
  items: LayerRecord[];
  active_layer_id: string;
  view: {
    center: [number, number];
    zoom: number;
    extent?: [number, number, number, number];
  };
  enabled_templates: string[];
  recent_actions: RecentAction[];
  base_map: BasemapPreset;
};

export type JobRecord = {
  job_id: string;
  project_id: string;
  job_type: string;
  title: string;
  workflow_type: string;
  status: string;
  updated_at: string;
  steps: Array<{ title: string; detail: string; status: string; timestamp: string }>;
  stages: Record<string, { status: string; summary: string; detail: string }>;
  result?: {
    summary?: string;
    assistant_message?: string;
    intent?: string;
    knowledge?: KnowledgeAnswer | null;
    citations?: CitationRecord[];
    actions?: Array<{ tool_name: string; tool_params: Record<string, unknown> }>;
    actions_planned?: Array<{
      name: string;
      target: string;
      category: string;
      risk_level: string;
      reversible: boolean;
      requires_confirmation: boolean;
      requires_map_context: boolean;
      tool_params: Record<string, unknown>;
    }>;
    actions_executed?: Array<{
      action: { tool_name: string; tool_params: Record<string, unknown> };
      risk_level?: string;
      result?: Record<string, unknown>;
    }>;
    requires_confirmation?: boolean;
    confirmation_id?: string;
    confirmation_status?: string;
    confirmation_expires_at?: string;
    plan_fingerprint?: string;
    planner?: string;
    retrieval_trace?: Array<Record<string, unknown>>;
    conversation_id?: string;
    prompt_parts?: Record<string, unknown>;
    permission_context?: Record<string, unknown>;
    artifacts?: Record<string, ArtifactRecord>;
    [key: string]: unknown;
  };
  error?: string;
};

export type ChatMessage = {
  role: "assistant" | "user" | "system";
  text: string;
  timestamp: string;
};

export type CitationRecord = {
  title: string;
  url: string;
};

export type KnowledgeAnswer = {
  direct_answer: string;
  mechanism_explanation: string;
  map_grounding: string;
  teaching_points: string[];
  citations: CitationRecord[];
  confidence: number;
  answer_type: string;
  llm_used?: boolean;
};

export type AssistantMode = "knowledge" | "tool";
export type AssistantTarget = "webgis" | "qgis" | "auto";
export type AssistantInputMode = "text" | "voice";

export type MapContext = {
  center: [number, number];
  zoom: number;
  extent: [number, number, number, number];
  active_layer_id?: string;
  visible_layers: Array<{ layer_id: string; name: string }>;
  recent_actions: RecentAction[];
  basemap_id?: string;
    search_area_geometry?: Record<string, unknown> | null;
    selected_feature_summary?: string;
    selected_region?: Record<string, unknown>;
    active_lesson_materials?: Array<{ id: string; title: string; type: string; region_binding?: RegionBinding }>;
  };

export type ScreenSnapshot = {
  image_data_url: string;
  width: number;
  height: number;
  captured_at: string;
};

export type TemplateItem = {
  template_id: string;
  title: string;
  description: string;
  chapter_id?: string;
  chapter_title?: string;
  chapter_order?: number;
  unit_id?: string;
  unit_title?: string;
  unit_order?: number;
  template_order?: number;
};

export type PoiSearchItem = {
  poi_id: string;
  name: string;
  address: string;
  type: string;
  district: string;
  city: string;
  location: [number, number];
};

export type PoiSearchResponse = {
  status: string;
  keyword: string;
  mode: string;
  items: PoiSearchItem[];
  layer: LayerRecord;
  summary: string;
};

export type KnowledgeCitation = {
  title: string;
  url: string;
};

export type RegionBinding = {
  layer_id?: string;
  feature_id?: string;
  admin_code?: string;
  name?: string;
  name_field?: string;
};

export type TeachingMaterial = {
  id: string;
  title: string;
  type: "image" | "video" | "animation" | "document" | "link" | string;
  source: string;
  url: string;
  thumbnail_url: string;
  description: string;
  region_binding: RegionBinding;
  sort_order: number;
  created_at: string;
};

export type KnowledgeDatasetRef = {
  project_id?: string;
  layer_id?: string;
  layer_name?: string;
  source_file?: string;
  [key: string]: unknown;
};

export type KnowledgeBaseItem = {
  id: string;
  title: string;
  topic: string;
  region: string;
  time: string;
  status?: "knowledge_only" | "renderable_layer" | "stored_only" | string;
  source: string;
  license: string;
  grade_level: string;
  keywords: string[];
  tags: string[];
  crs: string;
  summary: string;
  canonical_answer: string;
  teaching_points: string[];
  citations: KnowledgeCitation[];
  dataset_refs: KnowledgeDatasetRef[];
  materials: TeachingMaterial[];
  related_templates: unknown[];
  updated_at: string;
};

export type KnowledgeManifestResponse = {
  status: string;
  path: string;
  version: string;
  updated_at: string;
  items: KnowledgeBaseItem[];
};

export type KnowledgeSearchResponse = {
  status: string;
  query: string;
  topic: string;
  region: string;
  tag: string;
  total: number;
  items: KnowledgeBaseItem[];
};

export type KnowledgeLayerRegisterResponse = {
  status: string;
  item: KnowledgeBaseItem;
};

export type ResourceSearchResult = {
  id: string;
  title: string;
  source: string;
  type: string;
  summary: string;
  url: string;
  thumbnail_url: string;
  citations: KnowledgeCitation[];
  confidence: number;
  material?: TeachingMaterial;
  kb_item?: KnowledgeBaseItem;
};

export type ResourceSearchResponse = {
  status: string;
  query: string;
  scope: "all" | "kb" | "web" | "materials" | string;
  total: number;
  items: ResourceSearchResult[];
  trace: Array<{ source: string; status: string; count?: string; detail?: string }>;
};

export type LessonResourceSet = {
  id: string;
  title: string;
  project_id: string;
  item_ids: string[];
  material_ids: string[];
  region_bindings: RegionBinding[];
  active: boolean;
  created_at: string;
  updated_at: string;
};

export type LessonResourceResponse = {
  status: string;
  items: LessonResourceSet[];
  active_lesson_resource_set_id: string;
};

export type MaterialWriteResponse = {
  status: string;
  material: TeachingMaterial;
};

export type KnowledgeTopicSummary = {
  topic: string;
  title: string;
  item_count: number;
  renderable_count: number;
  stored_only_count: number;
  knowledge_only_count: number;
  sample_titles: string[];
};

export type KnowledgeTopicsResponse = {
  status: string;
  items: KnowledgeTopicSummary[];
};

export type HealthResponse = {
  status: string;
  ui: {
    mode: string;
    assistant_tools: Array<{ name: string; description: string; parameters: Record<string, string> }>;
    assistant_v2_enabled?: boolean;
  };
  llm?: {
    enabled: boolean;
    configured?: boolean;
    provider: string;
    model: string;
    base_url?: string;
    provider_source?: string;
    api_key_source?: string;
    error?: string;
  };
  vision?: {
    enabled: boolean;
    configured?: boolean;
    provider: string;
    token_plan_key_source?: string;
  };
  qgis?: {
    enabled: boolean;
    host: string;
    port: number;
    reachable?: boolean;
    error?: string;
  };
  online_services: {
    amap_poi_enabled: boolean;
  };
  basemaps: BasemapCatalog;
  templates: TemplateItem[];
};

export type LlmStatusResponse = {
  status: string;
  enabled: boolean;
  configured?: boolean;
  provider: string;
  model: string;
  base_url?: string;
  provider_source?: string;
  api_key_source?: string;
  error?: string;
};

export type QgisStatusResponse = {
  status: string;
  enabled: boolean;
  host: string;
  port: number;
  reachable: boolean;
  health_mode?: string;
  response?: Record<string, unknown>;
  error?: string;
};

export type QgisLayersResponse = {
  status: string;
  result: Record<string, unknown>;
};

export type QgisToolResponse = {
  status: string;
  result?: Record<string, unknown>;
  message?: string;
  ok?: boolean;
};

export type ConversationResponse = {
  status: string;
  conversation_id: string;
  project_id: string;
  assistant_mode: AssistantMode;
  running_summary: string;
  task_memory: Record<string, unknown>;
  pinned_state: Record<string, unknown>;
  last_map_grounding: Record<string, unknown>;
  messages: Array<{
    message_id: string;
    conversation_id: string;
    role: "assistant" | "user" | "system";
    text: string;
    assistant_mode: AssistantMode;
    metadata: Record<string, unknown>;
    created_at: string;
  }>;
};
