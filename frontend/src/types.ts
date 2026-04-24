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
    actions?: Array<{ tool_name: string; tool_params: Record<string, unknown> }>;
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

export type AssistantTarget = "webgis" | "qgis" | "auto";

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

export type HealthResponse = {
  status: string;
  ui: {
    mode: string;
    assistant_tools: Array<{ name: string; description: string; parameters: Record<string, string> }>;
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
