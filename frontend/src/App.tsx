import Polygon from "ol/geom/Polygon";
import MultiPolygon from "ol/geom/MultiPolygon";
import { UrbanStudyPanel, type UrbanSource, type UrbanStatus } from "./components/UrbanStudyPanel";
import { shanghaiDensityColor, densityColor, densityRadius, rankColor } from "./lib/populationVisual";
import { MapEvidenceLegend } from "./components/MapEvidenceLegend";
import { MapToolsDock } from "./components/MapToolsDock";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "ol/ol.css";
import Feature from "ol/Feature";
import GeoJSON from "ol/format/GeoJSON";
import Draw from "ol/interaction/Draw";
import Graticule from "ol/layer/Graticule";
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
import LineString from "ol/geom/LineString";
import Point from "ol/geom/Point";
import { fromLonLat, toLonLat, transformExtent } from "ol/proj";
import { getDistance, getLength } from "ol/sphere";
import { Circle as CircleStyle, Fill, RegularShape, Stroke, Style, Text } from "ol/style";
import { easeOut } from "ol/easing";
import { getCenter } from "ol/extent";
import { resolveCanvasDrawSize } from "./mapScreenshot";
import {
  addCatalogDatasetLayer,
  activateLessonResourceSet,
  buildPublicFileUrl,
  createKbMaterialLink,
  confirmAssistantAction,
  createProject,
  exportSnapshot,
  fetchDatasetCatalog,
  fetchCurrentUser,
  fetchLessonResources,
  fetchHealth,
  fetchKbManifest,
  fetchKbTopics,
  fetchLayers,
  fetchOutputs,
  fetchProject,
  fetchQuestionBanks,
  deleteQuestionBank,
  loadOutputAsLayer,
  deleteOutput,
  saveResourceResult,
  generateImageLibraryAsset,
  getApiBase,
  logSessionEvent,
  deleteLayer,
  patchLayer,
  registerKbLayer,
  renderPptx,
  runTemplate,
  searchKb,
  searchPoi,
  searchResources,
  sendAssistantMessage,
  saveLessonResourceSet,
  switchBasemap,
  summarizeCatalogLayers,
  upsertKbItem,
  uploadDataset,
  uploadImageLibraryAsset,
  uploadKbMaterial,
  fetchTeachingMaps,
  toggleTeachingMap,
  fetchActiveTeachingMaps,
  type TeachingMapItem,
} from "./api";
import { AnnotationDialog } from "./components/AnnotationDialog";
import { BasemapMenu } from "./components/BasemapMenu";
import { BrandLogo } from "./components/BrandLogo";
import { CopilotWidget } from "./components/CopilotWidget";
import { LessonDesignWorkspace } from "./components/LessonDesignWorkspace";
import { DatabaseViewer, type DatabaseCategory } from "./components/DatabaseViewer";
import { LayerManager } from "./components/LayerManager";
import { type KnowledgeQuery } from "./components/KnowledgePanel";
import { Map3DGlobe, type CameraState, type Map3DGlobeHandle } from "./components/Map3DGlobe";
import { MapInstructionStrip } from "./components/MapInstructionStrip";
import { MapStatusBar } from "./components/MapStatusBar";
import { MapToolRail } from "./components/MapToolRail";
import { LessonWorkflowShell } from "./components/LessonWorkflowShell";
import { RegionFocusOverlay } from "./components/RegionFocusOverlay";
import { SearchResultsCard, StatsResultsCard } from "./components/HeaderResultCards";
import { ScreenshotSelector, type ScreenshotSelection } from "./components/ScreenshotSelector";
import { TeachingMaterialViewer } from "./components/TeachingMaterialViewer";
import { ToastStack, type ToastItem } from "./components/ToastStack";
import { UploadDialog } from "./components/UploadDialog";
import { VisualMapPanel } from "./components/VisualMapPanel";
import { WorkflowDock } from "./components/WorkflowDock";
import { UserMenu } from "./components/UserMenu";
import { PptViewer } from "./components/PptViewer";
import { type BrushOverlayHandle, type BrushSettings } from "./components/BrushOverlay";
import { BrushToolbar } from "./components/BrushToolbar";
import {
  DOUBLE_CLICK_LANDING_ALTITUDE,
  PLANE_TO_GLOBE_ZOOM_THRESHOLD,
  altitudeToZoom,
  zoomToAltitude
} from "./lib/altitudeZoom";
import { parsePptxFile, releaseSlideObjectUrls } from "./lib/pptxRenderer";
import { decideLessonGlobeScene } from "./lib/lessonGlobeScene";
import { MapBrushOverlay } from "./components/MapBrushOverlay";
import type { MapInkProjection } from "./lib/mapInk";
import type { ViewMode } from "./lib/viewMode";
import type {
  AssistantInputMode,
  AssistantMode,
  AssistantTab,
  AssistantTarget,
  AssistantUiAction,
  ArtifactRecord,
  AuthUser,
  ChatMessage,
  DatasetCatalogItem,
  DatasetStatsResponse,
  ExecutedAction,
  HealthResponse,
  ImageAttachment,
  JobRecord,
  KnowledgeBaseItem,
  KnowledgeTopicSummary,
  QuestionBankSummary,
  LessonGlobeScene,
  LessonResourceSet,
  LayerRecord,
  LayersResponse,
  MapContext,
  PoiSearchItem,
  ProjectRecord,
  RegionBinding,
  ResourceSearchResult,
  SlideContent,
  TeachingContext,
  TeachingContract,
  TeachingMaterial
} from "./types";
import { speak, cancelSpeech } from "./speechSynthesis";
import { AgentControlOverlay } from "./components/AgentControlOverlay";
import "./styles.css";
import "./lesson-workflow.css";
import { ThemeToggle } from "./theme";

const PROJECT_ID_STORAGE_KEY = "webgis_ai_project_id";

function projectStorageKey(userId: string): string {
  return `${PROJECT_ID_STORAGE_KEY}:${userId}`;
}

function readStoredProjectId(userId: string): string {
  try {
    return window.localStorage.getItem(projectStorageKey(userId)) || "";
  } catch {
    return "";
  }
}

function storeProjectId(userId: string, projectId: string): void {
  try {
    window.localStorage.setItem(projectStorageKey(userId), projectId);
  } catch {
    // localStorage 不可用时退化为每次新建项目
  }
}

type InteractionMode = "browse" | "annotate" | "measure" | "draw-search" | "brush";
type RenderableLayer = TileLayer<XYZ> | ImageLayer<ImageStatic> | VectorLayer<any>;
type FocusedRegion = {
  label: string;
  layerId: string;
  properties: Record<string, unknown>;
  pixel: [number, number] | null;
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

export function captureMapSnapshot(map: Map): Promise<string> {
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
        let transformValues: number[] | null = null;
        if (transform) {
          const values = transform
            .replace("matrix(", "")
            .replace(")", "")
            .split(",")
            .map((value) => Number(value.trim()));
          if (values.length === 6) {
            transformValues = values;
            context.setTransform(values[0], values[1], values[2], values[3], values[4], values[5]);
          } else {
            context.setTransform(1, 0, 0, 1, 0, 0);
          }
        } else {
          context.setTransform(1, 0, 0, 1, 0, 0);
        }
        const drawSize = resolveCanvasDrawSize(sourceCanvas, transformValues);
        context.drawImage(
          sourceCanvas,
          0,
          0,
          sourceCanvas.width,
          sourceCanvas.height,
          0,
          0,
          drawSize.width,
          drawSize.height
        );
      });

      context.setTransform(1, 0, 0, 1, 0, 0);
      try {
        resolve(canvas.toDataURL("image/png"));
      } catch {
        resolve("");
      }
    });
    map.renderSync();
  });
}

function cropSnapshot(dataUrl: string, selection: ScreenshotSelection): Promise<string> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const scaleX = image.naturalWidth / Math.max(selection.viewportWidth, 1);
      const scaleY = image.naturalHeight / Math.max(selection.viewportHeight, 1);
      const sourceX = Math.max(0, Math.round(selection.left * scaleX));
      const sourceY = Math.max(0, Math.round(selection.top * scaleY));
      const sourceWidth = Math.min(image.naturalWidth - sourceX, Math.max(1, Math.round(selection.width * scaleX)));
      const sourceHeight = Math.min(image.naturalHeight - sourceY, Math.max(1, Math.round(selection.height * scaleY)));
      const canvas = document.createElement("canvas");
      canvas.width = sourceWidth;
      canvas.height = sourceHeight;
      const context = canvas.getContext("2d");
      if (!context) {
        reject(new Error("浏览器无法创建截图画布。"));
        return;
      }
      context.drawImage(image, sourceX, sourceY, sourceWidth, sourceHeight, 0, 0, sourceWidth, sourceHeight);
      const pixels = context.getImageData(0, 0, sourceWidth, sourceHeight).data;
      const first = [pixels[0], pixels[1], pixels[2], pixels[3]];
      let hasVisibleVariation = false;
      const stride = Math.max(4, Math.floor(pixels.length / 4096 / 4) * 4);
      for (let index = 0; index < pixels.length; index += stride) {
        if (
          pixels[index + 3] !== 0 &&
          (pixels[index] !== first[0] || pixels[index + 1] !== first[1] || pixels[index + 2] !== first[2] || pixels[index + 3] !== first[3])
        ) {
          hasVisibleVariation = true;
          break;
        }
      }
      if (!hasVisibleVariation) {
        reject(new Error("所选区域没有可保存的地图内容，请重新框选。"));
        return;
      }
      resolve(canvas.toDataURL("image/png"));
    };
    image.onerror = () => reject(new Error("截图画面读取失败。"));
    image.src = dataUrl;
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

function layerStyle(record: LayerRecord, showFit = false) {
  const visualization = record.metadata?.visualization as { items?: unknown[] } | undefined;
  const rankCount = (Array.isArray(visualization?.items) ? visualization.items.length : 0)
    || (Array.isArray(record.data.features) ? record.data.features.length : 0) || 20;
  return (feature: { getGeometry: () => { getType: () => string } | undefined; get: (key: string) => unknown }) => {
    const geometryType = feature.getGeometry()?.getType() || record.geometry_type;
    if (record.layer_id === "generated_hu_line" && feature.get("line_type") === "dynamic" && !showFit) return undefined;
    const densityTemplate = ["builtin_population_regions", "builtin_population_density"].includes(record.layer_id);
    const ranked = Boolean(record.metadata?.visualization) && Number(feature.get("rank")) > 0;
    let fillColor = String(record.style.fillColor || feature.get("__fillColor") || "#47a3ff");
    let fillOpacity = Number(record.style.fillOpacity || feature.get("__fillOpacity") || 0.22);
    let strokeColor = String(record.style.strokeColor || feature.get("__strokeColor") || "#e7edf5");
    let strokeWidth = Number(record.style.strokeWidth || feature.get("__strokeWidth") || 2);
    let radius = Number(record.style.radius || feature.get("__radius") || 7);
    if (densityTemplate) {
      fillColor = densityColor(feature.get("density")); fillOpacity = .88; strokeColor = "#ffffff"; strokeWidth = .9;
      radius = densityRadius(feature.get("density"));
    }
    if (record.metadata?.catalog_id === "shanghai_population_density") {
      fillColor = shanghaiDensityColor(feature.get("density"));
      fillOpacity = 0.98; strokeColor = "#4b7776"; strokeWidth = 0.9;
    }
    if (ranked) { fillColor = rankColor(Number(feature.get("rank")), rankCount); fillOpacity = .94; strokeColor = "#ffffff"; strokeWidth = 1.4; }
    if (record.layer_id === "generated_hu_line") { strokeColor = feature.get("line_type") === "dynamic" ? "#d88a26" : "#07575f"; strokeWidth = feature.get("line_type") === "dynamic" ? 2 : 3; }
    const labelField = String(record.style.labelField || "name");
    const labelValue = String(feature.get(labelField) || feature.get("name") || "");
    const catalogId = String(record.metadata?.catalog_id || "");
    const coverage = String(record.metadata?.coverage || "").toLowerCase();
    const templateId = String(record.metadata?.template_id || "");
    const provinceLevelLayer = (
      coverage.includes("china province-level") ||
      [
        "china_provinces",
        "china_province_population_density",
        "china_aging_rate_province",
        "china_province_gdp_per_capita"
      ].includes(catalogId) ||
      ["population_distribution", "population_density", "hu_line_comparison"].includes(templateId)
    );

    return new Style({
      fill: geometryType.includes("Polygon") ? new Fill({ color: withOpacity(fillColor, fillOpacity) }) : undefined,
      stroke: new Stroke({
        color: strokeColor,
        width: strokeWidth,
        lineDash: record.layer_id === "generated_hu_line" ? feature.get("line_type") === "dynamic" ? [7, 5] : undefined : (feature.get("__lineDash") as number[] | undefined) || undefined
      }),
      image: geometryType.includes("Point")
        ? new CircleStyle({
            declutterMode: densityTemplate ? "none" : undefined,
            radius,
            fill: new Fill({ color: withOpacity(fillColor, Math.min(fillOpacity + 0.36, 0.9)) }),
            stroke: new Stroke({ color: strokeColor, width: 1.2 })
          })
        : undefined,
      text: labelValue && (!provinceLevelLayer || geometryType.includes("Point"))
        ? new Text({
            text: labelValue,
            font: "500 12px 'Microsoft YaHei UI', 'Segoe UI', sans-serif",
            fill: new Fill({ color: "#18343f" }),
            stroke: new Stroke({ color: "#ffffff", width: 3 }),
            backgroundFill: new Fill({ color: "rgba(255,255,255,.9)" }),
            padding: [3, 4, 3, 4],
            offsetY: geometryType.includes("Point") ? -(radius + 12) : 0
          })
        : undefined
    });
  };
}

export default function App({
  currentUser,
  onLogout,
  onUserChanged
}: {
  currentUser: AuthUser;
  onLogout: () => void;
  onUserChanged: (user: AuthUser) => void;
}) {
  const mapElementRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
    const basemapLayersRef = useRef<RenderableLayer[]>([]);
    // 按 layer_id 缓存已构建的 OpenLayers 图层：GeoJSON 解析开销大，只有
    // 数据版本（data_rev）变化时才重建，可见性/透明度/层级直接原地更新。
    const businessLayerCacheRef = useRef<
      globalThis.Map<string, { signature: string; styleKey: string; olLayer: RenderableLayer }>
    >(new globalThis.Map());
    const vectorLayerByIdRef = useRef<globalThis.Map<string, VectorLayer<any>>>(new globalThis.Map());
    const searchAreaSourceRef = useRef<VectorSource | null>(null);
  const highlightSourceRef = useRef<VectorSource | null>(null);
  const annotationSourceRef = useRef<VectorSource | null>(null);
  const measureSourceRef = useRef<VectorSource | null>(null);
  const graticuleLayerRef = useRef<Graticule | null>(null);
  const drawInteractionRef = useRef<Draw | null>(null);
  const measureDrawRef = useRef<Draw | null>(null);
  const interactionModeRef = useRef<InteractionMode>("browse");
  const lastAppliedViewRef = useRef("");
  const lastPoiSignatureRef = useRef("");
  const assistantDispatchRef = useRef<(
    message: string,
    overrides?: Partial<MapContext>,
    displayMessage?: string
  ) => void>(() => undefined);
  // 课堂工作流（课前/课中/课后）当前所处的 lesson/session/stage/phase，随每次
  // 助教请求发给后端，让智能体知道自己正在服务哪节课的哪个环节。
  const teachingContextRef = useRef<TeachingContext | null>(null);
  // 同步一份 phase 到 state：助教面板头部的阶段徽标与能力芯片排序需要触发渲染。
  const [teachingPhase, setTeachingPhase] = useState<TeachingContext["phase"]>("");
  const [copilotOpenSignal, setCopilotOpenSignal] = useState(0);
  const activeJobStreamsRef = useRef(0);
  const jobStreamsRef = useRef<Set<EventSource>>(new Set());
  const assistantSubmittingRef = useRef(false);
  const resourceSearchRequestRef = useRef(0);
  const pendingEvidenceSnapshotRef = useRef<{ sessionId: string; stageId: string } | null>(null);

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [project, setProject] = useState<(ProjectRecord & { status: string }) | null>(null);
  const [layerState, setLayerState] = useState<LayersResponse | null>(null);
  const [outputs, setOutputs] = useState<ArtifactRecord[]>([]);
  const assistantMode: AssistantMode = "teaching";
  const [currentJob, setCurrentJob] = useState<JobRecord | null>(null);
  const [chatLog, setChatLog] = useState<ChatMessage[]>([
    {
      role: "assistant",
      text: "这里是专业教学智能体，可以讲解地理概念、判读当前地图、设计课堂追问、执行课堂地图操作，并在操作后给出教学解释。",
      timestamp: timestamp()
    }
  ]);
  const [conversationId, setConversationId] = useState("");
  // ===== 智能交互（interaction 模式）=====
  // 与教学助手共享 CopilotWidget，但各持独立会话线程；语音/TTS/光晕都只属于交互 Tab。
  const [assistantTab, setAssistantTab] = useState<AssistantTab>("teaching");
  const assistantTabRef = useRef<AssistantTab>("teaching");
  const [interactionChatLog, setInteractionChatLog] = useState<ChatMessage[]>([
    {
      role: "assistant",
      text: "智能交互模式已就绪：点麦克风说指令，或开启常开聆听后说“小智，切换到三维地球”。高频指令走快速通道，秒级响应。",
      timestamp: timestamp()
    }
  ]);
  const [interactionConversationId, setInteractionConversationId] = useState("");
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const lastInputModeRef = useRef<AssistantInputMode>("text");
  const lastSubmittedTabRef = useRef<AssistantTab>("teaching");
  const [interactionBusy, setInteractionBusy] = useState(false);
  const [overlayListening, setOverlayListening] = useState(false);
  const [overlayPartial, setOverlayPartial] = useState("");
  const [overlayCaptured, setOverlayCaptured] = useState("");
  const [overlayPulse, setOverlayPulse] = useState(0);
  const transitionToPlaneRef = useRef<((opts: { lon: number; lat: number; zoom?: number; reason: "manual" | "altitude" | "dblclick" }) => void) | null>(null);
  const transitionToGlobeRef = useRef<((opts: { lon?: number; lat?: number; zoom?: number; reason: "manual" | "zoom" }) => void) | null>(null);
  const [assistantInput, setAssistantInput] = useState("");
  const [pendingImage, setPendingImage] = useState<ImageAttachment | null>(null);
  const [imageGenerationLoading, setImageGenerationLoading] = useState(false);
  const [screenshotSource, setScreenshotSource] = useState("");
  const [screenshotBounds, setScreenshotBounds] = useState<{ left: number; top: number; width: number; height: number } | null>(null);
  const [interactionMode, setInteractionMode] = useState<InteractionMode>("browse");
  const [measureText, setMeasureText] = useState("");
  const [measureTotalKm, setMeasureTotalKm] = useState<number | null>(null);
  const [annotationCount, setAnnotationCount] = useState(0);
  const [measurementCount, setMeasurementCount] = useState(0);
  const [annotationDraft, setAnnotationDraft] = useState<{ lonLat: [number, number] } | null>(null);
  const [selectedFeatureText, setSelectedFeatureText] = useState("");
  const [brushSettings, setBrushSettings] = useState<BrushSettings>({
    tool: "freehand",
    color: "#ff4444",
    lineWidth: 4
  });
  const brushRef = useRef<BrushOverlayHandle | null>(null);
  const pptBrushRef = useRef<BrushOverlayHandle | null>(null);
  const [mapBrushHasContent, setMapBrushHasContent] = useState(false);
  const [pptBrushHasContent, setPptBrushHasContent] = useState(false);
  // ── 3D digital-globe state ───────────────────────────────────────────
  // Boot into the 3D globe view; users land on the digital earth first
  // and can drill in to the 2D map either by zooming, double-clicking, or
  // toggling the header button.
  const [urbanActive, setUrbanActive] = useState(false);
  const [urbanSource, setUrbanSource] = useState<UrbanSource|null>(null);
  const [urbanStatus, setUrbanStatus] = useState<UrbanStatus>("idle");
  const [viewMode, setViewMode] = useState<ViewMode>("globe");
  const [showGraticule, setShowGraticule] = useState(false);
  const [globeCamera, setGlobeCamera] = useState<CameraState | null>(null);
  // Active 3D thematic teaching layers (population columns, Hu line, …).
  const [globeThemeIds, setGlobeThemeIds] = useState<string[]>([]);
  const [showTeachingFit, setShowTeachingFit] = useState(false);
  // Mirror of the OpenLayers view center/zoom so the bottom status bar
  // stays live while the user pans / zooms the 2D map.
  const [planeViewState, setPlaneViewState] = useState<{
    lon: number;
    lat: number;
    zoom: number;
  } | null>(null);
  const globeRef = useRef<Map3DGlobeHandle | null>(null);
  const mapInkProjection = useMemo<MapInkProjection>(() => ({
    toWorld: (client) => {
      if (viewMode === "globe") return globeRef.current?.inkToWorld(client) || null;
      const map=mapRef.current; if(!map) return null;
      const rect=map.getViewport().getBoundingClientRect(), size=map.getSize();
      if(!size || !rect.width || !rect.height) return null;
      const coordinate=map.getCoordinateFromPixel([(client[0]-rect.left)*size[0]/rect.width,(client[1]-rect.top)*size[1]/rect.height]);
      return coordinate ? toLonLat(coordinate) as [number,number] : null;
    },
    toClient: (world) => {
      if (viewMode === "globe") return globeRef.current?.inkToClient(world) || null;
      const map=mapRef.current; if(!map) return null;
      const rect=map.getViewport().getBoundingClientRect(), size=map.getSize();
      const pixel=map.getPixelFromCoordinate(fromLonLat(world));
      return pixel && size && size[0] && size[1] ? [rect.left+pixel[0]*rect.width/size[0],rect.top+pixel[1]*rect.height/size[1]] : null;
    },
    subscribe: (render) => {
      if(viewMode === "globe") return globeRef.current?.subscribeInkRender(render);
      const map=mapRef.current; if(!map) return undefined;
      map.on("postrender",render); return () => { map.un("postrender",render); };
    }
  }), [viewMode]);
  const planeAutoArmedRef = useRef(true);
  // Timestamp until which plane→globe auto transitions are suppressed. Set
  // before programmatic view changes (layer-load fit, teaching-map fly) so a
  // world-extent layer cannot yank the class into 3D right after loading.
  const programmaticViewGuardUntilRef = useRef(0);
  const lessonGlobePinnedRef = useRef(false);
  const lessonGlobeRestoreRef = useRef<{
    viewMode: ViewMode;
    themeIds: string[];
    camera: CameraState | null;
    plane: { lon: number; lat: number; zoom: number } | null;
  } | null>(null);
  const [searchKeyword, setSearchKeyword] = useState("");
  const [searchDropdownOpen, setSearchDropdownOpen] = useState(false);
  const [searchResults, setSearchResults] = useState<PoiSearchItem[]>([]);
  const [searchSummary, setSearchSummary] = useState("");
  const [oneMapStats, setOneMapStats] = useState<DatasetStatsResponse | null>(null);
  const [searchAreaGeometry, setSearchAreaGeometry] = useState<Record<string, unknown> | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [databaseViewerOpen, setDatabaseViewerOpen] = useState(false);
  const [databaseCategory, setDatabaseCategory] = useState<DatabaseCategory>("all");
  const [layerManagerOpen, setLayerManagerOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [workflowDockOpen, setWorkflowDockOpen] = useState<boolean>(false);
  const [searchCardOpen, setSearchCardOpen] = useState(false);
  const [statsCardOpen, setStatsCardOpen] = useState(false);
  const [kbQuery, setKbQuery] = useState<KnowledgeQuery>({ query: "", topic: "", region: "", tag: "" });
    const [kbItems, setKbItems] = useState<KnowledgeBaseItem[]>([]);
    const [kbAllItems, setKbAllItems] = useState<KnowledgeBaseItem[]>([]);
  const [kbTopics, setKbTopics] = useState<KnowledgeTopicSummary[]>([]);
  const [kbTotal, setKbTotal] = useState(0);
    const [kbLoading, setKbLoading] = useState(false);
    const [kbEditingItem, setKbEditingItem] = useState<KnowledgeBaseItem | null>(null);
    const [resourceQuery, setResourceQuery] = useState("");
    const [resourceScope, setResourceScope] = useState<"all" | "kb" | "web">("all");
    const [resourceLoading, setResourceLoading] = useState(false);
    const [resourceResults, setResourceResults] = useState<ResourceSearchResult[]>([]);
    const [questionBanks, setQuestionBanks] = useState<QuestionBankSummary[]>([]);
    const [lessonResourceSets, setLessonResourceSets] = useState<LessonResourceSet[]>([]);
    const [activeLessonResourceSetId, setActiveLessonResourceSetId] = useState("");
    const [focusedRegion, setFocusedRegion] = useState<FocusedRegion | null>(null);
    const [materialViewerOpen, setMaterialViewerOpen] = useState(false);
    const [materialViewerTitle, setMaterialViewerTitle] = useState("");
    const [materialViewerItems, setMaterialViewerItems] = useState<TeachingMaterial[]>([]);
    const [teachingMaps, setTeachingMaps] = useState<TeachingMapItem[]>([]);
    const [datasetCatalogItems, setDatasetCatalogItems] = useState<DatasetCatalogItem[]>([]);
    const [datasetCatalogError, setDatasetCatalogError] = useState(false);
    const [workflowInitialDataset, setWorkflowInitialDataset] = useState("");
    const [activeTeachingMapIds, setActiveTeachingMapIds] = useState<Set<string>>(new Set());
    const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [pptViewerOpen, setPptViewerOpen] = useState(false);
  const [pptSlides, setPptSlides] = useState<SlideContent[]>([]);
  const [pptFileName, setPptFileName] = useState("");
  const [pptLoading, setPptLoading] = useState(false);
  const pptPresentationReady = pptSlides.length > 0;
  const brushTargetRef = pptViewerOpen && pptPresentationReady ? pptBrushRef : brushRef;
  const brushTargetHasContent = pptViewerOpen && pptPresentationReady ? pptBrushHasContent : mapBrushHasContent;
  // 单调递增信号：侧栏“上课模式”按钮触发 LessonWorkflowShell 打开课中/课前面板。
  const [lessonWorkflowOpenSignal, setLessonWorkflowOpenSignal] = useState(0);
  // 全屏教案设计工作台：query 参数 ?workspace=lesson-design&design_id=... 可恢复。
  const [lessonDesignWorkspace, setLessonDesignWorkspace] = useState<{ open: boolean; designId: string }>({ open: false, designId: "" });
  // 教案定稿后「进入模拟测试」：把目标课时传给课堂工作流外壳（单调递增信号触发打开）。
  const [rehearsalTarget, setRehearsalTarget] = useState<{ lessonId: string; signal: number }>({ lessonId: "", signal: 0 });
  const [initAttempt, setInitAttempt] = useState(0);
  const [initError, setInitError] = useState("");
  const connectionReady = Boolean(project && health && !initError);

  // 全屏教案设计工作台：URL 同步（?workspace=lesson-design&design_id=...），刷新/回退可恢复。
  const openLessonDesignWorkspace = useCallback((designId = "") => {
    setLessonDesignWorkspace({ open: true, designId });
    const params = new URLSearchParams(window.location.search);
    params.set("workspace", "lesson-design");
    if (designId) {
      params.set("design_id", designId);
    } else {
      params.delete("design_id");
    }
    window.history.pushState({ workspace: "lesson-design" }, "", `${window.location.pathname}?${params.toString()}`);
  }, []);
  const closeLessonDesignWorkspace = useCallback(() => {
    setLessonDesignWorkspace({ open: false, designId: "" });
    const params = new URLSearchParams(window.location.search);
    params.delete("workspace");
    params.delete("design_id");
    const query = params.toString();
    window.history.pushState({}, "", query ? `${window.location.pathname}?${query}` : window.location.pathname);
  }, []);
  useEffect(() => {
    const readWorkspace = () => {
      const params = new URLSearchParams(window.location.search);
      if (params.get("workspace") === "lesson-design") {
        setLessonDesignWorkspace({ open: true, designId: params.get("design_id") || "" });
      } else {
        setLessonDesignWorkspace((current) => (current.open ? { open: false, designId: "" } : current));
      }
    };
    readWorkspace();
    window.addEventListener("popstate", readWorkspace);
    return () => window.removeEventListener("popstate", readWorkspace);
  }, []);

  const onlinePoiEnabled = health?.online_services.amap_poi_enabled ?? false;
  const basemapItems = health?.basemaps.items || [];
  const activeBasemapId = layerState?.base_map.id || health?.basemaps.default_id || "";
  const kbActiveLayerId = layerState?.active_layer_id || "";
  const hasVisibleOneMapLayer = Boolean(
    layerState?.items.some((item) => item.source === "one_map_catalog" && item.visible)
  );
  // 课本地图：改用一张图目录中的真实地理数据（GeoJSON 矢量图层），
  // 替代旧的静态贴图（无投影的教材扫描图不适合叠加分析）。
  const textbookMapItems = useMemo(() => {
    const categoryMeta: Record<string, { label: string; order: number }> = {
      population: { label: "人口", order: 1 },
      shanghai: { label: "人口", order: 1 },
      boundaries: { label: "行政边界", order: 2 },
      climate: { label: "气候", order: 3 },
      economy: { label: "经济", order: 4 },
      themes: { label: "专题", order: 5 },
      transport: { label: "城市与交通", order: 6 }
    };
    return datasetCatalogItems
      .filter((item) => item.format === "geojson" && item.status !== "missing")
      .map((item) => {
        const meta = categoryMeta[item.category] || { label: "其他", order: 99 };
        return {
          id: item.id,
          name: item.name.replace(/\s*GeoJSON$/i, ""),
          category: meta.label,
          category_order: meta.order,
          status: item.status,
          source_name: item.source_name
        };
      });
  }, [datasetCatalogItems]);
  const textbookActiveIds = useMemo(() => {
    const ids = new Set<string>();
    (layerState?.items || []).forEach((item) => {
      if (item.source === "one_map_catalog" && item.visible) {
        const catalogId = String(item.metadata?.catalog_id || item.layer_id.replace(/^one_map_/, ""));
        ids.add(catalogId);
      }
    });
    return ids;
  }, [layerState?.items]);
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

  const appendChat = useCallback(
    (
      role: ChatMessage["role"],
      text: string,
      teachingContract?: TeachingContract | null,
      intent?: string | null,
      actionsExecuted?: ExecutedAction[] | null,
      imageAttachment?: ImageAttachment | null,
      planner?: string | null,
      targetTab?: AssistantTab
    ) => {
      if (!text.trim() && !imageAttachment) {
        return;
      }
      const message: ChatMessage = {
        role,
        text,
        timestamp: timestamp(),
        teaching_contract: teachingContract ?? undefined,
        intent: intent ?? undefined,
        actions_executed: actionsExecuted ?? undefined,
        image_attachment: imageAttachment ?? undefined,
        planner: planner ?? undefined
      };
      if (targetTab === "interaction") {
        setInteractionChatLog((previous) => [...previous, message]);
        return;
      }
      setChatLog((previous) => [...previous, message]);
    },
    []
  );

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

    // 资源检索按需触发：只在数据库面板打开且教师提交（回车/按钮/切换范围）
    // 时请求，修掉原先全局 effect 在面板关闭时也持续联网的问题。
    const runResourceSearch = useCallback(
      (query: string, scope: "all" | "kb" | "web") => {
        const trimmed = query.trim();
        const requestId = ++resourceSearchRequestRef.current;
        if (!trimmed) {
          setResourceResults([]);
          setResourceLoading(false);
          return;
        }
        setResourceLoading(true);
        searchResources({ query: trimmed, scope, limit: 16 })
          .then((response) => {
            if (resourceSearchRequestRef.current === requestId) {
              setResourceResults(response.items);
            }
          })
          .catch((error: Error) => {
            if (resourceSearchRequestRef.current === requestId) {
              pushToast("error", "资料搜索失败", error.message);
            }
          })
          .finally(() => {
            if (resourceSearchRequestRef.current === requestId) {
              setResourceLoading(false);
            }
          });
      },
      [pushToast]
    );

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
        const highlighted = firstFeature.clone();
        highlighted.set("__selectedLabel", regionLabel(firstFeature.getProperties()), true);
        highlightSourceRef.current?.addFeature(highlighted);
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
          setDatabaseViewerOpen(true);
          setDatabaseCategory("resources");
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
        // 联网结果先落库为「检索收藏」素材，再进入本课时节。
        if (project) {
          void (async () => {
            try {
              const saved = await saveResourceResult(project.project_id, {
                title: item.title || "检索资料",
                url: item.url,
                summary: item.summary || "",
                source: item.source || "",
                type: item.type || "",
                thumbnail_url: item.thumbnail_url || "",
              });
              await loadKnowledgeBase();
              if (saved.material) {
                // saved.material 需要父条目信息：用刚保存的收藏条目组装。
                const collectionItem = kbAllItems.find((kbItem) => kbItem.id === saved.kb_item_id);
                void importToLesson(collectionItem || ({ id: saved.kb_item_id } as KnowledgeBaseItem), saved.material);
                return;
              }
              pushToast("success", "已保存到知识库", "可在「教学资料 · 检索收藏」中查看");
            } catch (error) {
              pushToast("error", "保存失败", error instanceof Error ? error.message : "请求失败");
            }
          })();
          return;
        }
        pushToast("info", "暂不能导入", "该结果不是知识库条目或已保存素材。");
      },
      [importToLesson, loadKnowledgeBase, project, pushToast]
    );

    const handleSaveResourceResult = useCallback(
      (item: ResourceSearchResult) => {
        if (!project) {
          pushToast("info", "暂不能保存", "请先等待项目初始化完成。");
          return;
        }
        void (async () => {
          try {
            await saveResourceResult(project.project_id, {
              title: item.title || "检索资料",
              url: item.url,
              summary: item.summary || "",
              source: item.source || "",
              type: item.type || "",
              thumbnail_url: item.thumbnail_url || "",
            });
            await loadKnowledgeBase();
            pushToast("success", "已保存为素材", `「${item.title || "检索资料"}」已存入知识库·检索收藏`);
          } catch (error) {
            pushToast("error", "保存失败", error instanceof Error ? error.message : "请求失败");
          }
        })();
      },
      [loadKnowledgeBase, project, pushToast]
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
          teaching_context: teachingContextRef.current || undefined,
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

  const handleAssistantUiActions = useCallback(
    (payload: JobRecord) => {
      const executed = payload.result?.actions_executed || [];
      const uiActions = executed.flatMap((entry) => {
        const result = entry.result || {};
        return Array.isArray(result.ui_actions) ? (result.ui_actions as AssistantUiAction[]) : [];
      });
      for (const action of uiActions) {
        if (!action || typeof action !== "object") {
          continue;
        }
        if (action.type === "open_material") {
          const materials = action.materials || [];
          if (!materials.length) {
            continue;
          }
          setMaterialViewerTitle(action.title || materials[0]?.title || "课堂资料");
          setMaterialViewerItems(materials);
          setMaterialViewerOpen(true);
          setOverlayPulse((value) => value + 1);
          continue;
        }
        if (action.type === "switch_view") {
          setOverlayPulse((value) => value + 1);
          if (action.mode === "plane") {
            const center = project?.view?.center || [104, 35];
            transitionToPlaneRef.current?.({ lon: Number(center[0]), lat: Number(center[1]), reason: "manual" });
          } else {
            transitionToGlobeRef.current?.({ reason: "manual" });
          }
          continue;
        }
        if (action.type === "open_panel") {
          setOverlayPulse((value) => value + 1);
          const open = action.open !== false;
          if (action.panel === "layers") {
            setLayerManagerOpen(open);
          } else if (action.panel === "database") {
            setDatabaseViewerOpen(open);
          } else if (action.panel === "workflow") {
            setWorkflowDockOpen(open);
          }
          continue;
        }
      }
    },
    [project]
  );

  const subscribeToJob = useCallback(
    (jobId: string) => {
      const source = new EventSource(`${getApiBase()}/jobs/${jobId}/stream`, {
        withCredentials: true
      });
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
        setCurrentJob(payload);
        if (payload.status === "completed" || payload.status === "failed") {
          if (!closeJobStream(source)) {
            return;
          }
          const uiOnly = Boolean(payload.result?.actions_executed?.length) && payload.result!.actions_executed!.every(
            (entry) => ["switch_view_mode", "open_panel"].includes(entry.action.tool_name)
          );
          if (!uiOnly) {
            try {
              await refreshProjectState(payload.project_id);
            } catch (error) {
              pushToast("error", "地图状态刷新失败", error instanceof Error ? error.message : "请重试刷新地图。");
            }
          }
          handleAssistantUiActions(payload);
          const message = payload.result?.assistant_message || payload.result?.summary || payload.error || "";
          const nextConversationId = String(payload.result?.conversation_id || "");
          const submittedTab = lastSubmittedTabRef.current;
          if (nextConversationId) {
            if (submittedTab === "interaction") {
              setInteractionConversationId(nextConversationId);
            } else {
              setConversationId(nextConversationId);
            }
          }
          appendChat(
            payload.status === "failed" ? "system" : "assistant",
            message,
            payload.result?.teaching_contract,
            payload.result?.intent,
            payload.result?.actions_executed,
            undefined,
            payload.result?.planner,
            submittedTab
          );
          if (submittedTab === "interaction") {
            setInteractionBusy(false);
            // 语音发起的交互回合：播报结果（可关）。新回合开始时会先 cancel。
            if (payload.status === "completed" && ttsEnabled && lastInputModeRef.current === "voice" && message) {
              speak(message);
            }
          }
          const isAssistantAnswer = Boolean(payload.result?.assistant_message || payload.result?.conversation_id);
          if (payload.status === "failed") {
            pushToast("error", "任务失败", payload.error || message);
          } else if (!isAssistantAnswer) {
            pushToast("success", "任务完成", payload.result?.summary || message);
          }
        }
      });
      source.addEventListener("error", () => {
        if (closeJobStream(source)) {
          pushToast("error", "任务流断开", "事件流提前关闭，请重试当前操作。");
          void fetchCurrentUser().catch(() => undefined);
        }
      });
    },
    [appendChat, closeJobStream, handleAssistantUiActions, pushToast, refreshProjectState, ttsEnabled]
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
      imageAttachment?: ImageAttachment | null,
      displayMessage?: string
    ): Promise<boolean> => {
      if (!project) {
        return false;
      }
      const effectiveMessage = message.trim() || (imageAttachment ? "请识别并分析这张图片中的地理信息。" : "");
      if (!effectiveMessage || assistantSubmittingRef.current) return false;
      assistantSubmittingRef.current = true;
      // 智能交互 Tab 走 interaction 模式（独立会话、直达工具规划）；
      // 教学助手 Tab 保持 teaching 模式与既有行为完全一致。
      const submittedTab: AssistantTab = assistantTabRef.current === "interaction" ? "interaction" : "teaching";
      const requestMode: AssistantMode = submittedTab === "interaction" ? "interaction" : assistantMode;
      lastInputModeRef.current = inputMode;
      lastSubmittedTabRef.current = submittedTab;
      cancelSpeech();
      try {
        const response = await sendAssistantMessage(project.project_id, effectiveMessage, buildMapContext(overrides), target, inputMode, {
          assistantMode: requestMode,
          conversationId:
            submittedTab === "interaction"
              ? interactionConversationId || undefined
              : health?.ui.assistant_v2_enabled
                ? conversationId
                : undefined,
          history:
            submittedTab === "interaction"
              ? undefined
              : health?.ui.assistant_v2_enabled
                ? chatLog
                : undefined,
          imageAttachments: imageAttachment ? [{ artifact_id: imageAttachment.artifact_id }] : [],
          teachingContext: teachingContextRef.current || undefined
        });
        appendChat("user", displayMessage || effectiveMessage, null, null, null, imageAttachment, undefined, submittedTab);
        if (response.conversation_id) {
          if (submittedTab === "interaction") {
            setInteractionConversationId(response.conversation_id);
          } else {
            setConversationId(response.conversation_id);
          }
        }
        if (submittedTab === "interaction") {
          setInteractionBusy(true);
        }
        if (response.lesson_design) {
          // 助教识别到整节课设计请求：直接打开全屏教案设计工作台并续上该会话。
          const designId = String((response.lesson_design as { design_id?: string }).design_id || "");
          openLessonDesignWorkspace(designId);
        }
        subscribeToJob(response.job_id);
        return true;
      } catch (error) {
        pushToast("error", "助教消息发送失败", error instanceof Error ? error.message : "请检查网络后重试，输入内容已保留。");
        return false;
      } finally {
        assistantSubmittingRef.current = false;
      }
    },
    [
      appendChat,
      buildMapContext,
      chatLog,
      conversationId,
      health?.ui.assistant_v2_enabled,
      interactionConversationId,
      openLessonDesignWorkspace,
      project,
      pushToast,
      subscribeToJob
    ]
  );

  assistantDispatchRef.current = (message, overrides, displayMessage) => {
    setCopilotOpenSignal((value) => value + 1);
    void submitAssistantText(message, overrides, "webgis", "text", undefined, displayMessage);
  };

  const handleTemplateRun = useCallback(
    async (templateId: string) => {
      if (!project) {
        return;
      }
      setDatabaseViewerOpen(true);
      setDatabaseCategory("resources");
      const response = await runTemplate(project.project_id, templateId);
      subscribeToJob(response.job_id);
    },
    [project, subscribeToJob]
  );

  const handleStartScreenshot = useCallback(async (): Promise<boolean> => {
    if (!project) {
      return false;
    }
    const imageDataUrl = viewMode === "globe" ? globeRef.current?.captureImage() || "" : mapRef.current ? await captureMapSnapshot(mapRef.current) : "";
    const rect = viewMode === "globe"
      ? globeRef.current?.getCanvasRect() || null
      : mapElementRef.current
        ? (() => {
            const value = mapElementRef.current!.getBoundingClientRect();
            return { left: value.left, top: value.top, width: value.width, height: value.height };
          })()
        : null;
    if (!imageDataUrl) {
      pushToast("error", "截图失败", "当前地图画面暂时无法读取，请稍后重试。");
      return false;
    }
    if (!rect || rect.width < 24 || rect.height < 24) {
      pushToast("error", "截图失败", "当前地图区域尺寸无效。");
      return false;
    }
    setScreenshotSource(imageDataUrl);
    setScreenshotBounds(rect);
    return true;
  }, [project, pushToast, viewMode]);

  const handleCompleteScreenshot = useCallback(async (selection: ScreenshotSelection) => {
    if (!project || !screenshotSource) return;
    try {
      const cropped = await cropSnapshot(screenshotSource, selection);
      const saved = await exportSnapshot(project.project_id, `地图截图 ${new Date().toLocaleString("zh-CN")}`, cropped, "地图区域框选截图");
      const evidence = pendingEvidenceSnapshotRef.current;
      let evidenceRecorded = true;
      if (evidence) {
        try {
          await logSessionEvent(evidence.sessionId, {
            event_type: "snapshot",
            stage_id: evidence.stageId,
            payload: { artifact_id: saved.artifact.artifact_id, title: saved.artifact.title }
          });
        } catch (error) {
          evidenceRecorded = false;
          pushToast("error", "课堂存证未记录", error instanceof Error ? error.message : "图片已保存，但课堂事件写入失败。请重试存证。");
        }
      }
      await refreshProjectState(project.project_id);
      setDatabaseViewerOpen(true);
      setDatabaseCategory("images");
      if (evidenceRecorded) {
        pushToast("success", "截图已保存", "可在图片库中预览，或加入智能助教进行识图问答。");
      }
    } catch (error) {
      pushToast("error", "截图失败", error instanceof Error ? error.message : "截图保存失败。");
    } finally {
      pendingEvidenceSnapshotRef.current = null;
      setScreenshotSource("");
      setScreenshotBounds(null);
    }
  }, [project, pushToast, refreshProjectState, screenshotSource]);

  const handleAttachImage = useCallback((image: ImageAttachment) => {
    setPendingImage((current) => {
      if (current && current.artifact_id !== image.artifact_id) {
        pushToast("info", "已替换待发送图片", image.title || "新图片已加入智能助教");
      }
      return image;
    });
    setCopilotOpenSignal((value) => value + 1);
  }, [pushToast]);

  const handleUploadImage = useCallback(async (file: File) => {
    if (!project) return;
    const supported = new Set(["image/jpeg", "image/png", "image/webp", "image/gif"]);
    if (!supported.has(file.type)) {
      pushToast("error", "图片格式不支持", "请选择 JPEG、PNG、WebP 或 GIF 图片。");
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      pushToast("error", "图片过大", "单张图片不能超过 20MB。");
      return;
    }
    try {
      const response = await uploadImageLibraryAsset(project.project_id, file, file.name.replace(/\.[^.]+$/, ""));
      await refreshProjectState(project.project_id);
      handleAttachImage({
        artifact_id: response.artifact.artifact_id,
        title: response.artifact.title,
        public_url: buildPublicFileUrl(String(response.artifact.metadata?.public_url || "")),
        mime_type: String(response.artifact.metadata?.mime_type || file.type)
      });
      pushToast("success", "图片已上传", "图片已保存到项目图片库，并加入智能助教。");
    } catch (error) {
      pushToast("error", "图片上传失败", error instanceof Error ? error.message : "上传请求失败。");
    }
  }, [handleAttachImage, project, pushToast, refreshProjectState]);

  const handleGenerateImage = useCallback(async ({
    prompt,
    model,
    aspectRatio
  }: { prompt: string; model: string; aspectRatio: string }) => {
    if (!project || imageGenerationLoading) return;
    setImageGenerationLoading(true);
    try {
      const response = await generateImageLibraryAsset(project.project_id, prompt, { model, aspectRatio });
      await refreshProjectState(project.project_id);
      handleAttachImage({
        artifact_id: response.artifact.artifact_id,
        title: response.artifact.title,
        public_url: buildPublicFileUrl(String(response.artifact.metadata?.public_url || "")),
        mime_type: String(response.artifact.metadata?.mime_type || "image/jpeg")
      });
      pushToast("success", "图片已生成", "已保存到项目图片库，并加入智能助教待发送附件。AI 示意图不替代权威 GIS 数据。");
    } catch (error) {
      pushToast("error", "图片生成失败", error instanceof Error ? error.message : "MiniMax 图片服务暂不可用。");
      throw error;
    } finally {
      setImageGenerationLoading(false);
    }
  }, [handleAttachImage, imageGenerationLoading, project, pushToast, refreshProjectState]);

  const handleRenderedPptImport = useCallback(async (file: File) => {
    setPptLoading(true);
    let renderError = "";
    try {
      const rendered = await renderPptx(file);
      const slides = rendered.slides.map((slide) => ({
        index: slide.index,
        html: "",
        imageUrl: slide.image_url,
        images: {},
        width: slide.width,
        height: slide.height,
        renderer: rendered.renderer
      }));
      setPptSlides((previousSlides) => {
        releaseSlideObjectUrls(previousSlides);
        return slides;
      });
      setPptFileName(rendered.file_name || file.name);
      setPptBrushHasContent(false);
      setPptViewerOpen(true);
      pushToast("success", "PPT 已导入", `已使用 ${rendered.renderer} 渲染 ${rendered.slides.length} 张幻灯片`);
    } catch (err) {
      renderError = err instanceof Error ? err.message : String(err);
      try {
        const result = await parsePptxFile(file);
        setPptSlides((previousSlides) => {
          releaseSlideObjectUrls(previousSlides);
          return result.slides;
        });
        setPptFileName(result.fileName);
        setPptBrushHasContent(false);
        setPptViewerOpen(true);
        pushToast("info", "PPT 已导入（简易模式）", "未找到可用的服务端渲染器，已使用前端解析兜底。复杂背景可能不完全一致。");
      } catch (fallbackErr) {
        const fallbackMessage = fallbackErr instanceof Error ? fallbackErr.message : String(fallbackErr);
        pushToast("error", "PPT 导入失败", `${fallbackMessage}${renderError ? `；渲染器错误：${renderError}` : ""}`);
      }
    } finally {
      setPptLoading(false);
    }
  }, [pushToast]);

  const handlePptCollapse = useCallback(() => {
    setPptViewerOpen(false);
  }, []);

  const handlePptRemove = useCallback(() => {
    setPptViewerOpen(false);
    setPptBrushHasContent(false);
    setPptFileName("");
    setPptSlides((previousSlides) => {
      releaseSlideObjectUrls(previousSlides);
      return [];
    });
  }, []);

  const handleUploadDataset = useCallback(
    async (formData: FormData) => {
      if (!project) {
        return;
      }
      const response = await uploadDataset(project.project_id, formData);
      subscribeToJob(response.job_id);
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
      setStatsCardOpen(false);
      setSearchCardOpen(true);
      await refreshProjectState(project.project_id);
      appendChat("system", response.summary);
      pushToast("success", `${resolvedMode === "polygon" ? "区域" : "视域"}检索完成`, response.summary);
    },
    [appendChat, onlinePoiEnabled, project, pushToast, refreshProjectState, searchAreaGeometry, searchKeyword]
  );

  const handleClearWorkspace = useCallback(async () => {
    searchAreaSourceRef.current?.clear();
    highlightSourceRef.current?.clear();
    measureSourceRef.current?.clear();
    annotationSourceRef.current?.clear();
    brushRef.current?.clear();
    pptBrushRef.current?.clear();
    setMapBrushHasContent(false);
    setPptBrushHasContent(false);
    lastPoiSignatureRef.current = "";
    setSearchAreaGeometry(null);
    setFocusedRegion(null);
    setSearchResults([]);
    setSearchSummary("");
    setOneMapStats(null);
    setSelectedFeatureText("");
    setMeasureText("");
    setMeasureTotalKm(null);
    setAnnotationCount(0);
    setMeasurementCount(0);
    setAnnotationDraft(null);
    setInteractionMode("browse");

    if (project && layerState?.items.some((item) => item.layer_id === "poi_search_results" && item.visible)) {
      await patchLayer(project.project_id, "poi_search_results", { visible: false });
      await refreshProjectState(project.project_id);
    }
    pushToast("info", "已清除当前操作", "标注、测距、检索区与高亮要素已重置。");
  }, [layerState?.items, project, pushToast, refreshProjectState]);

  const handleToggleTeachingMap = useCallback(async (mapId: string, visible: boolean) => {
    if (!project) {
      return;
    }
    // Missing-image maps would otherwise create a blank overlay.
    const mapInfo = teachingMaps.find((item) => item.id === mapId);
    if (visible && mapInfo?.available === false) {
      pushToast("error", "教学地图缺图", `“${mapInfo.name || mapId}”的图片文件未部署，无法叠加显示。`);
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
          programmaticViewGuardUntilRef.current = Date.now() + 2500;
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
  }, [project, pushToast, refreshProjectState, teachingMaps]);

  const handleToggleTextbookMap = useCallback(
    async (datasetId: string, visible: boolean) => {
      if (!project) {
        return;
      }
      const existing = layerState?.items.find(
        (item) =>
          item.source === "one_map_catalog" &&
          String(item.metadata?.catalog_id || item.layer_id.replace(/^one_map_/, "")) === datasetId
      );
      try {
        if (visible && !existing) {
          const response = await addCatalogDatasetLayer(project.project_id, datasetId);
          setViewMode("plane");
          pushToast("success", "专题图层已加载", response.layer.name || datasetId);
        } else if (existing) {
          await patchLayer(project.project_id, existing.layer_id, { visible });
        }
        await refreshProjectState(project.project_id);
      } catch (error) {
        pushToast("error", "专题图层切换失败", error instanceof Error ? error.message : "请求失败");
      }
    },
    [layerState?.items, project, pushToast, refreshProjectState]
  );

  const handleFocusLessonEvidenceLayer = useCallback(
    async (datasetId: string, stageDatasetIds: string[]) => {
      if (!project) {
        return;
      }
      const stageSet = new Set(stageDatasetIds);
      const existingLayers = (layerState?.items || []).filter((item) => {
        const catalogId = String(item.metadata?.catalog_id || item.layer_id.replace(/^one_map_/, ""));
        return item.source === "one_map_catalog" && stageSet.has(catalogId);
      });
      const targetExists = existingLayers.some((item) =>
        String(item.metadata?.catalog_id || item.layer_id.replace(/^one_map_/, "")) === datasetId
      );
      try {
        await Promise.all(
          existingLayers.map((item) => {
            const catalogId = String(item.metadata?.catalog_id || item.layer_id.replace(/^one_map_/, ""));
            return patchLayer(project.project_id, item.layer_id, { visible: catalogId === datasetId });
          })
        );
        if (!targetExists) {
          await addCatalogDatasetLayer(project.project_id, datasetId);
        }
        setViewMode("plane");
        await refreshProjectState(project.project_id);
        pushToast("success", "证据图层已聚焦", "已隐藏同环节其他专题图层，便于课堂逐图判读。");
      } catch (error) {
        pushToast("error", "证据图层切换失败", error instanceof Error ? error.message : "请求失败");
      }
    },
    [layerState?.items, project, pushToast, refreshProjectState]
  );

  const handleDatabaseOpenKnowledgeItem = useCallback((item: KnowledgeBaseItem) => {
    // 打开素材查看器预览该条目的全部资料；无资料时退化为提示。
    const materials = item.materials || [];
    if (materials.length) {
      setMaterialViewerTitle(item.title || item.id);
      setMaterialViewerItems(materials);
      setMaterialViewerOpen(true);
    } else {
      pushToast("info", item.title || "知识条目", item.summary || "该条目暂无可展示的资料");
    }
  }, [pushToast]);

  const handleDatabaseOpenMaterial = useCallback((title: string, materials: TeachingMaterial[]) => {
    setMaterialViewerTitle(title);
    setMaterialViewerItems(materials);
    setMaterialViewerOpen(true);
  }, []);

  // 图片/产物预览：包装为 image 素材复用 TeachingMaterialViewer（原生支持 image 渲染）。
  const openArtifactPreview = useCallback((artifact: ArtifactRecord) => {
    const publicUrl = typeof artifact.metadata?.public_url === "string" ? artifact.metadata.public_url : "";
    if (!publicUrl) {
      pushToast("error", "无法预览", artifact.title || artifact.artifact_id);
      return;
    }
    setMaterialViewerTitle(artifact.title || artifact.artifact_id);
    setMaterialViewerItems([
      {
        id: artifact.artifact_id,
        title: artifact.title || artifact.artifact_id,
        type: "image",
        source: "",
        url: publicUrl,
        thumbnail_url: publicUrl,
        description: String(artifact.metadata?.summary || ""),
        region_binding: {},
        sort_order: 0,
        created_at: artifact.created_at
      }
    ]);
    setMaterialViewerOpen(true);
  }, [pushToast]);

  const handleDatabaseToggleLayer = useCallback(async (layerId: string, visible: boolean) => {
    if (!project) {
      return;
    }
    try {
      await patchLayer(project.project_id, layerId, { visible });
      await refreshProjectState(project.project_id);
      pushToast("success", visible ? "图层已显示" : "图层已隐藏", layerId);
    } catch (error) {
      pushToast("error", "图层更新失败", error instanceof Error ? error.message : "图层状态更新失败");
    }
  }, [project, pushToast, refreshProjectState]);

  const handleDatabaseFocusLayer = useCallback(async (layerId: string) => {
    if (!project) {
      return;
    }
    try {
      await patchLayer(project.project_id, layerId, { active: true, visible: true });
      await refreshProjectState(project.project_id);
      setDatabaseViewerOpen(false);
      focusLayerExtent(layerId);
    } catch (error) {
      pushToast("error", "图层定位失败", error instanceof Error ? error.message : "图层状态更新失败");
    }
  }, [focusLayerExtent, project, pushToast, refreshProjectState]);

  const handleLayerManagerToggle = useCallback(async (layerId: string, visible: boolean) => {
    if (!project) {
      return;
    }
    try {
      await patchLayer(project.project_id, layerId, { visible });
      await refreshProjectState(project.project_id);
    } catch (error) {
      pushToast("error", "图层更新失败", error instanceof Error ? error.message : "图层状态更新失败");
    }
  }, [project, pushToast, refreshProjectState]);

  const handleLayerManagerFocus = useCallback(async (layerId: string) => {
    if (!project) {
      return;
    }
    try {
      await patchLayer(project.project_id, layerId, { active: true, visible: true });
      await refreshProjectState(project.project_id);
      focusLayerExtent(layerId);
    } catch (error) {
      pushToast("error", "图层定位失败", error instanceof Error ? error.message : "图层状态更新失败");
    }
  }, [focusLayerExtent, project, pushToast, refreshProjectState]);

  const handleLayerManagerDelete = useCallback(async (layerId: string) => {
    if (!project) {
      return;
    }
    try {
      await deleteLayer(project.project_id, layerId);
      await refreshProjectState(project.project_id);
      pushToast("success", "图层已删除", layerId);
    } catch (error) {
      pushToast("error", "图层删除失败", error instanceof Error ? error.message : "请求失败");
    }
  }, [project, pushToast, refreshProjectState]);

  const handleLayerManagerAddDataset = useCallback(async (item: DatasetCatalogItem) => {
    if (!project) {
      return;
    }
    try {
      const response = await addCatalogDatasetLayer(project.project_id, item.id);
      await refreshProjectState(project.project_id);
      setViewMode("plane");
      pushToast("success", "一张图数据已加载", response.layer.name || item.name || item.id);
    } catch (error) {
      pushToast("error", "一张图数据加载失败", error instanceof Error ? error.message : "请求失败");
    }
  }, [project, pushToast, refreshProjectState]);

  const handleDatabaseOpenArtifact = useCallback(
    (artifact: ArtifactRecord) => {
      if (["uploaded_image", "generated_image", "map_snapshot"].includes(artifact.artifact_type) || artifact.metadata?.kind === "png") {
        openArtifactPreview(artifact);
        return;
      }
      const publicUrl = typeof artifact.metadata?.public_url === "string" ? artifact.metadata.public_url : "";
      if (!publicUrl) {
        pushToast("error", "产物无法打开", artifact.title || artifact.artifact_id);
        return;
      }
      const url = /^https?:\/\//i.test(publicUrl)
        ? publicUrl
        : `${getApiBase()}${publicUrl.startsWith("/") ? publicUrl : `/${publicUrl}`}`;
      window.open(url, "_blank", "noopener,noreferrer");
    },
    [openArtifactPreview, pushToast]
  );

  const handleDatabaseDownloadArtifact = useCallback((artifact: ArtifactRecord) => {
    const publicUrl = typeof artifact.metadata?.public_url === "string" ? artifact.metadata.public_url : "";
    if (!publicUrl) {
      return;
    }
    const link = document.createElement("a");
    link.href = /^https?:\/\//i.test(publicUrl) ? publicUrl : `${getApiBase()}${publicUrl.startsWith("/") ? publicUrl : `/${publicUrl}`}`;
    link.download = artifact.title || artifact.artifact_id;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }, []);

  const handleDatabaseDeleteArtifact = useCallback(
    async (artifact: ArtifactRecord) => {
      if (!project) {
        return;
      }
      if (!window.confirm(`确定从数据库移除“${artifact.title || artifact.artifact_id}”吗？（文件保留在服务器磁盘）`)) {
        return;
      }
      try {
        await deleteOutput(artifact.artifact_id, project.project_id);
        await refreshProjectState(project.project_id);
        pushToast("success", "产物已移除", artifact.title || artifact.artifact_id);
      } catch (error) {
        pushToast("error", "产物删除失败", error instanceof Error ? error.message : "请求失败");
      }
    },
    [project, pushToast, refreshProjectState]
  );

  const handleDatabaseLoadArtifactLayer = useCallback(
    async (artifact: ArtifactRecord) => {
      if (!project) {
        return;
      }
      try {
        const response = await loadOutputAsLayer(artifact.artifact_id, project.project_id);
        await refreshProjectState(project.project_id);
        setDatabaseViewerOpen(false);
        const layer = response.item as { name?: string } | undefined;
        pushToast("success", "产物已上图", layer?.name || artifact.title || artifact.artifact_id);
      } catch (error) {
        pushToast("error", "产物上图失败", error instanceof Error ? error.message : "请求失败");
      }
    },
    [project, pushToast, refreshProjectState]
  );

  const handleDatabaseAttachImage = useCallback(
    (artifact: ArtifactRecord) => {
      const publicUrl = typeof artifact.metadata?.public_url === "string" ? artifact.metadata.public_url : "";
      if (!publicUrl) {
        pushToast("error", "图片无法附加", artifact.title || artifact.artifact_id);
        return;
      }
      handleAttachImage({
        artifact_id: artifact.artifact_id,
        title: artifact.title || artifact.artifact_id,
        public_url: publicUrl,
      });
      setDatabaseViewerOpen(false);
    },
    [handleAttachImage, pushToast]
  );

  const handleDatabaseDeleteQuestionBank = useCallback(
    async (bank: QuestionBankSummary) => {
      if (!project) {
        return;
      }
      if (!window.confirm(`确定删除题库“${bank.title || bank.base_name}”（${bank.question_count} 题）吗？该操作不可恢复。`)) {
        return;
      }
      try {
        await deleteQuestionBank(bank.bank_id);
        const refreshed = await fetchQuestionBanks(project.project_id);
        setQuestionBanks(refreshed.items || []);
        pushToast("success", "题库已删除", bank.title || bank.base_name);
      } catch (error) {
        pushToast("error", "题库删除失败", error instanceof Error ? error.message : "请求失败");
      }
    },
    [project, pushToast]
  );

  // 与 handleLayerManagerAddDataset 相同的建层流程：保留单一实现，两个入口共用。
  const handleDatabaseLoadDataset = handleLayerManagerAddDataset;

  const handleDatabaseUseDataset = useCallback((item: DatasetCatalogItem) => {
    if (!item.source) {
      pushToast("error", "数据集无法制图", item.name || item.id);
      return;
    }
    setWorkflowInitialDataset(item.source);
    setWorkflowDockOpen(true);
    setDatabaseViewerOpen(false);
    pushToast("info", "已选择一张图数据", item.name || item.id);
  }, [pushToast]);

  const handleOneMapStats = useCallback(async () => {
    if (!project) {
      return;
    }
    if (!searchAreaGeometry) {
      pushToast("error", "尚未框选区域", "先点击右侧“绘区”，在地图上画出统计区域。");
      return;
    }
    if (!hasVisibleOneMapLayer) {
      pushToast("error", "没有可统计图层", "先在数据库的一张图数据中加载人口图层或可关联 CSV 到底图。");
      return;
    }
    try {
      const response = await summarizeCatalogLayers(project.project_id, searchAreaGeometry);
      setOneMapStats(response);
      setSearchCardOpen(false);
      setStatsCardOpen(true);
      pushToast("success", "区域统计完成", response.summary);
    } catch (error) {
      pushToast("error", "区域统计失败", error instanceof Error ? error.message : "请求失败");
    }
  }, [hasVisibleOneMapLayer, project, pushToast, searchAreaGeometry]);

  const handleDatabaseActivateLessonSet = useCallback(async (setId: string) => {
    if (!project) {
      return;
    }
    try {
      const response = await activateLessonResourceSet(project.project_id, setId, { active: true });
      setLessonResourceSets(response.items);
      setActiveLessonResourceSetId(response.active_lesson_resource_set_id || setId);
      pushToast("success", "课时资源已启用", setId);
    } catch (error) {
      pushToast("error", "课时资源切换失败", error instanceof Error ? error.message : "请求失败");
    }
  }, [project, pushToast]);

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

  // ── 3D globe ↔ 2D plane transition helpers ──────────────────────────
  //
  // The two views share a center coordinate; we approximate the camera
  // altitude ↔ OL zoom mapping via altitudeToZoom / zoomToAltitude. Three
  // independent triggers can flip the view: header toggle, automatic
  // zoom-threshold, and the globe's double-click "dive" gesture.

  /** Pick the first 3D-compatible XYZ layer from the active basemap. */
  const globeImageryUrl = useMemo(() => {
    const layers = layerState?.base_map.layers || [];
    const candidate = layers.find(
      (layer) => layer.kind === "xyz" && layer.usable_in_3d !== false && layer.urls.length
    );
    if (candidate) {
      return candidate.urls[0];
    }
    // Sane fallback when no project / basemap yet
    return "https://webrd01.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=7&x={x}&y={y}&z={z}";
  }, [layerState?.base_map]);

  const transitionToPlane = useCallback(
    (opts: { lon: number; lat: number; zoom?: number; reason: "manual" | "altitude" | "dblclick" }) => {
      if (viewMode === "plane") {
        return;
      }
      const map = mapRef.current;
      const targetZoom = opts.zoom ?? altitudeToZoom(DOUBLE_CLICK_LANDING_ALTITUDE);
      planeAutoArmedRef.current = false;
      setViewMode("plane");
      // Defer the OL view sync to the next tick so the canvas is visible.
      window.setTimeout(() => {
        const view = mapRef.current?.getView() || map?.getView();
        if (view) {
          view.animate({
            center: fromLonLat([opts.lon, opts.lat]),
            zoom: Math.max(targetZoom, 4),
            duration: opts.reason === "manual" ? 250 : 700,
            easing: easeOut
          });
        }
      }, 30);
      if (opts.reason !== "manual") {
        pushToast(
          "info",
          opts.reason === "dblclick" ? "已落入平面地图" : "已切换到平面地图",
          "继续缩小可返回 3D 数字地球。"
        );
      }
      // Re-arm the plane→globe trigger after a short cooldown so we don't
      // bounce back and forth at the threshold.
      window.setTimeout(() => {
        planeAutoArmedRef.current = true;
      }, 1500);
    },
    [pushToast, viewMode]
  );

  const transitionToGlobe = useCallback(
    (opts: { lon?: number; lat?: number; zoom?: number; reason: "manual" | "zoom" }) => {
      if (viewMode === "globe") {
        return;
      }
      const map = mapRef.current;
      let lon = opts.lon;
      let lat = opts.lat;
      let z = opts.zoom;
      if ((lon === undefined || lat === undefined) && map) {
        const center = map.getView().getCenter();
        if (center) {
          const ll = toLonLat(center) as [number, number];
          lon = ll[0];
          lat = ll[1];
        }
      }
      if (z === undefined && map) {
        z = map.getView().getZoom() ?? 4;
      }
      const altitude = zoomToAltitude(typeof z === "number" ? z : 3);
      setViewMode("globe");
      window.setTimeout(() => {
        globeRef.current?.flyTo(lon ?? 104, lat ?? 35, Math.max(altitude, 1_000_000), 1.0);
      }, 30);
      if (opts.reason !== "manual") {
        pushToast("info", "已切换到 3D 数字地球", "拖拽旋转，滚轮缩放或双击地球进入 2D。");
      }
    },
    [pushToast, viewMode]
  );

  // 智能交互 ui_action 的切换句柄：handleAssistantUiActions 定义在两个
  // transition 之前，通过 ref 桥接避免声明顺序问题。
  transitionToPlaneRef.current = transitionToPlane;
  transitionToGlobeRef.current = transitionToGlobe;

  const handleViewModeToggle = useCallback(
    (next: ViewMode) => {
      lessonGlobePinnedRef.current = false;
      lessonGlobeRestoreRef.current = null;
      if (next === "plane") {
        const cam = globeCamera;
        transitionToPlane({
          lon: cam?.lon ?? 104,
          lat: cam?.lat ?? 35,
          zoom: cam ? altitudeToZoom(cam.altitudeMeters) : 4,
          reason: "manual"
        });
      } else {
        transitionToGlobe({ reason: "manual" });
      }
    },
    [globeCamera, transitionToGlobe, transitionToPlane]
  );

  const handleGlobeDoubleClick = useCallback(
    (lon: number, lat: number) => {
      lessonGlobePinnedRef.current = false;
      lessonGlobeRestoreRef.current = null;
      transitionToPlane({ lon, lat, zoom: altitudeToZoom(DOUBLE_CLICK_LANDING_ALTITUDE), reason: "dblclick" });
    },
    [transitionToPlane]
  );

  const handleGlobeAltitudeThreshold = useCallback(
    (state: CameraState) => {
      if (lessonGlobePinnedRef.current) {
        return;
      }
      transitionToPlane({
        lon: state.lon,
        lat: state.lat,
        zoom: altitudeToZoom(state.altitudeMeters),
        reason: "altitude"
      });
    },
    [transitionToPlane]
  );

  const handleApplyLessonGlobeScene = useCallback(
    (globe: LessonGlobeScene) => {
      const decision = decideLessonGlobeScene(
        globe,
        lessonGlobePinnedRef.current,
        Boolean(lessonGlobeRestoreRef.current)
      );
      if (decision.kind === "apply-globe") {
        if (decision.rememberCurrent) {
          lessonGlobeRestoreRef.current = {
            viewMode,
            themeIds: [...globeThemeIds],
            camera: globeCamera ? { ...globeCamera } : null,
            plane: planeViewState ? { ...planeViewState } : null
          };
        }
        lessonGlobePinnedRef.current = true;
        setGlobeThemeIds([...(decision.globe.themes || [])]);
        setViewMode("globe");
        const camera = decision.globe.camera;
        if (camera) {
          window.setTimeout(() => {
            globeRef.current?.flyTo(
              camera.lon ?? 104,
              camera.lat ?? 35,
              camera.altitudeMeters ?? 12_000_000,
              1.0,
              camera.pitchDeg ?? -90
            );
          }, 30);
        }
        return;
      }

      if (decision.kind === "apply-plane") {
        lessonGlobePinnedRef.current = false;
        lessonGlobeRestoreRef.current = null;
        setGlobeThemeIds([]);
        // The scene refresh supplies its own center/zoom. A delayed camera
        // transition would overwrite Shanghai with the previous globe center.
        mapRef.current?.getView().cancelAnimations();
        lastAppliedViewRef.current = "";
        setViewMode("plane");
        return;
      }

      if (decision.kind === "none") {
        return;
      }
      const restore = lessonGlobeRestoreRef.current;
      if (!restore) return;
      lessonGlobePinnedRef.current = false;
      lessonGlobeRestoreRef.current = null;
      setGlobeThemeIds(restore.themeIds);
      if (restore.viewMode === "plane") {
        transitionToPlane({
          lon: restore.plane?.lon ?? 104,
          lat: restore.plane?.lat ?? 35,
          zoom: restore.plane?.zoom ?? 4,
          reason: "manual"
        });
      } else {
        setViewMode("globe");
        if (restore.camera) {
          window.setTimeout(() => {
            globeRef.current?.flyTo(
              restore.camera!.lon,
              restore.camera!.lat,
              restore.camera!.altitudeMeters,
              0.8,
              restore.camera!.pitchDeg
            );
          }, 30);
        }
      }
    },
    [globeCamera, globeThemeIds, planeViewState, transitionToPlane, viewMode]
  );

  const getLessonGlobeSceneSnapshot = useCallback((): LessonGlobeScene => {
    if (viewMode !== "globe") {
      return { enabled: false };
    }
    const camera = globeRef.current?.getCameraState() || globeCamera;
    return {
      enabled: true,
      themes: [...globeThemeIds],
      camera: camera
        ? {
            lon: camera.lon,
            lat: camera.lat,
            altitudeMeters: camera.altitudeMeters,
            pitchDeg: camera.pitchDeg
          }
        : undefined
    };
  }, [globeCamera, globeThemeIds, viewMode]);

  // Toggle the OL graticule layer in sync with `showGraticule`. The layer
  // is created during map init; we just flip its visibility here.
  useEffect(() => {
    graticuleLayerRef.current?.setVisible(showGraticule);
  }, [showGraticule]);

  useEffect(() => {
    if (!searchDropdownOpen) return undefined;
    const close = () => setSearchDropdownOpen(false);
    document.addEventListener("click", close, { once: true });
    return () => document.removeEventListener("click", close);
  }, [searchDropdownOpen]);

  // Auto plane → globe: watch the OL view's resolution and pop back to 3D
  // when the user zooms far enough out. Also mirror view state into
  // `planeViewState` so the bottom status bar updates live.
  useEffect(() => {
    if (viewMode !== "plane") {
      return undefined;
    }
    const map = mapRef.current;
    if (!map) {
      return undefined;
    }
    const view = map.getView();
    const sync = () => {
      const center = view.getCenter();
      const zoom = view.getZoom();
      if (center && typeof zoom === "number") {
        const ll = toLonLat(center) as [number, number];
        setPlaneViewState({ lon: ll[0], lat: ll[1], zoom });
      }
    };
    const checkThreshold = () => {
      if (!planeAutoArmedRef.current) {
        return;
      }
      if (Date.now() < programmaticViewGuardUntilRef.current) {
        return;
      }
      const zoom = view.getZoom();
      if (typeof zoom === "number" && zoom < PLANE_TO_GLOBE_ZOOM_THRESHOLD) {
        planeAutoArmedRef.current = false;
        const center = view.getCenter();
        const ll = center ? (toLonLat(center) as [number, number]) : [104, 35];
        transitionToGlobe({ lon: ll[0], lat: ll[1], zoom, reason: "zoom" });
        window.setTimeout(() => {
          planeAutoArmedRef.current = true;
        }, 1500);
      }
    };
    sync();
    view.on("change:center", sync);
    view.on("change:resolution", sync);
    view.on("change:resolution", checkThreshold);
    return () => {
      view.un("change:center", sync);
      view.un("change:resolution", sync);
      view.un("change:resolution", checkThreshold);
    };
  }, [transitionToGlobe, viewMode]);

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
        fill: new Fill({ color: "rgba(88, 199, 255, 0.12)" }),
        stroke: new Stroke({ color: "#58c7ff", width: 2, lineDash: [8, 6] })
      })
    });

    const highlightSource = new VectorSource();
    const highlightLayer = new VectorLayer({
      source: highlightSource,
      zIndex: 170,
      style: (feature) => {
        const geometryType = feature.getGeometry()?.getType() || "";
        const selectedLabel = String(feature.get("__selectedLabel") || feature.get("name") || "");
        return new Style({
          fill: geometryType.includes("Polygon") ? new Fill({ color: "rgba(56, 189, 248, 0.2)" }) : undefined,
          stroke: new Stroke({ color: "#67e8f9", width: 3.2 }),
          image: geometryType.includes("Point")
            ? new CircleStyle({
                radius: 10,
                fill: new Fill({ color: "rgba(56, 189, 248, 0.45)" }),
                stroke: new Stroke({ color: "#ecfeff", width: 2.2 })
              })
            : undefined,
          text: selectedLabel
            ? new Text({
                text: selectedLabel,
                font: "700 15px 'Microsoft YaHei UI', 'Segoe UI', sans-serif",
                fill: new Fill({ color: "#ffffff" }),
                backgroundFill: new Fill({ color: "rgba(7, 28, 48, 0.88)" }),
                backgroundStroke: new Stroke({ color: "rgba(103, 232, 249, 0.72)", width: 1.2 }),
                padding: [5, 8, 5, 8],
                overflow: true
              })
            : undefined
        });
      }
    });

    const measureSource = new VectorSource();
    const measureLayer = new VectorLayer({
      source: measureSource,
      zIndex: 180,
      style: (feature) => {
        const geometry = feature.getGeometry();
        const styles: Style[] = [];
        if (!geometry || !(geometry instanceof LineString)) {
          return styles;
        }
        const lengthMeters = getLength(geometry);
        const lengthKm = lengthMeters / 1000;
        styles.push(
          new Style({
            stroke: new Stroke({
              color: "rgba(255, 235, 120, 0.95)",
              width: 3,
              lineDash: [10, 6]
            })
          })
        );
        // Vertex markers
        geometry.getCoordinates().forEach((coord) => {
          styles.push(
            new Style({
              geometry: new Point(coord),
              image: new CircleStyle({
                radius: 4.5,
                fill: new Fill({ color: "#fde047" }),
                stroke: new Stroke({ color: "#1c1410", width: 1.5 })
              })
            })
          );
        });
        // Total label at the end
        const last = geometry.getLastCoordinate();
        styles.push(
          new Style({
            geometry: new Point(last),
            text: new Text({
              text:
                lengthKm >= 1
                  ? `${lengthKm.toFixed(2)} km`
                  : `${lengthMeters.toFixed(0)} m`,
              font: "600 12px 'Inter', 'Noto Sans SC', sans-serif",
              fill: new Fill({ color: "#fffbeb" }),
              backgroundFill: new Fill({ color: "rgba(28, 20, 16, 0.82)" }),
              backgroundStroke: new Stroke({ color: "rgba(253, 224, 71, 0.6)", width: 1 }),
              padding: [3, 6, 3, 6],
              offsetX: 14,
              offsetY: -14,
              textAlign: "left"
            })
          })
        );
        return styles;
      }
    });

    const annotationSource = new VectorSource();
    const annotationLayer = new VectorLayer({
      source: annotationSource,
      zIndex: 190,
      style: (feature) => {
        const text = String(feature.get("text") || "");
        return [
          // Pin shadow + accent shape
          new Style({
            image: new RegularShape({
              points: 3,
              radius: 11,
              rotation: Math.PI,
              fill: new Fill({ color: "rgba(88, 199, 255, 0.95)" }),
              stroke: new Stroke({ color: "rgba(8, 24, 44, 0.9)", width: 1.4 }),
              displacement: [0, 10]
            })
          }),
          new Style({
            image: new CircleStyle({
              radius: 9,
              fill: new Fill({ color: "#58c7ff" }),
              stroke: new Stroke({ color: "#f1f7ff", width: 2 }),
              displacement: [0, 4]
            })
          }),
          new Style({
            image: new CircleStyle({
              radius: 3.5,
              fill: new Fill({ color: "#06182c" }),
              displacement: [0, 4]
            })
          }),
          ...(text
            ? [
                new Style({
                  text: new Text({
                    text,
                    font: "600 12.5px 'Inter', 'Noto Sans SC', sans-serif",
                    fill: new Fill({ color: "#f1f7ff" }),
                    backgroundFill: new Fill({ color: "rgba(8, 24, 44, 0.86)" }),
                    backgroundStroke: new Stroke({ color: "rgba(140, 222, 255, 0.42)", width: 1 }),
                    padding: [5, 8, 5, 8],
                    offsetX: 16,
                    offsetY: -16,
                    textAlign: "left",
                    overflow: true
                  })
                })
              ]
            : [])
        ];
      }
    });

    // Lat/lon graticule (toggled separately via showGraticule state).
    // We register the layer here so it composes naturally with the others
    // and inherits the map view; visibility is the only thing the toggle
    // flips at runtime.
    const graticuleLayer = new Graticule({
      strokeStyle: new Stroke({
        color: "rgba(140, 222, 255, 0.42)",
        width: 1,
        lineDash: [2, 4]
      }),
      showLabels: true,
      lonLabelStyle: new Text({
        font: "11px 'Inter', 'Noto Sans SC', sans-serif",
        textBaseline: "bottom",
        fill: new Fill({ color: "#ecf6ff" }),
        stroke: new Stroke({ color: "rgba(8, 24, 44, 0.92)", width: 3 })
      }),
      latLabelStyle: new Text({
        font: "11px 'Inter', 'Noto Sans SC', sans-serif",
        textAlign: "end",
        fill: new Fill({ color: "#ecf6ff" }),
        stroke: new Stroke({ color: "rgba(8, 24, 44, 0.92)", width: 3 })
      }),
      visible: false,
      zIndex: 250
    });
    graticuleLayerRef.current = graticuleLayer;

    const map = new Map({
      target: mapElementRef.current,
      layers: [searchAreaLayer, highlightLayer, measureLayer, annotationLayer, graticuleLayer],
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
        // Open the in-app annotation dialog with the clicked location.
        // The dialog handler will commit the annotation and reset the mode.
        setAnnotationDraft({ lonLat });
        return;
      }

      if (mode === "measure" || mode === "draw-search") {
        // These modes are owned by the OL Draw interaction; ignore singleclick here.
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
            highlighted.set("__selectedLabel", regionLabel(properties), true);
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
    measureSourceRef.current = measureSource;
    annotationSourceRef.current = annotationSource;
    mapRef.current = map;
    map.on("singleclick", handleClick);

    return () => {
      if (drawInteractionRef.current) {
        map.removeInteraction(drawInteractionRef.current);
        drawInteractionRef.current = null;
      }
      if (measureDrawRef.current) {
        map.removeInteraction(measureDrawRef.current);
        measureDrawRef.current = null;
      }
      window.clearTimeout(delayedResize);
      resizeObserver.disconnect();
      map.un("singleclick", handleClick);
      map.setTarget(undefined);
      basemapLayersRef.current = [];
        businessLayerCacheRef.current.clear();
        vectorLayerByIdRef.current.clear();
      searchAreaSourceRef.current = null;
      highlightSourceRef.current = null;
      measureSourceRef.current = null;
      annotationSourceRef.current = null;
      graticuleLayerRef.current = null;
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
      // 优先复用上次的课堂项目：每次刷新都新建项目会让后端状态文件无限膨胀
      //（历史上曾涨到 228MB，导致整个课堂演示卡顿）。
      const storedProjectId = readStoredProjectId(currentUser.user_id);
      let active: (ProjectRecord & { status: string }) | null = null;
      if (storedProjectId) {
        try {
          active = await fetchProject(storedProjectId);
        } catch (error) {
          if ((error as Error).message === "AUTH_REQUIRED") {
            throw error;
          }
          active = null;
        }
      }
      if (cancelled) {
        return;
      }
      const restored = Boolean(active);
      if (!active) {
        active = await createProject();
        storeProjectId(currentUser.user_id, active.project_id);
      }
      if (cancelled) {
        return;
      }
      setProject(active);
      await refreshProjectState(active.project_id);
      await loadKnowledgeBase();
      try {
        const catalog = await fetchDatasetCatalog();
        if (!cancelled) {
          setDatasetCatalogItems(catalog.items || []);
          setDatasetCatalogError(false);
        }
      } catch {
        if (!cancelled) {
          setDatasetCatalogItems([]);
          setDatasetCatalogError(true);
        }
      }
      // Load teaching maps catalog
      try {
        const tmaps = await fetchTeachingMaps();
        if (!cancelled) {
          setTeachingMaps(tmaps.items);
        }
        const activeOverlays = await fetchActiveTeachingMaps(active.project_id);
        if (!cancelled) {
          setActiveTeachingMapIds(new Set(activeOverlays.active));
        }
      } catch {
        // teaching maps are optional – do not block init
      }
      // 题库列表：数据库面板「题库」分类的数据源（导入/删除后在此刷新）。
      try {
        const banks = await fetchQuestionBanks(active.project_id);
        if (!cancelled) {
          setQuestionBanks(banks.items || []);
        }
      } catch {
        if (!cancelled) {
          setQuestionBanks([]);
        }
      }
      if (cancelled) return;
      if (restored) {
        pushToast("success", "课堂项目已恢复", "已加载上次的课堂地图环境。");
      } else {
        pushToast("success", "课堂项目已创建", "已初始化课堂地图环境。");
      }
    })().catch((error: Error) => {
      setInitError(error.message);
      pushToast("error", "初始化失败", error.message);
    });

    return () => {
      cancelled = true;
    };
  }, [currentUser.user_id, initAttempt, loadKnowledgeBase, pushToast, refreshProjectState]);

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
          maxZoom: descriptor.max_zoom ?? 18,
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
    const cache = businessLayerCacheRef.current;
    const seen = new Set<string>();
    // Province symbols use an interior point of the largest land polygon, not a capital or an offshore centroid.
    const provinceAnchors = new globalThis.Map<string,number[]>();
    const regions = layerState.items.find(item=>item.layer_id === "builtin_population_regions");
    if(regions) format.readFeatures(regions.data,{dataProjection:"EPSG:4326",featureProjection:"EPSG:3857"}).forEach(feature=>{
      const geometry=feature.getGeometry();
      const polygon=geometry instanceof MultiPolygon ? geometry.getPolygons().sort((a,b)=>b.getArea()-a.getArea())[0] : geometry instanceof Polygon ? geometry : null;
      if(polygon) { const coordinate=polygon.getInteriorPoint().getCoordinates().slice(0,2); for(const key of ["name","short_name"]) if(feature.get(key)) provinceAnchors.set(String(feature.get(key)),coordinate); }
    });

    layerState.items.forEach((record) => {
      const isRaster = record.kind === "raster";
      const assetUrl = String(record.metadata.asset_url || "");
      const bounds = record.metadata.bounds as [number, number, number, number] | undefined;
      if (isRaster && (!assetUrl || !bounds)) {
        return;
      }
      seen.add(record.layer_id);
      const signature = isRaster
        ? `raster|${assetUrl}|${JSON.stringify(bounds)}`
        : `vector|${record.data_rev ?? 0}|${record.layer_id === "builtin_population_density" ? regions?.data_rev ?? "none" : ""}`;
      const styleKey = JSON.stringify([record.style || {}, showTeachingFit]);

      let entry = cache.get(record.layer_id);
      if (entry && entry.signature !== signature) {
        map.removeLayer(entry.olLayer);
        vectorLayerByIdRef.current.delete(record.layer_id);
        cache.delete(record.layer_id);
        entry = undefined;
      }

      if (!entry) {
        let olLayer: RenderableLayer;
        if (isRaster) {
          olLayer = new ImageLayer({
            source: new ImageStatic({
              url: `${getApiBase()}${assetUrl}`,
              imageExtent: transformExtent(bounds as [number, number, number, number], "EPSG:4326", "EPSG:3857")
            }),
            opacity: record.opacity,
            visible: record.visible,
            zIndex: record.z_index
          });
        } else {
          const features = format.readFeatures(record.data, {
            dataProjection: "EPSG:4326",
            featureProjection: "EPSG:3857"
          });
          if(record.layer_id === "builtin_population_density") features.forEach(feature=>{
            const anchor=provinceAnchors.get(String(feature.get("name")));
            if(anchor) feature.setGeometry(new Point(anchor));
          });
          const vectorLayer = new VectorLayer({
            source: new VectorSource({ features }),
            visible: record.visible,
            opacity: record.opacity,
            zIndex: record.z_index,
            // 标注抽稀：重叠的要素标签自动隐藏，省级/世界尺度不再一片叠字。
            declutter: true,
            style: layerStyle(record, showTeachingFit)
          });
          vectorLayerByIdRef.current.set(record.layer_id, vectorLayer);
          olLayer = vectorLayer;
        }
        cache.set(record.layer_id, { signature, styleKey, olLayer });
        map.addLayer(olLayer);
        return;
      }

      const olLayer = entry.olLayer;
      olLayer.setVisible(record.visible);
      olLayer.setOpacity(record.opacity);
      olLayer.setZIndex(record.z_index);
      if (!isRaster && entry.styleKey !== styleKey) {
        (olLayer as VectorLayer<any>).setStyle(layerStyle(record, showTeachingFit));
        entry.styleKey = styleKey;
      }
    });

    cache.forEach((entry, layerId) => {
      if (!seen.has(layerId)) {
        map.removeLayer(entry.olLayer);
        vectorLayerByIdRef.current.delete(layerId);
        cache.delete(layerId);
      }
    });

    const serverViewSignature = JSON.stringify(layerState.view || {});
    if (serverViewSignature !== lastAppliedViewRef.current) {
      const targetCenter = fromLonLat(layerState.view.center || [104, 35]);
      const targetZoom = layerState.view.zoom || 4;
      // Server-driven fit (e.g. a just-loaded world-extent layer may land at
      // zoom < 3) must not trigger the plane→globe auto switch.
      programmaticViewGuardUntilRef.current = Date.now() + 3000;
      map.getView().animate(
        { center: targetCenter, zoom: targetZoom, duration: 1200, easing: easeOut },
      );
      lastAppliedViewRef.current = serverViewSignature;
    }

    window.requestAnimationFrame(() => {
      map.updateSize();
      map.renderSync();
    });
  }, [layerState, showTeachingFit]);

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
      type: "Polygon",
      style: new Style({
        fill: new Fill({ color: "rgba(88, 199, 255, 0.16)" }),
        stroke: new Stroke({ color: "#58c7ff", width: 2, lineDash: [6, 5] }),
        image: new CircleStyle({
          radius: 5,
          fill: new Fill({ color: "#58c7ff" }),
          stroke: new Stroke({ color: "#f1f7ff", width: 1.5 })
        })
      })
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

  // Measurement mode — interactive multi-segment polyline with running total.
  useEffect(() => {
    if (!mapRef.current || !measureSourceRef.current) {
      return;
    }
    const map = mapRef.current;
    const existing = measureDrawRef.current;
    if (existing) {
      map.removeInteraction(existing);
      measureDrawRef.current = null;
    }
    if (interactionMode !== "measure") {
      setMeasureTotalKm(null);
      return;
    }

    const draw = new Draw({
      source: measureSourceRef.current,
      type: "LineString",
      style: new Style({
        stroke: new Stroke({
          color: "rgba(253, 224, 71, 0.95)",
          width: 2.6,
          lineDash: [8, 5]
        }),
        image: new CircleStyle({
          radius: 5,
          fill: new Fill({ color: "#fde047" }),
          stroke: new Stroke({ color: "#1c1410", width: 1.4 })
        })
      })
    });

    let liveListenerKey: ReturnType<typeof draw.getOverlay>["on"] extends (...args: infer A) => infer R ? R : null = null as any;

    draw.on("drawstart", (event) => {
      measureSourceRef.current?.clear();
      setMeasureText("绘制中…双击结束当前测线，按 Esc 取消。");
      setMeasureTotalKm(0);
      const geometry = event.feature.getGeometry();
      if (geometry) {
        liveListenerKey = geometry.on("change", () => {
          const lengthMeters = getLength(geometry);
          setMeasureTotalKm(lengthMeters / 1000);
        }) as any;
      }
    });

    draw.on("drawend", (event) => {
      const geometry = event.feature.getGeometry();
      if (liveListenerKey) {
        unByKey(liveListenerKey as any);
        liveListenerKey = null as any;
      }
      if (!geometry) {
        setInteractionMode("browse");
        return;
      }
      const lengthMeters = getLength(geometry);
      const lengthKm = lengthMeters / 1000;
      const pretty =
        lengthKm >= 1 ? `${lengthKm.toFixed(2)} 千米` : `${lengthMeters.toFixed(0)} 米`;
      setMeasureText(`测量完成：${pretty}`);
      setMeasureTotalKm(lengthKm);
      setMeasurementCount((value) => value + 1);
      pushToast("success", "测距完成", `本段共 ${pretty}`);
      setInteractionMode("browse");
    });

    measureDrawRef.current = draw;
    map.addInteraction(draw);

    return () => {
      if (liveListenerKey) {
        unByKey(liveListenerKey as any);
      }
      if (measureDrawRef.current) {
        map.removeInteraction(measureDrawRef.current);
        measureDrawRef.current = null;
      }
    };
  }, [interactionMode, pushToast]);

  // Esc cancels any active interaction; B/A/M/D switch modes when no input is focused.
  useEffect(() => {
    const isTextInputTarget = (target: EventTarget | null): boolean => {
      if (!(target instanceof HTMLElement)) {
        return false;
      }
      if (target.isContentEditable) {
        return true;
      }
      const tag = target.tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
    };

    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (annotationDraft) {
          setAnnotationDraft(null);
          setInteractionMode("browse");
          return;
        }
        if (interactionModeRef.current !== "browse") {
          setInteractionMode("browse");
          setMeasureText("");
          setMeasureTotalKm(null);
        }
        return;
      }

      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      if (isTextInputTarget(event.target)) {
        return;
      }

      const lower = event.key.toLowerCase();
      const shortcuts: Record<string, InteractionMode> = {
        b: "browse",
        a: "annotate",
        m: "measure",
        d: "draw-search",
        p: "brush"
      };
      const next = shortcuts[lower];
      if (next) {
        event.preventDefault();
        setInteractionMode(next);
      }
    };

    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [annotationDraft]);

  const handleBrushWheelZoom = useCallback(
    (event: WheelEvent) => {
      if (viewMode !== "plane") {
        return;
      }
      const map = mapRef.current;
      if (!map) {
        return;
      }

      const viewportRect = map.getViewport().getBoundingClientRect();
      if (
        event.clientX < viewportRect.left ||
        event.clientX > viewportRect.right ||
        event.clientY < viewportRect.top ||
        event.clientY > viewportRect.bottom
      ) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();

      let normalizedDelta = event.deltaY;
      if (event.deltaMode === 1) {
        normalizedDelta *= 16;
      } else if (event.deltaMode === 2) {
        normalizedDelta *= viewportRect.height || window.innerHeight;
      }
      if (!Number.isFinite(normalizedDelta) || normalizedDelta === 0) {
        return;
      }

      const zoomDelta = Math.max(-0.75, Math.min(0.75, -normalizedDelta / 360));
      if (Math.abs(zoomDelta) < 0.01) {
        return;
      }

      const anchor = map.getCoordinateFromPixel([
        event.clientX - viewportRect.left,
        event.clientY - viewportRect.top
      ]);
      map.getView().adjustZoom(zoomDelta, anchor);
      map.render();
    },
    [viewMode]
  );

  // Commit a saved annotation when the dialog is submitted.
  const commitAnnotation = useCallback(
    (text: string) => {
      const draft = annotationDraft;
      if (!draft || !text.trim() || !annotationSourceRef.current) {
        setAnnotationDraft(null);
        setInteractionMode("browse");
        return;
      }
      const trimmed = text.trim();
      const feature = new Feature({
        geometry: new Point(fromLonLat(draft.lonLat))
      });
      feature.set("text", trimmed);
      feature.set("created_at", new Date().toISOString());
      annotationSourceRef.current.addFeature(feature);
      setAnnotationCount(annotationSourceRef.current.getFeatures().length);
      setAnnotationDraft(null);
      setInteractionMode("browse");

      const map = mapRef.current;
      assistantDispatchRef.current(`在当前位置标注：${trimmed}`, {
        center: draft.lonLat,
        extent: map ? currentExtentFromMap(map) : undefined
      });
      pushToast("success", "标注已添加", trimmed.length > 24 ? `${trimmed.slice(0, 24)}…` : trimmed);
    },
    [annotationDraft, pushToast]
  );

  useEffect(() => {
    const { items, summary } = parsePoiResults(layerState);
    setSearchResults(items);
    setSearchSummary(summary);
    const signature = JSON.stringify([summary, items.map((item) => item.poi_id)]);
    if (items.length && signature !== lastPoiSignatureRef.current) {
      lastPoiSignatureRef.current = signature;
      setStatsCardOpen(false);
      setSearchCardOpen(true);
    }
  }, [layerState]);

  return (
    <div
      className={`screen-shell screen-shell-classroom view-mode-${viewMode}`}
      data-interaction-mode={interactionMode}
    >
      <div
        ref={mapElementRef}
        className={`map-canvas map-canvas-mode-${interactionMode} ${viewMode === "plane" ? "" : "is-hidden"}`}
        data-testid="map-canvas"
      />
      <Map3DGlobe
        ref={globeRef}
        visible={viewMode === "globe"}
        imageryUrl={globeImageryUrl}
        showGraticule={showGraticule}
        themeIds={globeThemeIds}
        onThemeError={(themeId, message) => {
          pushToast("error", "三维专题图层加载失败", `${themeId}: ${message}`);
        }}
        onCameraChange={setGlobeCamera}
        onAltitudeThreshold={urbanActive ? undefined : handleGlobeAltitudeThreshold}
        urbanSource={urbanActive ? urbanSource : null}
        onUrbanStatus={setUrbanStatus}
        onDoubleClickGlobe={handleGlobeDoubleClick}
        onUserInteraction={() => {
          if (lessonGlobePinnedRef.current) {
            lessonGlobePinnedRef.current = false;
            lessonGlobeRestoreRef.current = null;
          }
        }}
        onWebGLError={(message) => {
          lessonGlobePinnedRef.current = false;
          lessonGlobeRestoreRef.current = null;
          pushToast("error", "3D 引擎初始化失败", `${message}。已自动切换到 2D 平面地图。`);
          setViewMode("plane");
        }}
      />
      {viewMode === "globe" && layerState?.base_map.layers.length && !layerState.base_map.layers.some(layer => layer.kind === "xyz" && layer.usable_in_3d !== false && layer.urls.length) ? (
        <div className="map-basemap-notice" role="status">
          当前底图仅支持二维，三维显示高德参考底图。
          <button type="button" onClick={() => handleViewModeToggle("plane")}>返回 2D 查看专题图</button>
        </div>
      ) : null}
      <MapEvidenceLegend basemapId={activeBasemapId} layers={layerState?.items || []} globe={viewMode === "globe"} themeIds={globeThemeIds} showFit={showTeachingFit} onShowFit={setShowTeachingFit} />
      <MapBrushOverlay
        projection={mapInkProjection}
        scope={project?.project_id || ""}
        ref={brushRef}
        active={interactionMode === "brush"}
        settings={brushSettings}
        onWheelZoom={handleBrushWheelZoom}
        onContentChange={setMapBrushHasContent}
      />
      <div className="map-vignette" />
      <div className="map-grid-overlay" />
      <div className="map-scanline" />

      <MapInstructionStrip
        mode={interactionMode}
        measureHint={measureText || undefined}
        measureTotalKm={measureTotalKm}
        hasSearchArea={Boolean(searchAreaGeometry)}
        onCancel={() => {
          setInteractionMode("browse");
          setMeasureText("");
          setMeasureTotalKm(null);
          setAnnotationDraft(null);
        }}
        onFinishMeasure={
          interactionMode === "measure"
            ? () => measureDrawRef.current?.finishDrawing?.()
            : undefined
        }
      />

      <AnnotationDialog
        open={Boolean(annotationDraft)}
        location={annotationDraft?.lonLat || null}
        onSubmit={commitAnnotation}
        onCancel={() => {
          setAnnotationDraft(null);
          setInteractionMode("browse");
        }}
      />

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
          <BrandLogo className="brand-logo" />
          <ThemeToggle />
          <div className="brand-title">
            <strong>GeoBot<span className="brand-platform-name"> 智能教学平台</span></strong>
            <span
              className={`connection-dot ${connectionReady ? "connected" : "disconnected"}`}
              aria-label={connectionReady ? "系统已连接" : "系统未连接"}
              title={connectionReady ? "系统已连接" : "系统未连接"}
            />
          </div>
        </div>

        <div className="header-actions">
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
            GIS 分析工作流
          </button>
          <button
            type="button"
            className={`toolbar-button ${databaseViewerOpen ? "active" : ""}`}
            onClick={() => setDatabaseViewerOpen(true)}
          >
            数据库
          </button>
          <button
            type="button"
            className="toolbar-button"
            disabled={pptLoading}
            onClick={() => {
              const input = document.createElement("input");
              input.type = "file";
              input.accept = ".pptx";
              input.onchange = () => {
                const file = input.files?.[0];
                if (file) void handleRenderedPptImport(file);
              };
              input.click();
            }}
          >
            {pptLoading ? "解析中…" : "导入 PPT"}
          </button>
          <button type="button" className="toolbar-button" onClick={() => void handleStartScreenshot()}>
            截图
          </button>
          {initError ? (
            <button
              type="button"
              className="toolbar-button active"
              onClick={() => {
                setProject(null);
                setLayerState(null);
                setOutputs([]);
                setCurrentJob(null);
                setConversationId("");
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
        <div className="header-search">
          <label className="header-search-label" htmlFor="poi-keyword">POI 检索</label>
          <div className="header-search-row">
            <input
              id="poi-keyword"
              aria-label="POI 检索关键词"
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
            <div className="search-dropdown">
              <button
                type="button"
                className="toolbar-button compact"
                disabled={!onlinePoiEnabled}
                onClick={(e) => {
                  e.stopPropagation();
                  setSearchDropdownOpen((v) => !v);
                }}
                aria-expanded={searchDropdownOpen}
              >
                检索
              </button>
              {searchDropdownOpen && (
                <div className="search-dropdown-menu" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    disabled={!onlinePoiEnabled}
                    onClick={() => {
                      setSearchDropdownOpen(false);
                      void handlePoiSearch("view");
                    }}
                  >
                    视域检索
                  </button>
                  <button
                    type="button"
                    disabled={!onlinePoiEnabled || !searchAreaGeometry}
                    onClick={() => {
                      setSearchDropdownOpen(false);
                      void handlePoiSearch("polygon");
                    }}
                  >
                    区域检索
                  </button>
                </div>
              )}
            </div>
            <button
              type="button"
              className="toolbar-button compact"
              disabled={!searchAreaGeometry || !hasVisibleOneMapLayer}
              onClick={() => void handleOneMapStats()}
            >
              统计
            </button>
          </div>
        </div>

      </header>

      <main className="workspace-shell">
        <SearchResultsCard
          open={searchCardOpen}
          summary={searchSummary}
          results={searchResults}
          onClose={() => setSearchCardOpen(false)}
          onFocusResult={focusPoiResult}
        />
        <StatsResultsCard
          open={statsCardOpen}
          stats={oneMapStats}
          onClose={() => setStatsCardOpen(false)}
        />

        <section className="map-workspace" aria-hidden="true" />

        <MapToolsDock>
          <MapToolRail
            layersOpen={layerManagerOpen}
            onToggleLayers={() => setLayerManagerOpen((value) => !value)}
            mode={interactionMode}
            viewMode={viewMode}
            hasSearchArea={Boolean(searchAreaGeometry)}
            hasMeasurements={measurementCount > 0}
            hasAnnotations={annotationCount > 0}
            busy={busy}
            showGraticule={showGraticule}
            onChangeMode={setInteractionMode}
            onChangeViewMode={handleViewModeToggle}
            onToggleGraticule={() => setShowGraticule((value) => !value)}
            onResetView={() => {
              if (viewMode === "globe") {
                globeRef.current?.resetView();
              } else {
                handleResetView();
              }
            }}
            onZoomIn={() => {
              if (viewMode === "globe") {
                const cam = globeCamera;
                if (cam) {
                  globeRef.current?.flyTo(cam.lon, cam.lat, Math.max(cam.altitudeMeters * 0.55, urbanActive ? 100 : 300_000), 0.5);
                }
                return;
              }
              const map = mapRef.current;
              if (!map) {
                return;
              }
              map.getView().animate({ zoom: (map.getView().getZoom() || 4) + 1, duration: 300 });
            }}
            onZoomOut={() => {
              if (viewMode === "globe") {
                const cam = globeCamera;
                if (cam) {
                  globeRef.current?.flyTo(cam.lon, cam.lat, Math.min(cam.altitudeMeters * 1.8, 30_000_000), 0.5);
                }
                return;
              }
              const map = mapRef.current;
              if (!map) {
                return;
              }
              map.getView().animate({ zoom: (map.getView().getZoom() || 4) - 1, duration: 300 });
            }}
            onClear={() => void handleClearWorkspace()}
          />

          <VisualMapPanel
            viewMode={viewMode}
            activeThemeIds={globeThemeIds}
            onChangeThemes={(ids) => {
              lessonGlobePinnedRef.current = false;
              lessonGlobeRestoreRef.current = null;
              setUrbanActive(false);
              setGlobeThemeIds(ids);
              // 开启 3D 主题时经统一过渡切到地球（带相机同步），而非硬切。
              if (ids.length && viewMode === "plane") {
                transitionToGlobe({ reason: "manual" });
              }
            }}
            onApplyScene={(preset) => {
              lessonGlobePinnedRef.current = false;
              lessonGlobeRestoreRef.current = null;
              setViewMode("globe");
              setUrbanActive(false);
              setGlobeThemeIds(preset.themes);
              globeRef.current?.lookAtLocation(
                preset.camera.lon, 35, preset.camera.altitudeMeters, preset.camera.pitchDeg
              );
            }}
            textbookItems={textbookMapItems}
            textbookActiveIds={textbookActiveIds}
            busy={busy}
            catalogError={datasetCatalogError}
            onRetryCatalog={() => {
              setDatasetCatalogError(false);
              fetchDatasetCatalog()
                .then((res) => {
                  setDatasetCatalogItems(res.items || []);
                  setDatasetCatalogError(false);
                })
                .catch(() => {
                  setDatasetCatalogItems([]);
                  setDatasetCatalogError(true);
                });
            }}
            onToggleTextbook={(id, visible) => {
              // 只有"显示"一个 2D 图层才需要切到平面模式；在地球模式下
              // 取消勾选不再把用户踹回平面（修复既有反直觉行为）。
              if (visible && viewMode === "globe") {
                handleViewModeToggle("plane");
              }
              void handleToggleTextbookMap(id, visible);
            }}
          />

          <UrbanStudyPanel active={urbanActive} source={urbanSource} status={urbanStatus}
            onVisit={stop => { lessonGlobePinnedRef.current=false; lessonGlobeRestoreRef.current=null; setUrbanActive(true); setViewMode("globe"); setGlobeThemeIds([]); globeRef.current?.lookAtLocation(stop.lon,stop.lat,stop.range); }}
            onSource={setUrbanSource}
            onExit={() => {setUrbanActive(false);setUrbanSource(null);globeRef.current?.resetView();}} />
        </MapToolsDock>
        </main>

        <aside
          className="account-dock"
          data-testid="account-dock"
          aria-label="当前登录账号"
        >
          <UserMenu
            user={currentUser}
            onLogout={onLogout}
            onUserChanged={onUserChanged}
          />
        </aside>

      {interactionMode === "brush" ? (
        <BrushToolbar
          settings={brushSettings}
          hasContent={brushTargetHasContent}
          onChangeSettings={(next) => setBrushSettings((prev) => ({ ...prev, ...next }))}
          onUndo={() => brushTargetRef.current?.undo()}
          onClear={() => brushTargetRef.current?.clear()}
        />
      ) : null}

      {project ? (
        <>
        <AgentControlOverlay
          active={interactionBusy}
          listening={overlayListening}
          partialTranscript={overlayPartial}
          capturedCommand={overlayCaptured}
          workingDetail={
            interactionBusy
              ? Object.values(currentJob?.stages || {}).find((stage) => stage?.status === "running")?.summary || ""
              : ""
          }
          pulseSignal={overlayPulse}
        />
        <CopilotWidget
          chatLog={assistantTab === "interaction" ? interactionChatLog : chatLog}
          currentJob={currentJob}
          inputValue={assistantInput}
          onInputChange={setAssistantInput}
          assistantTab={assistantTab}
          onTabChange={(tab) => {
            setAssistantTab(tab);
            assistantTabRef.current = tab;
          }}
          ttsEnabled={ttsEnabled}
          onTtsToggle={(enabled) => setTtsEnabled(enabled)}
          voiceStreamAvailable={Boolean(health?.voice_asr?.available)}
          onListeningChange={setOverlayListening}
          onPartialTranscript={setOverlayPartial}
          onCapturedCommand={(command) => {
            setOverlayCaptured(command);
            window.setTimeout(() => setOverlayCaptured((current) => (current === command ? "" : current)), 1200);
          }}
          onSubmit={() => {
            const message = assistantInput.trim();
            if (!message && !pendingImage) {
              return;
            }
            const image = pendingImage;
            void submitAssistantText(message, undefined, "webgis", "text", image).then((sent) => {
              if (!sent) return;
              setAssistantInput((current) => (current.trim() === message ? "" : current));
              setPendingImage((current) => (current?.artifact_id === image?.artifact_id ? null : current));
            });
          }}
          onQuickPrompt={(prompt) => {
            const message = prompt.trim();
            if (!message) {
              return;
            }
            const image = pendingImage;
            void submitAssistantText(message, undefined, "webgis", "text", image).then((sent) => {
              if (sent) setPendingImage((current) => (current?.artifact_id === image?.artifact_id ? null : current));
            });
          }}
          onConfirm={(confirmationId, decision = "approve") => {
            void confirmAssistantAction(confirmationId, decision).then((response) => subscribeToJob(response.job_id));
          }}
          onVoiceSubmit={(message) => {
            const transcript = message.trim();
            if (!transcript) {
              return;
            }
            const image = pendingImage;
            void submitAssistantText(transcript, undefined, "webgis", "voice", image).then((sent) => {
              if (sent) setPendingImage((current) => (current?.artifact_id === image?.artifact_id ? null : current));
            });
          }}
          onVoiceNotice={(tone, title, detail) => {
            pushToast(tone, title, detail);
          }}
          busy={busy}
          teachingPhase={teachingPhase}
          pendingImage={pendingImage}
          openSignal={copilotOpenSignal}
          onAttachImage={handleAttachImage}
          onUploadImage={(file) => void handleUploadImage(file)}
          onRemoveImage={() => setPendingImage(null)}
          onGenerateImage={handleGenerateImage}
          imageGenerationLoading={imageGenerationLoading}
          imageGenerationConfigured={Boolean(health?.image_generation?.configured)}
          imageGenerationModel={health?.image_generation?.model || "image-01"}
        />
        </>
      ) : null}

      {screenshotSource && screenshotBounds ? (
        <ScreenshotSelector
          bounds={screenshotBounds}
          onComplete={(selection) => void handleCompleteScreenshot(selection)}
          onCancel={() => {
            pendingEvidenceSnapshotRef.current = null;
            setScreenshotSource("");
            setScreenshotBounds(null);
          }}
        />
      ) : null}

        <LessonWorkflowShell
          project={project}
          assistantJob={currentJob}
          layerState={layerState}
          busy={busy}
          openSignal={lessonWorkflowOpenSignal}
          onOpenDesignWorkspace={() => openLessonDesignWorkspace()}
          rehearsalSignal={rehearsalTarget.signal}
          rehearsalLessonId={rehearsalTarget.lessonId}
          onRefresh={() => (project ? refreshProjectState(project.project_id) : undefined)}
          onTeachingContextChange={(ctx) => {
            teachingContextRef.current = ctx;
            setTeachingPhase(ctx?.phase || "");
          }}
          onAssistantPrompt={(prompt, displayMessage) => assistantDispatchRef.current(prompt, undefined, displayMessage)}
          onApplyGlobeScene={handleApplyLessonGlobeScene}
          getGlobeSceneSnapshot={getLessonGlobeSceneSnapshot}
          onFocusEvidenceLayer={(datasetId, stageDatasetIds) => {
            void handleFocusLessonEvidenceLayer(datasetId, stageDatasetIds);
          }}
          onRequestPlaneView={() => handleViewModeToggle("plane")}
          onCaptureEvidence={(sessionId, stageId) => {
            pendingEvidenceSnapshotRef.current = { sessionId, stageId };
            void handleStartScreenshot().then((started) => {
              if (!started) pendingEvidenceSnapshotRef.current = null;
            });
          }}
          statusBar={
            <MapStatusBar
              mode={viewMode}
              lon={viewMode === "globe" ? globeCamera?.lon ?? null : planeViewState?.lon ?? null}
              lat={viewMode === "globe" ? globeCamera?.lat ?? null : planeViewState?.lat ?? null}
              zoom={viewMode === "plane" ? planeViewState?.zoom ?? null : null}
              altitudeMeters={viewMode === "globe" ? globeCamera?.altitudeMeters ?? null : null}
            />
          }
        />
        {project && lessonDesignWorkspace.open ? (
          <LessonDesignWorkspace
            projectId={project.project_id}
            initialDesignId={lessonDesignWorkspace.designId}
            onClose={closeLessonDesignWorkspace}
            onFinalized={() => {
              if (project) void refreshProjectState(project.project_id);
            }}
            onEnterRehearsal={(lesson) => {
              closeLessonDesignWorkspace();
              setRehearsalTarget((previous) => ({ lessonId: lesson.lesson_id, signal: previous.signal + 1 }));
            }}
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
          assistantJob={currentJob}
          mapRef={mapRef}
          open={workflowDockOpen}
          layerState={layerState}
          initialDatasetSource={workflowInitialDataset}
          onRequestClose={() => setWorkflowDockOpen(false)}
          onToast={(tone, message) => pushToast(tone, message)}
        />
        <LayerManager
          open={layerManagerOpen}
          onClose={() => setLayerManagerOpen(false)}
          layers={layerState?.items || []}
          busy={busy}
          onToggleLayer={(layerId, visible) => void handleLayerManagerToggle(layerId, visible)}
          onFocusLayer={(layerId) => void handleLayerManagerFocus(layerId)}
          onDeleteLayer={(layerId) => void handleLayerManagerDelete(layerId)}
          datasetCatalogItems={datasetCatalogItems}
          onLoadDataset={(item) => void handleLayerManagerAddDataset(item)}
        />
        <DatabaseViewer
          open={databaseViewerOpen}
          onClose={() => setDatabaseViewerOpen(false)}
          onUpload={() => setUploadOpen(true)}
          knowledgeItems={kbAllItems}
          layers={layerState?.items || []}
          outputs={outputs}
          lessonResourceSets={lessonResourceSets}
          teachingMaps={teachingMaps}
          datasetCatalogItems={datasetCatalogItems}
          questionBanks={questionBanks}
          activeTeachingMapIds={activeTeachingMapIds}
          activeLessonResourceSetId={activeLessonResourceSetId}
          onOpenKnowledgeItem={handleDatabaseOpenKnowledgeItem}
          onOpenMaterial={handleDatabaseOpenMaterial}
          onToggleLayer={(layerId, visible) => void handleDatabaseToggleLayer(layerId, visible)}
          onFocusLayer={(layerId) => void handleDatabaseFocusLayer(layerId)}
          onOpenArtifact={handleDatabaseOpenArtifact}
          onDownloadArtifact={handleDatabaseDownloadArtifact}
          onDeleteArtifact={(artifact) => void handleDatabaseDeleteArtifact(artifact)}
          onLoadArtifactLayer={(artifact) => void handleDatabaseLoadArtifactLayer(artifact)}
          onAttachImage={handleDatabaseAttachImage}
          onDeleteQuestionBank={(bank) => void handleDatabaseDeleteQuestionBank(bank)}
          onActivateLessonSet={(setId) => void handleDatabaseActivateLessonSet(setId)}
          onToggleTeachingMap={(mapId, visible) => void handleToggleTeachingMap(mapId, visible)}
          onLoadDataset={handleDatabaseLoadDataset}
          onUseDataset={handleDatabaseUseDataset}
          activeCategory={databaseCategory}
          onCategoryChange={setDatabaseCategory}
          resourceQuery={resourceQuery}
          resourceScope={resourceScope}
          resourceLoading={resourceLoading}
          resourceResults={resourceResults}
          onResourceQueryChange={setResourceQuery}
          onResourceScopeChange={(scope) => {
            setResourceScope(scope);
            runResourceSearch(resourceQuery, scope);
          }}
          onResourceSearchSubmit={() => runResourceSearch(resourceQuery, resourceScope)}
          onImportResource={handleImportResourceResult}
          onSaveResource={(item) => void handleSaveResourceResult(item)}
          onOpenResource={handleOpenResourceResult}
        />
        <PptViewer
          open={pptViewerOpen}
          slides={pptSlides}
          fileName={pptFileName}
          onExpand={() => setPptViewerOpen(true)}
          onCollapse={handlePptCollapse}
          onRemove={handlePptRemove}
          brushActive={interactionMode === "brush"}
          brushSettings={brushSettings}
          brushOverlayRef={pptBrushRef}
          onBrushContentChange={setPptBrushHasContent}
        />
      </div>
  );
}
