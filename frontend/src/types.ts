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
  /**
   * Whether the backend considers this raster layer safe to use as a
   * Cesium ImageryProvider in the 3D globe view. Weather overlays and
   * vector-only tiles typically opt out (false). Default is true.
   */
  usable_in_3d?: boolean;
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
export type AssistantTarget = "webgis";
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
  gis_workflow?: {
    enabled: boolean;
    engine?: string;
    qgis_root?: string;
    init_warning?: Record<string, unknown> | null;
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


// ---------------------------------------------------------------------------
// GIS workflow types (PyQGIS worker is a backend implementation detail)
// ---------------------------------------------------------------------------

export type WorkflowStatus = "pending" | "running" | "success" | "error" | "cancelled";
export type WorkflowStepStatus = "pending" | "running" | "success" | "error" | "skipped";

export type WorkflowError = {
  code: string;
  message: string;
  user_friendly: string;
  step_id?: string;
  details?: Record<string, unknown>;
};

export type WorkflowStepRecord = {
  id: string;
  op: string;
  status: WorkflowStepStatus;
  outputs: Record<string, unknown>;
  error: WorkflowError | null;
  started_at: string;
  finished_at: string;
};

export type WorkflowArtifactRecord = {
  artifact_id: string;
  workflow_id: string;
  kind: "geojson" | "style" | "stats" | "png" | "summary" | "layout_pdf" | "other" | string;
  title: string;
  relative_path: string;
  public_url: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type WorkflowRecord = {
  workflow_id: string;
  project_id: string;
  user_message: string;
  intent: string;
  template_id: string;
  mode: string;
  workflow_json: Record<string, unknown>;
  status: WorkflowStatus;
  steps: WorkflowStepRecord[];
  artifacts: WorkflowArtifactRecord[];
  error: WorkflowError | null;
  created_at: string;
  updated_at: string;
  started_at: string;
  finished_at: string;
};

export type WorkflowSubmitResponse = {
  status: string;
  workflow_id: string;
  workflow_status: WorkflowStatus;
  intent: string;
  template_id: string;
  parameters: Record<string, unknown>;
  error?: WorkflowError | null;
};

export type WorkflowTemplateInfo = {
  id: string;
  title: string;
  description: string;
};

export type WorkflowTemplatesResponse = {
  status: string;
  items: WorkflowTemplateInfo[];
};

export type WorkflowArtifactsResponse = {
  status: string;
  workflow_id: string;
  artifacts: WorkflowArtifactRecord[];
};

export type WorkflowHistoryResponse = {
  status: string;
  items: WorkflowRecord[];
};

export type WorkflowEventType =
  | "workflow_created"
  | "workflow_started"
  | "step_started"
  | "step_progress"
  | "step_success"
  | "step_error"
  | "artifact_ready"
  | "workflow_success"
  | "workflow_error"
  | "stream_idle_timeout"
  | "ping";

export type WorkflowEvent = {
  type: WorkflowEventType;
  payload: Record<string, unknown>;
};

// ---------------------------------------------------------------------------
// style.json (graduated/choropleth) — used by OpenLayers style function
// ---------------------------------------------------------------------------

export type GraduatedStyleClass = {
  min: number;
  max: number;
  color: string;
  label?: string;
};

export type GraduatedStyleLegendItem = {
  label: string;
  color: string;
};

export type GraduatedStyle = {
  type: "graduated";
  field: string;
  method?: string;
  classes: GraduatedStyleClass[];
  stroke?: { color?: string; width?: number };
  default?: { color?: string };
  legend?: { title?: string; items: GraduatedStyleLegendItem[] };
  title?: string;
};

export type StatsRow = Record<string, string | number | boolean | null | undefined>;

export type StatsPayload = {
  title?: string;
  fields?: string[];
  rows?: StatsRow[];
  all_rows_count?: number;
  summary?: Record<string, number | string>;
};

// ── PPT types ────────────────────────────────────────────────

export type SlideContent = {
  index: number;
  html: string;
  imageUrl?: string;
  bgColor?: string;
  images: Record<string, string>; // rId -> object URL
  width: number;  // EMU
  height: number; // EMU
  renderer?: string;
};

export type PptxParsedPresentation = {
  fileName: string;
  slideWidth: number;
  slideHeight: number;
  slides: SlideContent[];
};

export type PptRenderSlide = {
  index: number;
  image_url: string;
  width: number;
  height: number;
};

export type PptRenderResponse = {
  status: string;
  file_name: string;
  renderer: string;
  slide_width: number;
  slide_height: number;
  slides: PptRenderSlide[];
  attempts?: Array<Record<string, string>>;
};

// ── Timeline types ───────────────────────────────────────────

export type TimelineNode = {
  id: string;
  order: number;
  stage: string;
  title: string;
  description: string;
  durationMin: number;
  active: boolean;
};

export type TimelineData = {
  id: string;
  project_id: string;
  source_file_name: string;
  title: string;
  totalDurationMin: number;
  nodes: TimelineNode[];
  created_at: string;
  updated_at: string;
};

export type TimelineGenerateResponse = {
  status: string;
  timeline: TimelineData;
};

export type TimelineSaveResponse = {
  status: string;
  timeline: TimelineData;
};
