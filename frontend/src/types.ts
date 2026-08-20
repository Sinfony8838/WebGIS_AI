export type UserRole = "admin" | "teacher";
export type UserStatus = "active" | "disabled";

export type AuthUser = {
  user_id: string;
  email: string;
  nickname: string;
  role: UserRole;
  status: UserStatus;
  must_change_password: boolean;
  created_at: string;
  updated_at: string;
  last_login_at: string;
  locked_until: string;
  active_session_count?: number;
};

export type AuthSession = {
  status: string;
  user: AuthUser;
  csrf_token: string;
  expires_at?: string;
};

export type AuthBootstrapStatus = {
  status: string;
  auth_mode: "users" | "legacy_token" | "disabled";
  required: boolean;
};

export type AuthAuditLog = {
  audit_id: number;
  actor_user_id: string;
  action: string;
  target_user_id: string;
  outcome: string;
  detail: string;
  ip_address: string;
  created_at: string;
};

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
  /** 数据内容版本号：仅在 data 变化时递增，用于跳过未变化图层的 GeoJSON 重解析。 */
  data_rev?: number;
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

export type DatasetCatalogItem = {
  id: string;
  name: string;
  category: string;
  source: string;
  format: string;
  geometry_source?: string;
  join_key?: string;
  fields: string[];
  coverage: string;
  source_year: string;
  source_name: string;
  source_url: string;
  license: string;
  includes_taiwan: boolean;
  status: string;
  geometry_type: string;
  recommended_template: string;
  population_fields: string[];
  tags: string[];
  description: string;
};

export type DatasetCatalogResponse = {
  status: string;
  path: string;
  items: DatasetCatalogItem[];
  missing_requirements_path: string;
  missing_requirements_available: boolean;
};

export type DatasetCatalogLayerResponse = {
  status: string;
  layer: LayerRecord;
  view?: {
    center?: [number, number];
    zoom?: number;
    extent?: [number, number, number, number];
  };
};

export type GeoJsonFeature = {
  type: "Feature";
  properties: Record<string, unknown> | null;
  geometry: { type: string; coordinates: unknown } | null;
};

export type GeoJsonFeatureCollection = {
  type: "FeatureCollection";
  features: GeoJsonFeature[];
};

export type CatalogDatasetDataResponse = {
  status: string;
  dataset: DatasetCatalogItem;
  data: GeoJsonFeatureCollection;
};

export type DatasetStatRow = {
  name: string;
  region_code: string;
  population: number | null;
  area: number | null;
  density: number | null;
  coverage_ratio?: number;
  source_population?: number | null;
  source_area?: number | null;
  estimated?: boolean;
};

export type DatasetStatLayerSummary = {
  layer_id: string;
  name: string;
  catalog_id: string;
  feature_count: number;
  matched_count: number;
  total_population: number | null;
  total_area: number | null;
  density: number | null;
  rows: DatasetStatRow[];
  method: string;
};

export type DatasetStatsResponse = {
  status: string;
  summary: string;
  geometry_used: boolean;
  layers: DatasetStatLayerSummary[];
  totals: {
    matched_count: number;
    total_population: number | null;
    total_area: number | null;
    density: number | null;
  };
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
    teaching_contract?: TeachingContract | null;
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
    actions_executed?: ExecutedAction[];
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
  teaching_contract?: TeachingContract | null;
  /** Routed teaching intent (teaching_explain/question/action/reflect, knowledge, tool, hybrid) - drives the intent badge. */
  intent?: string | null;
  /** Tools the agent executed for this reply - drives the collapsible tool-use trace. */
  actions_executed?: ExecutedAction[] | null;
  image_attachment?: ImageAttachment | null;
};

export type ImageAttachment = {
  artifact_id: string;
  title: string;
  public_url: string;
  mime_type?: string;
};

export type CitationRecord = {
  title: string;
  url: string;
};

/**
 * A tool call the agent actually executed on the map. Persisted per
 * ChatMessage so the widget can render a collapsible tool-use trace under
 * the assistant reply (the most "agent" affordance - visible tool use).
 */
export type ExecutedAction = {
  action: { tool_name: string; tool_params: Record<string, unknown> };
  risk_level?: string;
  result?: Record<string, unknown>;
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

export type TeachingContract = {
  summary: string;
};

export type AssistantMode = "teaching" | "knowledge" | "tool";
export type AssistantTarget = "webgis" | "qgis";
export type AssistantInputMode = "text" | "voice";

/**
 * Where the teacher currently is in the lesson workflow. Sent with every
 * assistant request so the agent knows which lesson/session/stage it is
 * serving and can adapt routing and answer strategy per phase.
 */
export type TeachingContext = {
  lesson_id?: string;
  session_id?: string;
  stage_id?: string;
  phase?: "course_prep" | "in_class" | "post_class" | "";
};

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
    teaching_context?: TeachingContext;
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
    api_key_source?: string;
    billing?: string;
  };
  image_generation?: {
    enabled: boolean;
    configured?: boolean;
    provider: string;
    model: string;
    base_url?: string;
    api_key_source?: string;
    billing?: string;
    error?: string;
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

export type QgisStatusResponse = {
  reachable: boolean;
  host?: string;
  port?: number;
  status?: string;
  message?: string;
  [key: string]: unknown;
};

export type LessonMisconception = {
  tag: string;
  description: string;
};

export type LessonEvidenceRef = {
  source_id: string;
  title?: string;
  source_year?: string;
  fingerprint?: string;
};

export type LessonGlobeScene = {
  enabled?: boolean;
  themes?: string[];
  camera?: {
    lon?: number;
    lat?: number;
    altitudeMeters?: number;
    pitchDeg?: number;
  };
};

export type LessonTeacherGuidance = {
  observation_prompt?: string;
  evidence_points?: string[];
  oral_question?: string;
  expected_response?: string;
  misconception_cue?: string;
  closing?: string;
  fallback?: string;
};

export type LessonBrainstorm = {
  title: string;
  prompt: string;
  regions: string[];
  button_label: string;
};

export type LessonQuestion = {
  question_id: string;
  type: "choice" | "open";
  text: string;
  options: string[];
  answer_index: number | null;
  expected_points: string[];
  misconceptions: LessonMisconception[];
  evidence_refs?: LessonEvidenceRef[];
  argument_chain?: string[];
  remediation_task?: string;
};

export type LessonScene = {
  basemap_id: string;
  templates: string[];
  layer_visibility: Record<string, boolean>;
  catalog_layers?: string[];
  catalog_layer_focus?: string;
  view: { center?: [number, number]; zoom?: number; extent?: [number, number, number, number] };
  annotations: Array<{ text: string; position: [number, number] }>;
  visual_query: Record<string, unknown> | null;
  globe?: LessonGlobeScene;
};

export type LessonStage = {
  stage_id: string;
  title: string;
  minutes: number;
  scene: LessonScene;
  script: string[];
  questions: LessonQuestion[];
  assistant_prompts: string[];
  brainstorm?: LessonBrainstorm;
  evidence_refs?: LessonEvidenceRef[];
  teacher_guidance?: LessonTeacherGuidance;
};

export type LessonRecord = {
  lesson_id: string;
  title: string;
  subject: string;
  grade: string;
  objectives: string[];
  stages: LessonStage[];
  source: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type SessionEvent = {
  event_id: string;
  type: string;
  timestamp: string;
  stage_id: string;
  payload: Record<string, unknown>;
};

export type ClassSessionRecord = {
  session_id: string;
  lesson_id: string;
  project_id: string;
  status: "running" | "ended";
  join_code: string;
  current_stage_id: string;
  started_at: string;
  ended_at: string;
  events: SessionEvent[];
  active_question: Record<string, unknown>;
  responses: Record<string, Array<Record<string, unknown>>>;
  metadata: Record<string, unknown>;
};

export type ClassSessionResponse = {
  status: string;
  session: ClassSessionRecord;
  student_join_url?: string;
};

export type QuestionTally = {
  question_id: string;
  total: number;
  option_counts: number[];
  answer_index: number | null;
  correct_rate: number | null;
  texts: Array<{ nickname: string; text: string }>;
};

export type SessionLiveState = {
  status: string;
  session_id: string;
  session_status: string;
  current_stage_id: string;
  active_question: Record<string, unknown>;
  tally: QuestionTally | null;
  joined_count: number;
  recent_events: SessionEvent[];
};

export type ObservationVerdict = "correct" | "partial" | "misconception";

export type SceneSnapshot = {
  basemap_id?: string;
  view?: { center: [number, number]; zoom: number };
  layer_visibility?: Record<string, boolean>;
  templates?: string[];
  globe?: LessonGlobeScene;
};

export type PopulationSourceCard = {
  id: string;
  title: string;
  source_type: "dataset" | "knowledge" | "lesson";
  source_name: string;
  source_url: string;
  source_year: string;
  spatial_scale: string;
  field_unit: string;
  license: string;
  status: string;
  dataset_id: string;
  knowledge_id: string;
  lesson_id: string;
  version: string;
  teaching_usage: string[];
  limitations: string[];
  summary: string;
  fingerprint: string;
};

export type PopulationSourceVersion = {
  version: string;
  manifest: string;
  released_at: string;
  summary: string;
};

export type PopulationLessonPrepInput = {
  objective: string;
  grade: string;
  duration_minutes: number;
  region: string;
  years?: string[];
  source_ids?: string[];
  source_version?: string;
};

export type PopulationLessonPrepChange = {
  stage_id: string;
  title: string;
  change_types: string[];
  before_fingerprint: string;
  after_fingerprint: string;
  evidence_count: number;
  question_count: number;
};

export type PopulationLessonPrepChangeSet = {
  change_set_id: string;
  status: "pending" | "applied" | "rejected";
  lesson_id: string;
  base_lesson_fingerprint: string;
  source_version: string;
  source_pack_fingerprint: string;
  source_refs: LessonEvidenceRef[];
  changes: PopulationLessonPrepChange[];
  proposed_lesson: LessonRecord;
  created_at: string;
  resolved_at?: string;
  applied_stage_ids?: string[];
};

export type PopulationLessonPrepResult = {
  status: string;
  capability: "population_lesson_prep";
  job_id: string;
  warnings: string[];
  rehearsal: {
    status: "passed" | "failed";
    errors: string[];
    warnings: string[];
    checks: Record<string, number | boolean>;
  };
  change_set: PopulationLessonPrepChangeSet;
};

export type ReportStageStat = {
  stage_id: string;
  title: string;
  planned_minutes: number | null;
  actual_minutes: number | null;
  entered_at: string;
};

export type ReportQuestionStat = {
  question_id: string;
  stage_id: string;
  text: string;
  type: string;
  collection_mode?: "student_response" | "teacher_observation" | string;
  options: string[];
  answer_index: number | null;
  response_count: number;
  option_counts: number[];
  correct_rate: number | null;
  sample_texts: string[];
  misconceptions: LessonMisconception[];
};

export type SessionReportStatistics = {
  session_id: string;
  lesson_id: string;
  lesson_title: string;
  started_at: string;
  ended_at: string;
  duration_minutes: number | null;
  participant_count: number;
  participants: string[];
  response_data_collected?: boolean;
  stages: ReportStageStat[];
  questions: ReportQuestionStat[];
  observations: {
    total: number;
    verdict_counts: Record<ObservationVerdict, number>;
    misconception_tags: Array<[string, number]>;
    notes: Array<{ timestamp: string; stage_id: string; verdict: string; tag: string; note: string }>;
  };
  snapshot_count: number;
  assistant_exchange_count: number;
  event_count: number;
};

export type SessionReportResult = {
  statistics: SessionReportStatistics;
  diagnosis: { text: string; generator: string };
  report_url: string;
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
