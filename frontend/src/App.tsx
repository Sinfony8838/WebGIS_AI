import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "ol/ol.css";
import GeoJSON from "ol/format/GeoJSON";
import Draw from "ol/interaction/Draw";
import ImageLayer from "ol/layer/Image";
import TileLayer from "ol/layer/Tile";
import VectorLayer from "ol/layer/Vector";
import Map from "ol/Map";
import type MapBrowserEvent from "ol/MapBrowserEvent";
import { unByKey } from "ol/Observable";
import View from "ol/View";
import ImageStatic from "ol/source/ImageStatic";
import VectorSource from "ol/source/Vector";
import XYZ from "ol/source/XYZ";
import { fromLonLat, toLonLat, transformExtent } from "ol/proj";
import { getDistance } from "ol/sphere";
import { Circle as CircleStyle, Fill, Stroke, Style, Text } from "ol/style";
import { easeOut } from "ol/easing";
import { getCenter } from "ol/extent";
import {
  activateLessonResourceSet,
  createKbMaterialLink,
  confirmAssistantAction,
  createProject,
  exportSnapshot,
  fetchLessonResources,
  fetchHealth,
  fetchKbManifest,
  fetchKbTopics,
  fetchLayers,
  fetchOutputs,
  fetchProject,
  getApiBase,
  patchLayer,
  registerKbLayer,
  runTemplate,
  searchKb,
  searchPoi,
  searchResources,
  sendAssistantMessage,
  saveLessonResourceSet,
  switchBasemap,
  upsertKbItem,
  uploadDataset,
  uploadKbMaterial,
  fetchTeachingMaps,
  toggleTeachingMap,
  fetchActiveTeachingMaps,
  type TeachingMapItem,
} from "./api";
import { BasemapMenu } from "./components/BasemapMenu";
import { CopilotWidget } from "./components/CopilotWidget";
import { type KnowledgeQuery } from "./components/KnowledgePanel";
import { RegionFocusOverlay } from "./components/RegionFocusOverlay";
import { SideDrawer, type DrawerTab } from "./components/SideDrawer";
import { TeachingMapPanel } from "./components/TeachingMapPanel";
import { TeachingMaterialViewer } from "./components/TeachingMaterialViewer";
import { ToastStack, type ToastItem } from "./components/ToastStack";
import { UploadDialog } from "./components/UploadDialog";
import { WorkflowDock } from "./components/WorkflowDock";
import type {
  AssistantInputMode,
  AssistantMode,
  AssistantTarget,
  ArtifactRecord,
  ChatMessage,
  HealthResponse,
  JobRecord,
  KnowledgeBaseItem,
  KnowledgeTopicSummary,
  LessonResourceSet,
  LayerRecord,
  LayersResponse,
  MapContext,
  PoiSearchItem,
  ProjectRecord,
  RegionBinding,
  ResourceSearchResult,
  TeachingMaterial
} from "./types";
import "./styles.css";

type InteractionMode = "browse" | "annotate" | "measure" | "draw-search";
type RenderableLayer = TileLayer<XYZ> | ImageLayer<ImageStatic> | VectorLayer<any>;
type FocusedRegion = {
  label: string;
  layerId: string;
  properties: Record<string, unknown>;
  pixel: [number, number] | null;
};

const modeLabelMap: Record<InteractionMode, string> = {
  browse: "选择",
  annotate: "标注",
  measure: "测距",
  "draw-search": "绘区"
};

function timestamp(): string {
  return new Date().toISOString();
}

function withOpacity(color: string, opacity: number): string {
  if (!color.startsWith("#")) {
    return color;
  }
  const normalized =
    color.length === 4 ? `#${color[1]}${color[1]}${color[2]}${color[2]}${color[3]}${color[3]}` : color;
  const red = Number.parseInt(normalized.slice(1, 3), 16);
  const green = Number.parseInt(normalized.slice(3, 5), 16);
  const blue = Number.parseInt(normalized.slice(5, 7), 16);
  return `rgba(${red}, ${green}, ${blue}, ${opacity})`;
}

function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

function regionLabel(properties: Record<string, unknown>): string {
  for (const key of ["name", "name_cn", "NAME", "Name", "admin_name", "province", "city", "id"]) {
    const value = properties[key];
    if (value !== undefined && value !== null && String(value).trim()) {
      return String(value).trim();
    }
  }
  return "已选地区";
}

function regionMatchesBinding(region: FocusedRegion, binding: RegionBinding): boolean {
  if (binding.layer_id && binding.layer_id !== region.layerId) {
    return false;
  }
  const candidates = [
    region.label,
    String(region.properties.name || ""),
    String(region.properties.name_cn || ""),
    String(region.properties.NAME || ""),
    String(region.properties.adcode || ""),
    String(region.properties.admin_code || ""),
    String(region.properties.id || "")
  ]
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  const bindingValues = [binding.name, binding.admin_code, binding.feature_id]
    .map((value) => String(value || "").trim().toLowerCase())
    .filter(Boolean);
  if (!bindingValues.length) {
    return Boolean(binding.layer_id);
  }
  return bindingValues.some((value) => candidates.includes(value) || candidates.some((candidate) => candidate.includes(value)));
}

function currentExtentFromMap(map: Map): [number, number, number, number] {
  const size = map.getSize();
  if (!size) {
    return [73, 18, 135, 54];
  }
  const extent = map.getView().calculateExtent(size);
  return transformExtent(extent, "EPSG:3857", "EPSG:4326") as [number, number, number, number];
}

function captureMapSnapshot(map: Map): Promise<string> {
  return new Promise((resolve) => {
    map.once("rendercomplete", () => {
      const size = map.getSize();
      if (!size) {
        resolve("");
        return;
      }
      const canvas = document.createElement("canvas");
      canvas.width = size[0];
      canvas.height = size[1];
      const context = canvas.getContext("2d");
      if (!context) {
        resolve("");
        return;
      }

      const canvases = Array.from(map.getViewport().querySelectorAll<HTMLCanvasElement>(".ol-layer canvas, canvas.ol-layer"));
      canvases.forEach((sourceCanvas) => {
        if (!sourceCanvas.width || !sourceCanvas.height) {
          return;
        }
        const parent = sourceCanvas.parentElement as HTMLElement | null;
        const opacity = Number(parent?.style.opacity || "1");
        context.globalAlpha = Number.isFinite(opacity) ? opacity : 1;
        const transform = sourceCanvas.style.transform;
        if (transform) {
          const values = transform
            .replace("matrix(", "")
            .replace(")", "")
            .split(",")
            .map((value) => Number(value.trim()));
          if (values.length === 6) {
            context.setTransform(values[0], values[1], values[2], values[3], values[4], values[5]);
          } else {
            context.setTransform(1, 0, 0, 1, 0, 0);
          }
        } else {
          context.setTransform(1, 0, 0, 1, 0, 0);
        }
        context.drawImage(sourceCanvas, 0, 0);
      });

      context.setTransform(1, 0, 0, 1, 0, 0);
      resolve(canvas.toDataURL("image/png"));
    });
    map.renderSync();
  });
}

function formatFeatureSummary(properties: Record<string, unknown>): string {
  const entries = Object.entries(properties)
    .filter(([key, value]) => key !== "geometry" && !key.startsWith("__") && value !== undefined && value !== "")
    .slice(0, 7);
  if (!entries.length) {
    return "当前要素没有可读属性。";
  }
  return entries.map(([key, value]) => `${key}: ${String(value)}`).join("\n");
}

function parsePoiResults(layerState: LayersResponse | null): { items: PoiSearchItem[]; summary: string } {
  const poiLayer = layerState?.items.find((item) => item.layer_id === "poi_search_results" && item.visible);
  if (!poiLayer) {
    return { items: [], summary: "" };
  }

  const features = Array.isArray((poiLayer.data as { features?: unknown[] }).features)
    ? ((poiLayer.data as { features: Array<Record<string, unknown>> }).features)
    : [];

  const items = features
    .map((feature, index) => {
      const geometry = feature.geometry as { coordinates?: unknown[] } | undefined;
      const coordinates = Array.isArray(geometry?.coordinates) ? geometry.coordinates : [];
      if (coordinates.length < 2) {
        return null;
      }
      const properties = (feature.properties as Record<string, unknown>) || {};
      return {
        poi_id: String(properties.poi_id || `poi_${index}`),
        name: String(properties.name || `POI ${index + 1}`),
        address: String(properties.address || ""),
        type: String(properties.type || ""),
        district: String(properties.district || ""),
        city: String(properties.city || ""),
        location: [Number(coordinates[0]), Number(coordinates[1])] as [number, number]
      } satisfies PoiSearchItem;
    })
    .filter((item): item is PoiSearchItem => Boolean(item));

  const keyword = String(poiLayer.metadata.keyword || "POI");
  const summary = items.length
    ? `当前已加载“${keyword}”相关结果 ${items.length} 条。`
    : `当前范围内没有“${keyword}”相关结果。`;
  return { items, summary };
}

function emptyKnowledgeItem(): KnowledgeBaseItem {
  return {
    id: "",
    title: "",
    topic: "",
    region: "",
    time: "",
    source: "",
    license: "",
    grade_level: "",
    keywords: [],
    tags: [],
    crs: "",
    summary: "",
    canonical_answer: "",
    teaching_points: [],
    citations: [],
    dataset_refs: [],
    materials: [],
    related_templates: [],
    updated_at: ""
  };
}

function layerStyle(record: LayerRecord) {
  return (feature: { getGeometry: () => { getType: () => string } | undefined; get: (key: string) => unknown }) => {
    const geometryType = feature.getGeometry()?.getType() || record.geometry_type;
    const fillColor = String(record.style.fillColor || feature.get("__fillColor") || "#47a3ff");
    const fillOpacity = Number(record.style.fillOpacity || feature.get("__fillOpacity") || 0.22);
    const strokeColor = String(record.style.strokeColor || feature.get("__strokeColor") || "#e7edf5");
    const strokeWidth = Number(record.style.strokeWidth || feature.get("__strokeWidth") || 2);
    const radius = Number(record.style.radius || feature.get("__radius") || 7);
    const labelField = String(record.style.labelField || "name");
    const labelValue = String(feature.get(labelField) || feature.get("name") || "");

    return new Style({
      fill: geometryType.includes("Polygon") ? new Fill({ color: withOpacity(fillColor, fillOpacity) }) : undefined,
      stroke: new Stroke({
        color: strokeColor,
        width: strokeWidth,
        lineDash: (feature.get("__lineDash") as number[] | undefined) || undefined
      }),
      image: geometryType.includes("Point")
        ? new CircleStyle({
            radius,
            fill: new Fill({ color: withOpacity(fillColor, Math.min(fillOpacity + 0.36, 0.9)) }),
            stroke: new Stroke({ color: strokeColor, width: 1.2 })
          })
        : undefined,
      text: labelValue
        ? new Text({
            text: labelValue,
            font: "600 11px 'Microsoft YaHei UI', 'Segoe UI', sans-serif",
            fill: new Fill({ color: "#f7fafc" }),
            backgroundFill: new Fill({ color: "rgba(18, 25, 35, 0.68)" }),
            padding: [3, 4, 3, 4],
            offsetY: geometryType.includes("Point") ? -16 : 0
          })
        : undefined
    });
  };
}

export default function App() {
  const mapElementRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
    const basemapLayersRef = useRef<RenderableLayer[]>([]);
    const businessLayersRef = useRef<RenderableLayer[]>([]);
    const vectorLayerByIdRef = useRef<globalThis.Map<string, VectorLayer<any>>>(new globalThis.Map());
    const searchAreaSourceRef = useRef<VectorSource | null>(null);
  const highlightSourceRef = useRef<VectorSource | null>(null);
  const drawInteractionRef = useRef<Draw | null>(null);
  const pendingMeasureStartRef = useRef<[number, number] | null>(null);
  const interactionModeRef = useRef<InteractionMode>("browse");
  const lastAppliedViewRef = useRef("");
  const lastPoiSignatureRef = useRef("");
  const assistantDispatchRef = useRef<(message: string, overrides?: Partial<MapContext>) => void>(() => undefined);
  const activeJobStreamsRef = useRef(0);
  const jobStreamsRef = useRef<Set<EventSource>>(new Set());

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [project, setProject] = useState<(ProjectRecord & { status: string }) | null>(null);
  const [layerState, setLayerState] = useState<LayersResponse | null>(null);
  const [outputs, setOutputs] = useState<ArtifactRecord[]>([]);
  const [assistantMode, setAssistantMode] = useState<AssistantMode>("tool");
  const [currentJobByMode, setCurrentJobByMode] = useState<Record<AssistantMode, JobRecord | null>>({
    knowledge: null,
    tool: null
  });
  const [chatLogByMode, setChatLogByMode] = useState<Record<AssistantMode, ChatMessage[]>>({
    knowledge: [
      {
        role: "assistant",
        text: "这里是知识助手，可以回答地理概念、区域地理、地图判读与 GIS 方法问题。",
        timestamp: timestamp()
      }
    ],
    tool: [
      {
        role: "assistant",
        text: "这里是工具助手，可以规划并执行 WebGIS 操作；复杂分析请使用 PyQGIS 工作流面板。",
        timestamp: timestamp()
      }
    ]
  });
  const [conversationIds, setConversationIds] = useState<Record<AssistantMode, string>>({
    knowledge: "",
    tool: ""
  });
  const [assistantInput, setAssistantInput] = useState("");
  const [interactionMode, setInteractionMode] = useState<InteractionMode>("browse");
  const [measureText, setMeasureText] = useState("");
  const [selectedFeatureText, setSelectedFeatureText] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [searchResults, setSearchResults] = useState<PoiSearchItem[]>([]);
  const [searchSummary, setSearchSummary] = useState("");
  const [searchAreaGeometry, setSearchAreaGeometry] = useState<Record<string, unknown> | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [workflowDockOpen, setWorkflowDockOpen] = useState<boolean>(false);
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [drawerTab, setDrawerTab] = useState<DrawerTab>("resources");
  const [kbQuery, setKbQuery] = useState<KnowledgeQuery>({ query: "", topic: "", region: "", tag: "" });
    const [kbItems, setKbItems] = useState<KnowledgeBaseItem[]>([]);
    const [kbAllItems, setKbAllItems] = useState<KnowledgeBaseItem[]>([]);
  const [kbTopics, setKbTopics] = useState<KnowledgeTopicSummary[]>([]);
  const [kbTotal, setKbTotal] = useState(0);
    const [kbLoading, setKbLoading] = useState(false);
    const [kbEditingItem, setKbEditingItem] = useState<KnowledgeBaseItem | null>(null);
    const [resourceQuery, setResourceQuery] = useState("");
    const [resourceScope, setResourceScope] = useState<"all" | "kb" | "web" | "materials">("all");
    const [resourceLoading, setResourceLoading] = useState(false);
    const [resourceResults, setResourceResults] = useState<ResourceSearchResult[]>([]);
    const [lessonResourceSets, setLessonResourceSets] = useState<LessonResourceSet[]>([]);
    const [activeLessonResourceSetId, setActiveLessonResourceSetId] = useState("");
    const [focusedRegion, setFocusedRegion] = useState<FocusedRegion | null>(null);
    const [materialViewerOpen, setMaterialViewerOpen] = useState(false);
    const [materialViewerTitle, setMaterialViewerTitle] = useState("");
    const [materialViewerItems, setMaterialViewerItems] = useState<TeachingMaterial[]>([]);
    const [teachingMaps, setTeachingMaps] = useState<TeachingMapItem[]>([]);
    const [activeTeachingMapIds, setActiveTeachingMapIds] = useState<Set<string>>(new Set());
    const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [initAttempt, setInitAttempt] = useState(0);
  const [initError, setInitError] = useState("");
  const currentJob = currentJobByMode[assistantMode];
  const chatLog = chatLogByMode[assistantMode];

  const onlinePoiEnabled = health?.online_services.amap_poi_enabled ?? false;
  const basemapItems = health?.basemaps.items || [];
  const activeBasemapId = layerState?.base_map.id || health?.basemaps.default_id || "";
  const activeBasemapTitle = layerState?.base_map.title || basemapItems.find((item) => item.id === activeBasemapId)?.title || "未连接";
  const searchScopeLabel = searchAreaGeometry ? "手绘区域" : "当前视域";
  const statusText =
    measureText ||
    selectedFeatureText ||
    searchSummary ||
    layerState?.recent_actions[0]?.detail ||
    "可在右侧切换地图工具，或在左侧单元页加载课堂模板。";
  const visibleLayerCount = layerState?.items.filter((item) => item.visible).length ?? 0;
  const totalLayerCount = layerState?.items.length ?? 0;
    const enabledTemplateCount = layerState?.enabled_templates.length ?? 0;
    const kbActiveLayerId = layerState?.active_layer_id || "";
    const kbCanRegister = Boolean(project && kbActiveLayerId && !kbLoading);
    const activeLessonResourceSet = lessonResourceSets.find((item) => item.id === activeLessonResourceSetId) || lessonResourceSets.find((item) => item.active);
    const allKnowledgeMaterials = useMemo(
      () => kbAllItems.flatMap((item) => (item.materials || []).map((material) => ({ material, item }))),
      [kbAllItems]
    );
    const focusedRegionMaterials = useMemo(() => {
      if (!focusedRegion || !activeLessonResourceSet) {
        return [];
      }
      const allowedMaterialIds = new Set(activeLessonResourceSet.material_ids || []);
      const allowedItemIds = new Set(activeLessonResourceSet.item_ids || []);
      return allKnowledgeMaterials
        .filter(({ material, item }) => {
          if (allowedMaterialIds.size && !allowedMaterialIds.has(material.id)) {
            return false;
          }
          if (!allowedMaterialIds.size && allowedItemIds.size && !allowedItemIds.has(item.id)) {
            return false;
          }
          return regionMatchesBinding(focusedRegion, material.region_binding || {});
        })
        .map(({ material }) => material);
    }, [activeLessonResourceSet, allKnowledgeMaterials, focusedRegion]);
  const assistantActionPrompt = useMemo(
    () => "请结合当前视图进行课堂读图讲解，突出关键空间关系、层级结构与区位判断。",
    []
  );

  const dismissToast = useCallback((toastId: string) => {
    setToasts((previous) => previous.filter((item) => item.id !== toastId));
  }, []);

  const pushToast = useCallback(
    (tone: ToastItem["tone"], title: string, detail = "") => {
      const id = `${Date.now()}_${Math.random().toString(16).slice(2)}`;
      setToasts((previous) => [...previous, { id, tone, title, detail }]);
      window.setTimeout(() => {
        dismissToast(id);
      }, 4200);
    },
    [dismissToast]
  );

  const appendChat = useCallback((mode: AssistantMode, role: ChatMessage["role"], text: string) => {
    if (!text.trim()) {
      return;
    }
    setChatLogByMode((previous) => ({
      ...previous,
      [mode]: [...previous[mode], { role, text, timestamp: timestamp() }]
    }));
  }, []);

  const refreshProjectState = useCallback(async (projectId: string) => {
      const [projectPayload, layerPayload, outputsPayload, lessonPayload, activeTeachingPayload] = await Promise.all([
        fetchProject(projectId),
        fetchLayers(projectId),
        fetchOutputs(projectId),
        fetchLessonResources(projectId),
        fetchActiveTeachingMaps(projectId)
      ]);
      setProject(projectPayload);
      setLayerState(layerPayload);
      setOutputs(outputsPayload.items);
      setLessonResourceSets(lessonPayload.items);
      setActiveLessonResourceSetId(lessonPayload.active_lesson_resource_set_id);
      setActiveTeachingMapIds(new Set(activeTeachingPayload.active));
    }, []);

  const runKbSearch = useCallback(
    async (queryOverride?: Partial<KnowledgeQuery>) => {
      const nextQuery: KnowledgeQuery = { ...kbQuery, ...(queryOverride || {}) };
      setKbLoading(true);
      try {
        const response = await searchKb({ ...nextQuery, limit: 20 });
        setKbItems(response.items);
        setKbTotal(response.total);
        setKbEditingItem((previous) => {
          if (previous) {
            const matched = response.items.find((item) => item.id === previous.id);
            return matched || previous;
          }
          return response.items[0] || null;
        });
      } catch (error) {
        pushToast("error", "知识库检索失败", error instanceof Error ? error.message : "检索接口调用失败");
      } finally {
        setKbLoading(false);
      }
    },
    [kbQuery, pushToast]
  );

    const loadKnowledgeBase = useCallback(async () => {
    setKbLoading(true);
    try {
        const [manifest, topicsPayload] = await Promise.all([fetchKbManifest(), fetchKbTopics()]);
        setKbTopics(topicsPayload.items);
        setKbAllItems(manifest.items);
        setKbTotal(manifest.items.length);
      const response = await searchKb({ query: "", topic: "", region: "", tag: "", limit: 20 });
      setKbItems(response.items);
      setKbTotal(response.total || manifest.items.length);
      setKbEditingItem((previous) => previous || response.items[0] || manifest.items[0] || null);
    } catch (error) {
      pushToast("error", "知识库加载失败", error instanceof Error ? error.message : "无法读取知识库");
    } finally {
      setKbLoading(false);
    }
    }, [pushToast]);

    useEffect(() => {
      const query = resourceQuery.trim();
      const timer = window.setTimeout(() => {
        setResourceLoading(true);
        searchResources({ query, scope: resourceScope, limit: 16 })
          .then((response) => {
            setResourceResults(response.items);
          })
          .catch((error: Error) => {
            pushToast("error", "资料搜索失败", error.message);
          })
          .finally(() => setResourceLoading(false));
      }, 320);
      return () => window.clearTimeout(timer);
    }, [pushToast, resourceQuery, resourceScope]);

  const handleKbSaveItem = useCallback(async () => {
    if (!kbEditingItem) {
      setKbEditingItem(emptyKnowledgeItem());
      return;
    }
    if (!kbEditingItem.title.trim()) {
      pushToast("error", "保存失败", "请先填写知识条目标题。");
      return;
    }
    setKbLoading(true);
    try {
      const response = await upsertKbItem(kbEditingItem);
      setKbEditingItem(response.item);
      pushToast("success", "知识条目已保存", response.item.title || response.item.id);
      const refreshed = await searchKb({ ...kbQuery, limit: 20 });
      const topicsPayload = await fetchKbTopics();
      setKbTopics(topicsPayload.items);
      setKbItems(refreshed.items);
      setKbTotal(refreshed.total);
    } catch (error) {
      pushToast("error", "知识条目保存失败", error instanceof Error ? error.message : "请求未完成");
    } finally {
      setKbLoading(false);
    }
  }, [kbEditingItem, kbQuery, pushToast]);

  const buildKbRegisterMetadata = useCallback((item: KnowledgeBaseItem | null): Record<string, unknown> => {
    if (!item) {
      return {};
    }
    const metadata: Record<string, unknown> = {};
    if (item.id.trim()) {
      metadata.id = item.id.trim();
    }
    if (item.title.trim()) {
      metadata.title = item.title.trim();
    }
    if (item.topic.trim()) {
      metadata.topic = item.topic.trim();
    }
    if (item.region.trim()) {
      metadata.region = item.region.trim();
    }
    if (item.time.trim()) {
      metadata.time = item.time.trim();
    }
    if (item.keywords.length) {
      metadata.keywords = item.keywords;
    }
    if (item.summary.trim()) {
      metadata.summary = item.summary.trim();
    }
    if (item.canonical_answer.trim()) {
      metadata.canonical_answer = item.canonical_answer.trim();
    }
    if (item.teaching_points.length) {
      metadata.teaching_points = item.teaching_points;
    }
    return metadata;
  }, []);

  const handleRegisterActiveLayerToKb = useCallback(async () => {
    if (!project || !layerState?.active_layer_id) {
      return;
    }
    setKbLoading(true);
    try {
      const response = await registerKbLayer(
        project.project_id,
        layerState.active_layer_id,
        buildKbRegisterMetadata(kbEditingItem)
      );
      setKbEditingItem(response.item);
      const refreshed = await searchKb({ ...kbQuery, limit: 20 });
      const topicsPayload = await fetchKbTopics();
      setKbTopics(topicsPayload.items);
      setKbItems(refreshed.items);
      setKbTotal(refreshed.total);
      await refreshProjectState(project.project_id);
      pushToast("success", "已关联当前图层", layerState.active_layer_id);
    } catch (error) {
      pushToast("error", "图层关联失败", error instanceof Error ? error.message : "知识库关联请求失败");
    } finally {
      setKbLoading(false);
    }
  }, [buildKbRegisterMetadata, kbEditingItem, kbQuery, layerState?.active_layer_id, project, pushToast, refreshProjectState]);

    const focusLayerExtent = useCallback((layerId: string) => {
      const map = mapRef.current;
      const record = layerState?.items.find((item) => item.layer_id === layerId);
      if (!map || !record || record.kind !== "vector") {
        return false;
      }
      const format = new GeoJSON();
      const features = format.readFeatures(record.data, {
        dataProjection: "EPSG:4326",
        featureProjection: "EPSG:3857"
      });
      if (!features.length) {
        return false;
      }
      const source = new VectorSource({ features });
      const extent = source.getExtent();
      const firstFeature = features[0];
      highlightSourceRef.current?.clear();
      if (firstFeature) {
        highlightSourceRef.current?.addFeature(firstFeature.clone());
      }
      map.getView().fit(extent, { duration: 620, padding: [90, 360, 90, 360], maxZoom: 8 });
      const properties = { ...firstFeature.getProperties() } as Record<string, unknown>;
      delete properties.geometry;
      setFocusedRegion({
        label: regionLabel(properties),
        layerId,
        properties,
        pixel: map.getPixelFromCoordinate(getCenter(extent)) as [number, number]
      });
      return true;
    }, [layerState?.items]);

    const handleFocusKnowledgeLayer = useCallback(
      async (layerId: string) => {
        if (!project) {
          return;
        }
      try {
        await patchLayer(project.project_id, layerId, { active: true, visible: true });
        await refreshProjectState(project.project_id);
        focusLayerExtent(layerId);
        pushToast("info", "已定位关联图层", layerId);
      } catch (error) {
        pushToast("error", "定位关联图层失败", error instanceof Error ? error.message : "图层状态更新失败");
      }
    },
      [focusLayerExtent, project, pushToast, refreshProjectState]
    );

    const refreshKnowledgeAfterMaterialWrite = useCallback(
      async (itemId: string, material: TeachingMaterial) => {
        const manifest = await fetchKbManifest();
        setKbAllItems(manifest.items);
        const refreshed = await searchKb({ ...kbQuery, limit: 20 });
        setKbItems(refreshed.items);
        setKbTotal(refreshed.total);
        setKbEditingItem((previous) => {
          const fromManifest = manifest.items.find((item) => item.id === itemId);
          if (fromManifest) {
            return fromManifest;
          }
          return previous ? { ...previous, materials: [...(previous.materials || []), material] } : previous;
        });
      },
      [kbQuery]
    );

    const handleUploadMaterial = useCallback(
      async (
        item: KnowledgeBaseItem,
        file: File,
        metadata: { title: string; description: string; material_type: string; region_binding: RegionBinding }
      ) => {
        if (!item.id) {
          pushToast("error", "素材上传失败", "请先保存知识库条目。");
          return;
        }
        setKbLoading(true);
        try {
          const formData = new FormData();
          formData.set("file", file);
          formData.set("title", metadata.title || file.name);
          formData.set("description", metadata.description);
          formData.set("material_type", metadata.material_type);
          const response = await uploadKbMaterial(item.id, formData, metadata.region_binding);
          await refreshKnowledgeAfterMaterialWrite(item.id, response.material);
          pushToast("success", "素材已上传", response.material.title);
        } catch (error) {
          pushToast("error", "素材上传失败", error instanceof Error ? error.message : "上传请求失败");
        } finally {
          setKbLoading(false);
        }
      },
      [pushToast, refreshKnowledgeAfterMaterialWrite]
    );

    const handleAddMaterialLink = useCallback(
      async (
        item: KnowledgeBaseItem,
        payload: { url: string; title: string; description: string; material_type: string; region_binding: RegionBinding }
      ) => {
        if (!item.id) {
          pushToast("error", "外链添加失败", "请先保存知识库条目。");
          return;
        }
        setKbLoading(true);
        try {
          const response = await createKbMaterialLink({
            kb_item_id: item.id,
            url: payload.url,
            title: payload.title,
            description: payload.description,
            material_type: payload.material_type,
            region_binding: payload.region_binding
          });
          await refreshKnowledgeAfterMaterialWrite(item.id, response.material);
          pushToast("success", "外链已添加", response.material.title);
        } catch (error) {
          pushToast("error", "外链添加失败", error instanceof Error ? error.message : "请求失败");
        } finally {
          setKbLoading(false);
        }
      },
      [pushToast, refreshKnowledgeAfterMaterialWrite]
    );

    const importToLesson = useCallback(
      async (item: KnowledgeBaseItem, material?: TeachingMaterial) => {
        if (!project || !item.id) {
          return;
        }
        const active = activeLessonResourceSet || {
          id: "",
          title: "当前课时资料包",
          project_id: project.project_id,
          item_ids: [],
          material_ids: [],
          region_bindings: [],
          active: true,
          created_at: "",
          updated_at: ""
        };
        const binding = material?.region_binding || {
          name: item.region,
          layer_id: String(item.dataset_refs?.[0]?.layer_id || "")
        };
        const response = await saveLessonResourceSet(project.project_id, {
          ...active,
          item_ids: uniqueStrings([...(active.item_ids || []), item.id]),
          material_ids: uniqueStrings([...(active.material_ids || []), ...(material ? [material.id] : item.materials.map((entry) => entry.id))]),
          region_bindings: [...(active.region_bindings || []), binding],
          active: true
        });
        setLessonResourceSets(response.items);
        setActiveLessonResourceSetId(response.item.id);
        pushToast("success", "已导入本课时", material?.title || item.title);
      },
      [activeLessonResourceSet, project, pushToast]
    );

    const handleOpenResourceResult = useCallback(
      (item: ResourceSearchResult) => {
        if (item.kb_item) {
          setKbEditingItem(item.kb_item);
          setDrawerOpen(true);
          setDrawerTab("resources");
          return;
        }
        if (item.material) {
          setMaterialViewerTitle(item.title);
          setMaterialViewerItems([item.material]);
          setMaterialViewerOpen(true);
          return;
        }
        if (item.url) {
          window.open(item.url, "_blank", "noopener,noreferrer");
        }
      },
      []
    );

    const handleImportResourceResult = useCallback(
      (item: ResourceSearchResult) => {
        if (item.kb_item) {
          void importToLesson(item.kb_item, item.material);
          return;
        }
        pushToast("info", "暂不能导入", "该结果不是知识库条目或已保存素材。");
      },
      [importToLesson, pushToast]
    );

  const buildMapContext = useCallback(
    (overrides?: Partial<MapContext>): MapContext => {
      const map = mapRef.current;
      const center = map
        ? (toLonLat(map.getView().getCenter() || fromLonLat([104, 35])) as [number, number])
        : project?.view.center || [104, 35];
      const zoom = map?.getView().getZoom() || project?.view.zoom || 4;
      const extent = map
        ? currentExtentFromMap(map)
        : ((project?.view.extent || [73, 18, 135, 54]) as [number, number, number, number]);

      return {
        center,
        zoom,
        extent,
        active_layer_id: layerState?.active_layer_id,
        visible_layers: layerState?.items.filter((item) => item.visible).map((item) => ({ layer_id: item.layer_id, name: item.name })) || [],
        recent_actions: layerState?.recent_actions || [],
          basemap_id: layerState?.base_map.id,
          search_area_geometry: searchAreaGeometry,
          selected_feature_summary: selectedFeatureText || undefined,
          selected_region: focusedRegion
            ? { label: focusedRegion.label, layer_id: focusedRegion.layerId, properties: focusedRegion.properties }
            : undefined,
          active_lesson_materials: focusedRegionMaterials.map((material) => ({
            id: material.id,
            title: material.title,
            type: material.type,
            region_binding: material.region_binding
          })),
          ...overrides
        };
      },
      [focusedRegion, focusedRegionMaterials, layerState, project, searchAreaGeometry, selectedFeatureText]
    );

  const closeJobStream = useCallback((source: EventSource): boolean => {
    const wasTracked = jobStreamsRef.current.delete(source);
    source.close();
    if (wasTracked) {
      activeJobStreamsRef.current = Math.max(0, activeJobStreamsRef.current - 1);
    }
    setBusy(activeJobStreamsRef.current > 0);
    return wasTracked;
  }, []);

  const handleAssistantUiActions = useCallback((payload: JobRecord) => {
    const executed = payload.result?.actions_executed || [];
    const openMaterialActions = executed.flatMap((entry) => {
      const result = entry.result || {};
      const uiActions = Array.isArray(result.ui_actions) ? result.ui_actions : [];
      return uiActions.filter((item): item is { type: string; title?: string; materials?: TeachingMaterial[] } => {
        return Boolean(item && typeof item === "object" && (item as { type?: string }).type === "open_material");
      });
    });
    const latest = openMaterialActions.at(-1);
    const materials = latest?.materials || [];
    if (!latest || !materials.length) {
      return;
    }
    setMaterialViewerTitle(latest.title || materials[0]?.title || "课堂资料");
    setMaterialViewerItems(materials);
    setMaterialViewerOpen(true);
  }, []);

  const subscribeToJob = useCallback(
    (jobId: string, mode: AssistantMode) => {
      const source = new EventSource(`${getApiBase()}/jobs/${jobId}/stream`);
      jobStreamsRef.current.add(source);
      activeJobStreamsRef.current += 1;
      setBusy(true);
      source.addEventListener("job", async (event) => {
        let payload: JobRecord;
        try {
          payload = JSON.parse((event as MessageEvent).data) as JobRecord;
        } catch {
          if (closeJobStream(source)) {
            pushToast("error", "任务流异常", "任务流返回了无法解析的数据。");
          }
          return;
        }
        setCurrentJobByMode((previous) => ({ ...previous, [mode]: payload }));
        if (payload.status === "completed" || payload.status === "failed") {
          if (!closeJobStream(source)) {
            return;
          }
          await refreshProjectState(payload.project_id);
          handleAssistantUiActions(payload);
          const message = payload.result?.assistant_message || payload.result?.summary || payload.error || "";
          const nextConversationId = String(payload.result?.conversation_id || "");
          if (nextConversationId) {
            setConversationIds((previous) => ({ ...previous, [mode]: nextConversationId }));
          }
          appendChat(mode, payload.status === "failed" ? "system" : "assistant", message);
          pushToast(
            payload.status === "failed" ? "error" : "success",
            payload.status === "failed" ? "任务失败" : "任务完成",
            payload.result?.summary || message
          );
        }
      });
      source.addEventListener("error", () => {
        if (closeJobStream(source)) {
          pushToast("error", "任务流断开", "事件流提前关闭，请重试当前操作。");
        }
      });
    },
    [appendChat, closeJobStream, handleAssistantUiActions, pushToast, refreshProjectState]
  );

  useEffect(() => {
    return () => {
      jobStreamsRef.current.forEach((source) => source.close());
      jobStreamsRef.current.clear();
      activeJobStreamsRef.current = 0;
    };
  }, []);

  const submitAssistantText = useCallback(
    async (
      message: string,
      overrides?: Partial<MapContext>,
      target: AssistantTarget = "webgis",
      inputMode: AssistantInputMode = "text",
      mode: AssistantMode = assistantMode,
      screenSnapshot?: { image_data_url: string; width: number; height: number; captured_at: string }
    ) => {
      if (!project) {
        return;
      }
      appendChat(mode, "user", message);
      const response = await sendAssistantMessage(project.project_id, message, buildMapContext(overrides), target, inputMode, {
        assistantMode: mode,
        conversationId: health?.ui.assistant_v2_enabled ? conversationIds[mode] : undefined,
        history: health?.ui.assistant_v2_enabled ? chatLogByMode[mode] : undefined,
        screenSnapshot
      });
      if (response.conversation_id) {
        setConversationIds((previous) => ({ ...previous, [mode]: response.conversation_id || previous[mode] }));
      }
      subscribeToJob(response.job_id, mode);
    },
    [appendChat, assistantMode, buildMapContext, chatLogByMode, conversationIds, health?.ui.assistant_v2_enabled, project, subscribeToJob]
  );

  assistantDispatchRef.current = (message, overrides) => {
    void submitAssistantText(message, overrides, "webgis", "text", "tool");
  };

  const handleReadMapWithSnapshot = useCallback(async () => {
    if (!mapRef.current) {
      void submitAssistantText(assistantActionPrompt, undefined, "webgis", "text", "knowledge");
      return;
    }
    const size = mapRef.current.getSize() || [0, 0];
    const imageDataUrl = await captureMapSnapshot(mapRef.current);
    const snapshot = imageDataUrl
      ? {
          image_data_url: imageDataUrl,
          width: Number(size[0] || 0),
          height: Number(size[1] || 0),
          captured_at: new Date().toISOString()
        }
      : undefined;
    void submitAssistantText(assistantActionPrompt, undefined, "webgis", "text", "knowledge", snapshot);
  }, [assistantActionPrompt, submitAssistantText]);

  const handleTemplateRun = useCallback(
    async (templateId: string) => {
      if (!project) {
        return;
      }
      setDrawerOpen(true);
      setDrawerTab("resources");
      const response = await runTemplate(project.project_id, templateId);
      subscribeToJob(response.job_id, "tool");
    },
    [project, subscribeToJob]
  );

  const handleExportSnapshot = useCallback(async () => {
    if (!project || !mapRef.current) {
      return;
    }
    const imageDataUrl = await captureMapSnapshot(mapRef.current);
    if (!imageDataUrl) {
      pushToast("error", "导出失败", "当前地图画面没有可用图层。");
      return;
    }
    await exportSnapshot(project.project_id, "课堂截图", imageDataUrl, "由 WebGIS 实时交互系统导出");
    await refreshProjectState(project.project_id);
    appendChat("tool", "system", "当前课堂画面已导出到课堂产物列表。");
    pushToast("success", "导出完成", "课堂截图已进入左侧产物页。");
  }, [appendChat, project, pushToast, refreshProjectState]);

  const handleUploadDataset = useCallback(
    async (formData: FormData) => {
      if (!project) {
        return;
      }
      const response = await uploadDataset(project.project_id, formData);
      subscribeToJob(response.job_id, "tool");
    },
    [project, subscribeToJob]
  );

  const focusPoiResult = useCallback(
    (item: PoiSearchItem) => {
      if (!mapRef.current || !highlightSourceRef.current) {
        return;
      }
      const format = new GeoJSON();
      const feature = format.readFeature(
        {
          type: "Feature",
          properties: {
            name: item.name,
            address: item.address,
            district: item.district,
            city: item.city
          },
          geometry: { type: "Point", coordinates: item.location }
        },
        { dataProjection: "EPSG:4326", featureProjection: "EPSG:3857" }
      );
      highlightSourceRef.current.clear();
      highlightSourceRef.current.addFeature(feature);
      mapRef.current.getView().animate({
        center: fromLonLat(item.location),
        zoom: Math.max(mapRef.current.getView().getZoom() || 4, 10),
        duration: 600
      });
      setSelectedFeatureText(
        [`名称: ${item.name}`, `区域: ${item.district || item.city || "未知"}`, item.address ? `地址: ${item.address}` : ""]
          .filter(Boolean)
          .join("\n")
      );
      pushToast("info", "已定位检索结果", item.name);
    },
    [pushToast]
  );

  const handlePoiSearch = useCallback(
    async (scope: "auto" | "view" | "polygon" = "auto") => {
      if (!project) {
        return;
      }
      const keyword = searchKeyword.trim();
      if (!keyword) {
        pushToast("error", "缺少检索关键词", "先在搜索栏输入需要检索的 POI 类型。");
        return;
      }
      if (!onlinePoiEnabled) {
        pushToast("error", "在线检索未配置", "请先设置 WEBGIS_AI_AMAP_WEB_SERVICE_KEY。");
        return;
      }
      const map = mapRef.current;
      const resolvedMode = scope === "auto" ? (searchAreaGeometry ? "polygon" : "view") : scope;
      if (resolvedMode === "polygon" && !searchAreaGeometry) {
        pushToast("error", "尚未绘制检索区", "先点击右侧“绘区”，在地图上画出检索区域。");
        return;
      }
      const response = await searchPoi(project.project_id, keyword, {
        mode: resolvedMode,
        extent: map ? currentExtentFromMap(map) : project.view.extent,
        geometry: searchAreaGeometry
      });
      setSearchSummary(response.summary);
      setSearchResults(response.items);
      setDrawerTab("search");
      setDrawerOpen(true);
      await refreshProjectState(project.project_id);
      appendChat("tool", "system", response.summary);
      pushToast("success", `${resolvedMode === "polygon" ? "区域" : "视域"}检索完成`, response.summary);
    },
    [appendChat, onlinePoiEnabled, project, pushToast, refreshProjectState, searchAreaGeometry, searchKeyword]
  );

  const handleClearWorkspace = useCallback(async () => {
    pendingMeasureStartRef.current = null;
      searchAreaSourceRef.current?.clear();
      highlightSourceRef.current?.clear();
      lastPoiSignatureRef.current = "";
      setSearchAreaGeometry(null);
      setFocusedRegion(null);
    setSearchResults([]);
    setSearchSummary("");
    setSelectedFeatureText("");
    setMeasureText("");
    setInteractionMode("browse");

    if (project && layerState?.items.some((item) => item.layer_id === "poi_search_results" && item.visible)) {
      await patchLayer(project.project_id, "poi_search_results", { visible: false });
      await refreshProjectState(project.project_id);
    }
    pushToast("info", "已清除当前操作", "检索区、测距结果和高亮要素已重置。");
  }, [layerState?.items, project, pushToast, refreshProjectState]);

  const handleToggleTeachingMap = useCallback(async (mapId: string, visible: boolean) => {
    if (!project) {
      return;
    }
    try {
      const result = await toggleTeachingMap(project.project_id, mapId, visible);
      setActiveTeachingMapIds((prev) => {
        const next = new Set(prev);
        if (visible) {
          next.add(mapId);
        } else {
          next.delete(mapId);
        }
        return next;
      });
      // Refresh layers so the new raster layer appears on the map
      await refreshProjectState(project.project_id);
      // Optionally fly to the map's recommended view
      if (visible && result.view?.center && result.view?.zoom) {
        const map = mapRef.current;
        if (map) {
          map.getView().animate({
            center: fromLonLat(result.view.center),
            zoom: result.view.zoom,
            duration: 600,
          });
        }
      }
    } catch (error: unknown) {
      pushToast("error", "教学地图切换失败", String(error));
    }
  }, [project, pushToast, refreshProjectState]);

  const handleResetView = useCallback(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    map.getView().animate({
      center: fromLonLat([104, 35]),
      zoom: 4,
      duration: 1000,
      easing: easeOut,
    });
  }, []);

  useEffect(() => {
    interactionModeRef.current = interactionMode;
  }, [interactionMode]);

  useEffect(() => {
    if (!mapElementRef.current || mapRef.current) {
      return;
    }

    const searchAreaSource = new VectorSource();
    const searchAreaLayer = new VectorLayer({
      source: searchAreaSource,
      zIndex: 160,
      style: new Style({
        fill: new Fill({ color: "rgba(79, 95, 120, 0.16)" }),
        stroke: new Stroke({ color: "#facc15", width: 2, lineDash: [8, 6] })
      })
    });

      const highlightSource = new VectorSource();
      const highlightLayer = new VectorLayer({
        source: highlightSource,
        zIndex: 170,
        style: (feature) => {
          const geometryType = feature.getGeometry()?.getType() || "";
          return new Style({
            fill: geometryType.includes("Polygon") ? new Fill({ color: "rgba(56, 189, 248, 0.2)" }) : undefined,
            stroke: new Stroke({ color: "#67e8f9", width: 3.2 }),
            image: geometryType.includes("Point")
              ? new CircleStyle({
                  radius: 10,
                  fill: new Fill({ color: "rgba(56, 189, 248, 0.45)" }),
                  stroke: new Stroke({ color: "#ecfeff", width: 2.2 })
                })
              : undefined
          });
        }
      });

    const map = new Map({
      target: mapElementRef.current,
      layers: [searchAreaLayer, highlightLayer],
      view: new View({
        center: fromLonLat([104, 35]),
        zoom: 4
      })
    });

    const syncMapSize = () => {
      map.updateSize();
      map.renderSync();
    };
    const resizeObserver = new ResizeObserver(() => {
      syncMapSize();
    });
    resizeObserver.observe(mapElementRef.current);
    const delayedResize = window.setTimeout(() => {
      syncMapSize();
    }, 180);

    const handleClick = (event: MapBrowserEvent<UIEvent>) => {
      const lonLat = toLonLat(event.coordinate) as [number, number];
      const mode = interactionModeRef.current;

      if (mode === "annotate") {
        const text = window.prompt("输入课堂标注内容");
        if (text) {
          assistantDispatchRef.current(`在当前位置标注：${text}`, {
            center: lonLat,
            extent: currentExtentFromMap(map)
          });
        }
        setInteractionMode("browse");
        return;
      }

      if (mode === "measure") {
        if (!pendingMeasureStartRef.current) {
          pendingMeasureStartRef.current = lonLat;
          setMeasureText("已记录起点，请再点击一个位置作为终点。");
          return;
        }
        const distanceKm = getDistance(pendingMeasureStartRef.current, lonLat) / 1000;
        pendingMeasureStartRef.current = null;
        setMeasureText(`测线结果：${distanceKm.toFixed(1)} 千米。`);
        setInteractionMode("browse");
        return;
      }

      const hit = map.forEachFeatureAtPixel(event.pixel, (feature, layer) => ({ feature, layer })) as
        | { feature: { getProperties: () => Record<string, unknown> }; layer: unknown }
        | undefined;

        if (!hit || hit.layer === searchAreaLayer || hit.layer === highlightLayer) {
          setSelectedFeatureText("");
          setFocusedRegion(null);
          highlightSource.clear();
          return;
        }

        const feature = hit.feature as any;
        const properties = { ...feature.getProperties() } as Record<string, unknown>;
        delete properties.geometry;
        setSelectedFeatureText(formatFeatureSummary(properties));
        const geometry = feature.getGeometry?.();
        if (geometry) {
          const cloned = geometry.clone();
          highlightSource.clear();
          const highlighted = feature.clone ? feature.clone() : undefined;
          if (highlighted?.setGeometry) {
            highlighted.setGeometry(cloned);
            highlightSource.addFeature(highlighted);
          }
          const extent = cloned.getExtent();
          const centerPixel = map.getPixelFromCoordinate(getCenter(extent)) as [number, number];
          const layerId =
            Array.from(vectorLayerByIdRef.current.entries()).find(([, layer]) => layer === hit.layer)?.[0] || "";
          setFocusedRegion({
            label: regionLabel(properties),
            layerId,
            properties,
            pixel: centerPixel
          });
          if (cloned.getType?.().includes("Polygon")) {
            map.getView().fit(extent, { duration: 560, padding: [92, 360, 92, 360], maxZoom: 8 });
          }
        }
      };

    searchAreaSourceRef.current = searchAreaSource;
    highlightSourceRef.current = highlightSource;
    mapRef.current = map;
    map.on("singleclick", handleClick);

    return () => {
      if (drawInteractionRef.current) {
        map.removeInteraction(drawInteractionRef.current);
        drawInteractionRef.current = null;
      }
      window.clearTimeout(delayedResize);
      resizeObserver.disconnect();
      map.un("singleclick", handleClick);
      map.setTarget(undefined);
      basemapLayersRef.current = [];
        businessLayersRef.current = [];
        vectorLayerByIdRef.current.clear();
      searchAreaSourceRef.current = null;
      highlightSourceRef.current = null;
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setInitError("");
      const healthPayload = await fetchHealth();
      if (cancelled) {
        return;
      }
      setHealth(healthPayload);
      const created = await createProject();
      if (cancelled) {
        return;
      }
      setProject(created);
      await refreshProjectState(created.project_id);
      await loadKnowledgeBase();
      // Load teaching maps catalog
      try {
        const tmaps = await fetchTeachingMaps();
        if (!cancelled) {
          setTeachingMaps(tmaps.items);
        }
        const active = await fetchActiveTeachingMaps(created.project_id);
        if (!cancelled) {
          setActiveTeachingMapIds(new Set(active.active));
        }
      } catch {
        // teaching maps are optional – do not block init
      }
      pushToast("success", "课堂项目已创建", "已初始化课堂地图环境。");
    })().catch((error: Error) => {
      setInitError(error.message);
      pushToast("error", "初始化失败", error.message);
    });

    return () => {
      cancelled = true;
    };
  }, [initAttempt, loadKnowledgeBase, pushToast, refreshProjectState, subscribeToJob]);

  useEffect(() => {
    if (!mapRef.current || !layerState?.base_map) {
      return;
    }
    const map = mapRef.current;
    const basemapId = layerState.base_map.id;
    const listenerKeys: Array<unknown> = [];
    const loadStats = { started: 0, finished: 0, errored: 0 };
    basemapLayersRef.current.forEach((layer) => map.removeLayer(layer));
    basemapLayersRef.current = [];

    layerState.base_map.layers
      .slice()
      .sort((left, right) => left.z_index - right.z_index)
      .forEach((descriptor) => {
        const source = new XYZ({
          ...(descriptor.urls.length > 1 ? { urls: descriptor.urls } : { url: descriptor.urls[0] }),
          attributions: descriptor.attribution || undefined,
          crossOrigin: descriptor.cross_origin || "anonymous"
        });
        listenerKeys.push(
          source.on("tileloadstart", () => {
            loadStats.started += 1;
          })
        );
        listenerKeys.push(
          source.on("tileloadend", () => {
            loadStats.finished += 1;
          })
        );
        listenerKeys.push(
          source.on("tileloaderror", () => {
            loadStats.errored += 1;
          })
        );
        const layer = new TileLayer({
          source,
          opacity: descriptor.opacity,
          zIndex: descriptor.z_index
        });
        basemapLayersRef.current.push(layer);
        map.addLayer(layer);
        source.refresh();
      });

    window.requestAnimationFrame(() => {
      map.updateSize();
      map.renderSync();
    });

    const fallbackTimer = window.setTimeout(() => {
      if (!project?.project_id || basemapId === "legacy_xyz") {
        return;
      }
      if (loadStats.finished > 0) {
        return;
      }
      if (loadStats.errored <= 0) {
        return;
      }
      if (loadStats.started > loadStats.errored) {
        return;
      }
      void switchBasemap(project.project_id, "legacy_xyz")
        .then(() => refreshProjectState(project.project_id))
        .then(() => {
          pushToast("info", "底图已自动回退", "当前在线底图未成功加载，已切换到兼容底图。");
        })
        .catch(() => {
          pushToast("error", "底图加载失败", "在线底图与兼容底图均未成功切换。");
        });
    }, 3500);

    return () => {
      window.clearTimeout(fallbackTimer);
      if (listenerKeys.length) {
        unByKey(listenerKeys as never);
      }
    };
  }, [layerState?.base_map, project?.project_id, pushToast, refreshProjectState]);

  useEffect(() => {
    if (!mapRef.current || !layerState) {
      return;
    }
    const map = mapRef.current;
      const format = new GeoJSON();
      businessLayersRef.current.forEach((layer) => map.removeLayer(layer));
      businessLayersRef.current = [];
      vectorLayerByIdRef.current.clear();

    layerState.items
      .slice()
      .sort((left, right) => left.z_index - right.z_index)
      .forEach((record) => {
        if (record.kind === "raster") {
          const assetUrl = String(record.metadata.asset_url || "");
          const bounds = record.metadata.bounds as [number, number, number, number] | undefined;
          if (!assetUrl || !bounds) {
            return;
          }
          const rasterLayer = new ImageLayer({
            source: new ImageStatic({
              url: `${getApiBase()}${assetUrl}`,
              imageExtent: transformExtent(bounds, "EPSG:4326", "EPSG:3857")
            }),
            opacity: record.opacity,
            visible: record.visible,
            zIndex: record.z_index
          });
          businessLayersRef.current.push(rasterLayer);
          map.addLayer(rasterLayer);
          return;
        }

        const features = format.readFeatures(record.data, {
          dataProjection: "EPSG:4326",
          featureProjection: "EPSG:3857"
        });
          const vectorLayer = new VectorLayer({
            source: new VectorSource({ features }),
            visible: record.visible,
            opacity: record.opacity,
            zIndex: record.z_index,
            style: layerStyle(record)
          });
          vectorLayerByIdRef.current.set(record.layer_id, vectorLayer);
          businessLayersRef.current.push(vectorLayer);
        map.addLayer(vectorLayer);
      });

    const serverViewSignature = JSON.stringify(layerState.view || {});
    if (serverViewSignature !== lastAppliedViewRef.current) {
      const targetCenter = fromLonLat(layerState.view.center || [104, 35]);
      const targetZoom = layerState.view.zoom || 4;
      map.getView().animate(
        { center: targetCenter, zoom: targetZoom, duration: 1200, easing: easeOut },
      );
      lastAppliedViewRef.current = serverViewSignature;
    }

    window.requestAnimationFrame(() => {
      map.updateSize();
      map.renderSync();
    });
  }, [layerState]);

  useEffect(() => {
    if (!mapRef.current || !searchAreaSourceRef.current) {
      return;
    }
    const map = mapRef.current;
    const existing = drawInteractionRef.current;
    if (existing) {
      map.removeInteraction(existing);
      drawInteractionRef.current = null;
    }
    if (interactionMode !== "draw-search") {
      return;
    }

    const draw = new Draw({
      source: searchAreaSourceRef.current,
      type: "Polygon"
    });

    draw.on("drawstart", () => {
      searchAreaSourceRef.current?.clear();
      highlightSourceRef.current?.clear();
    });

    draw.on("drawend", (event) => {
      const geometry = event.feature.getGeometry();
      if (!geometry) {
        return;
      }
      const format = new GeoJSON();
      const cloned = geometry.clone();
      cloned.transform("EPSG:3857", "EPSG:4326");
      setSearchAreaGeometry(format.writeGeometryObject(cloned) as Record<string, unknown>);
      setInteractionMode("browse");
      pushToast("success", "检索区已绘制", "现在可以发起区域内 POI 检索。");
    });

    drawInteractionRef.current = draw;
    map.addInteraction(draw);

    return () => {
      if (drawInteractionRef.current) {
        map.removeInteraction(drawInteractionRef.current);
        drawInteractionRef.current = null;
      }
    };
  }, [interactionMode, pushToast]);

  useEffect(() => {
    const { items, summary } = parsePoiResults(layerState);
    setSearchResults(items);
    setSearchSummary(summary);
    const signature = JSON.stringify([summary, items.map((item) => item.poi_id)]);
    if (items.length && signature !== lastPoiSignatureRef.current) {
      lastPoiSignatureRef.current = signature;
      setDrawerOpen(true);
      setDrawerTab("search");
    }
  }, [layerState]);

  const statusSummary = useMemo(
    () => ({
      currentMode: modeLabelMap[interactionMode],
      searchScope: searchScopeLabel,
      latest: statusText,
      activeBasemap: activeBasemapTitle,
      visibleLayers: visibleLayerCount,
      totalLayers: totalLayerCount,
      enabledTemplates: enabledTemplateCount
    }),
    [activeBasemapTitle, enabledTemplateCount, interactionMode, searchScopeLabel, statusText, totalLayerCount, visibleLayerCount]
  );

  return (
    <div className="screen-shell screen-shell-classroom">
      <div ref={mapElementRef} className="map-canvas" data-testid="map-canvas" />
      <div className="map-vignette" />
      <div className="map-grid-overlay" />
      <div className="map-scanline" />
      <RegionFocusOverlay
        label={focusedRegion?.label || ""}
        pixel={focusedRegion?.pixel || null}
        materials={focusedRegionMaterials}
        onOpenMaterials={() => {
          setMaterialViewerTitle(focusedRegion?.label || "地区教学资料");
          setMaterialViewerItems(focusedRegionMaterials);
          setMaterialViewerOpen(true);
        }}
      />

      <header className="app-header glass-panel">
        <div className="brand-block">
          <strong>GeoBot 智能教学平台</strong>
        </div>

        <div className="header-search">
          <span className="header-search-label">POI 检索</span>
          <div className="header-search-row">
            <input
              id="poi-keyword"
              value={searchKeyword}
              onChange={(event) => setSearchKeyword(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void handlePoiSearch("view");
                }
              }}
              placeholder={onlinePoiEnabled ? "输入港口、机场、城市等关键词" : "POI 在线检索未配置"}
              disabled={!onlinePoiEnabled}
            />
            <button type="button" className="toolbar-button compact" disabled={!onlinePoiEnabled} onClick={() => void handlePoiSearch("view")}>
              视域检索
            </button>
            <button
              type="button"
              className="toolbar-button compact"
              disabled={!onlinePoiEnabled || !searchAreaGeometry}
              onClick={() => void handlePoiSearch("polygon")}
            >
              区域检索
            </button>
          </div>
        </div>

        <div className="header-actions">
          <span className={`status-pill ${initError ? "" : busy ? "busy" : "ready"}`}>
            {initError ? "连接异常" : busy ? "任务执行中" : "系统在线"}
          </span>
          <BasemapMenu
            items={basemapItems}
            activeId={activeBasemapId}
            disabled={!project}
            onSelect={async (basemapId) => {
              if (!project) {
                return;
              }
              await switchBasemap(project.project_id, basemapId);
              await refreshProjectState(project.project_id);
              const title = basemapItems.find((item) => item.id === basemapId)?.title || "底图";
              pushToast("success", "底图已切换", `当前底图：${title}`);
            }}
          />
          <button
            type="button"
            className={`toolbar-button ${workflowDockOpen ? "active" : ""}`}
            onClick={() => setWorkflowDockOpen((value) => !value)}
            data-testid="toolbar-workflow-toggle"
          >
            PyQGIS 工作流
          </button>
          <button type="button" className="toolbar-button" onClick={() => setUploadOpen(true)}>
            上传数据
          </button>
          <button type="button" className="toolbar-button" onClick={() => void handleExportSnapshot()}>
            导出截图
          </button>
          <button type="button" className="toolbar-button" onClick={handleResetView}>
            复位视图
          </button>
          {initError ? (
            <button
              type="button"
              className="toolbar-button active"
              onClick={() => {
                setProject(null);
                setLayerState(null);
                setOutputs([]);
                setCurrentJobByMode({ knowledge: null, tool: null });
                setConversationIds({ knowledge: "", tool: "" });
                setSearchResults([]);
                setSearchSummary("");
                setKbItems([]);
                setKbTotal(0);
                setKbEditingItem(null);
                setInitAttempt((value) => value + 1);
              }}
            >
              重试连接
            </button>
          ) : null}
        </div>
      </header>

      <main className="workspace-shell">
        <SideDrawer
          open={drawerOpen}
          activeTab={drawerTab}
          topics={kbTopics}
          layerState={layerState}
            outputs={outputs}
            searchResults={searchResults}
            searchSummary={searchSummary}
            resourceQuery={resourceQuery}
            resourceScope={resourceScope}
            resourceLoading={resourceLoading}
            resourceResults={resourceResults}
            statusSummary={statusSummary}
          onToggleOpen={() => setDrawerOpen((value) => !value)}
          onChangeTab={setDrawerTab}
          onToggleLayer={(layerId, visible) => {
            if (!project) {
              return;
            }
            void patchLayer(project.project_id, layerId, { visible }).then(() => refreshProjectState(project.project_id));
          }}
            onSelectLayer={(layerId) => {
              if (!project) {
                return;
              }
              void patchLayer(project.project_id, layerId, { active: true, visible: true })
                .then(() => refreshProjectState(project.project_id))
                .then(() => focusLayerExtent(layerId));
            }}
          onFocusResult={focusPoiResult}
            onOpenKnowledgeTopic={(topic) => {
              setKbQuery((previous) => ({ ...previous, topic, query: "", tag: "" }));
              void runKbSearch({ topic, query: "", tag: "" });
              setDrawerOpen(true);
              setDrawerTab("resources");
            }}
            onResourceQueryChange={(value) => {
              setResourceQuery(value);
              setDrawerTab("resource-search");
            }}
            onResourceScopeChange={setResourceScope}
            onOpenResourceResult={handleOpenResourceResult}
            onImportResourceResult={handleImportResourceResult}
          />

        <section className="map-workspace" aria-hidden="true" />

        <aside className="right-rail">
          <section className="tool-group glass-panel">
            <div className="tool-group-header">
              <span>课堂动作</span>
            </div>
            <button
              type="button"
              className="tool-button active"
              onClick={() => void handleReadMapWithSnapshot()}
            >
              读图讲解
            </button>
          </section>

          <section className="tool-group glass-panel">
            <div className="tool-group-header">
              <span>地图工具</span>
            </div>
            <button type="button" className={`tool-button ${interactionMode === "browse" ? "active" : ""}`} onClick={() => setInteractionMode("browse")}>
              选择
            </button>
            <button
              type="button"
              className={`tool-button ${interactionMode === "annotate" ? "active" : ""}`}
              onClick={() => setInteractionMode("annotate")}
            >
              标注
            </button>
            <button
              type="button"
              className={`tool-button ${interactionMode === "measure" ? "active" : ""}`}
              onClick={() => setInteractionMode("measure")}
            >
              测距
            </button>
            <button
              type="button"
              className={`tool-button ${interactionMode === "draw-search" ? "active" : ""}`}
              onClick={() => setInteractionMode("draw-search")}
            >
              绘区
            </button>
            <button type="button" className="tool-button" onClick={() => void handleClearWorkspace()}>
              清除
            </button>
            <button
              type="button"
              className="tool-button"
              onClick={() => {
                const map = mapRef.current;
                if (!map) {
                  return;
                }
                map.getView().animate({ zoom: (map.getView().getZoom() || 4) + 1, duration: 300 });
              }}
            >
              放大
            </button>
            <button
              type="button"
              className="tool-button"
              onClick={() => {
                const map = mapRef.current;
                if (!map) {
                  return;
                }
                map.getView().animate({ zoom: (map.getView().getZoom() || 4) - 1, duration: 300 });
              }}
            >
              缩小
            </button>
          </section>

          <TeachingMapPanel
            items={teachingMaps}
            activeIds={activeTeachingMapIds}
            busy={busy}
            onToggle={handleToggleTeachingMap}
          />

        </aside>
        </main>

      {project ? (
        <CopilotWidget
          assistantMode={assistantMode}
          chatLog={chatLog}
          currentJob={currentJob}
          inputValue={assistantInput}
          onInputChange={setAssistantInput}
          onAssistantModeChange={setAssistantMode}
          onSubmit={() => {
            const message = assistantInput.trim();
            if (!message) {
              return;
            }
            void submitAssistantText(message, undefined, "webgis", "text", assistantMode);
            setAssistantInput("");
          }}
          onConfirm={(confirmationId, decision = "approve") => {
            void confirmAssistantAction(confirmationId, decision).then((response) => subscribeToJob(response.job_id, assistantMode));
          }}
          onVoiceSubmit={(message) => {
            const transcript = message.trim();
            if (!transcript) {
              return;
            }
            void submitAssistantText(transcript, undefined, "webgis", "voice", assistantMode);
          }}
          onVoiceNotice={(tone, title, detail) => {
            pushToast(tone, title, detail);
          }}
          busy={busy}
        />
      ) : null}

        <ToastStack items={toasts} onDismiss={dismissToast} />
        <TeachingMaterialViewer
          open={materialViewerOpen}
          title={materialViewerTitle}
          materials={materialViewerItems}
          onClose={() => setMaterialViewerOpen(false)}
        />
        <UploadDialog open={uploadOpen} busy={busy} onClose={() => setUploadOpen(false)} onSubmit={handleUploadDataset} />
        <WorkflowDock
          projectId={project?.project_id || ""}
          mapRef={mapRef}
          open={workflowDockOpen}
          onRequestClose={() => setWorkflowDockOpen(false)}
          onToast={(tone, message) => pushToast(tone, message)}
        />
      </div>
  );
}
