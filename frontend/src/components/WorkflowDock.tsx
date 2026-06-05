/**
 * WorkflowDock — self-contained GIS analysis workflow UI.
 *
 * Owns:
 *   - the user input box for workflow requests,
 *   - the SSE subscription via useWorkflowStream,
 *   - the lifecycle of OpenLayers layers loaded from artifacts (geojson +
 *     style.json + optional png overlay),
 *   - the WorkflowPanel / LegendPanel / StatsPanel / ResultExplanation views.
 *
 * The dock is intentionally additive: it does not modify the existing
 * CopilotWidget assistant flow, so the rest of App.tsx keeps working.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import GeoJSON from "ol/format/GeoJSON";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import { Fill, Stroke, Style } from "ol/style";
import type { FeatureLike } from "ol/Feature";
import type Map from "ol/Map";

import {
  buildWorkflowFileUrl,
  listWorkflowTemplates,
  submitWorkflow
} from "../api";
import { useWorkflowStream } from "../hooks/useWorkflowStream";
import type {
  GraduatedStyle,
  LayersResponse,
  StatsPayload,
  WorkflowArtifactRecord,
  WorkflowTemplateInfo
} from "../types";
import { LegendPanel } from "./LegendPanel";
import { ResultExplanation } from "./ResultExplanation";
import { StatsPanel } from "./StatsPanel";
import { WorkflowPanel } from "./WorkflowPanel";

const DEFAULT_FILL = "#cccccc";
const DEFAULT_STROKE = "#444444";

/**
 * Built-in datasets surfaced in the dataset dropdown so a fresh classroom
 * project can submit a workflow without uploading anything first. The keys
 * are the `source` strings the backend's resolve_dataset_path accepts
 * (see backend/app/services/pyqgis_worker/handlers/_common.py).
 */
const BUILTIN_DATASETS: Array<{ source: string; label: string }> = [
  { source: "builtin:population/china_provinces.geojson", label: "内置 · 中国 31 省级行政区（2020 七普人口）" },
  { source: "builtin:population/population_regions.geojson", label: "内置 · 中国 7 大区（演示数据）" },
  { source: "builtin:population/population_centroids.geojson", label: "内置 · 大区中心点（点）" },
  { source: "builtin:population/migration_flows.geojson", label: "内置 · 大区迁徙连线" }
];

/**
 * Templates that need a second dataset (overlay / clip / join / region).
 * The dock shows a second dropdown for these and maps the selection to
 * the template-specific parameter name expected by workflow_templates.py.
 */
const SECONDARY_PARAM_BY_TEMPLATE: Record<string, { paramName: string; label: string }> = {
  clip_to_region: { paramName: "region_dataset", label: "裁剪区域图层" },
  overlay_intersection: { paramName: "overlay_dataset", label: "叠加图层" },
  spatial_join_attributes: { paramName: "join_dataset", label: "属性来源图层" }
};

export type WorkflowDockProps = {
  projectId: string;
  mapRef: React.MutableRefObject<Map | null>;
  /** Whether the dock is visible; collapsing the dock keeps state. */
  open?: boolean;
  /** Project layer state, used to populate the dataset selector with
   * uploaded layers in addition to the built-in defaults. */
  layerState?: LayersResponse | null;
  /** Called when the user closes the dock from inside the component. */
  onRequestClose?: () => void;
  /** Optional toast shim so the dock can surface errors via the host UI. */
  onToast?: (level: "info" | "error" | "success", message: string) => void;
};

function pickArtifact(
  artifacts: WorkflowArtifactRecord[],
  kind: string
): WorkflowArtifactRecord | undefined {
  return artifacts.find((item) => item.kind === kind);
}

function styleClassFor(style: GraduatedStyle | null, value: number): string {
  if (!style || !style.classes || style.classes.length === 0) {
    return DEFAULT_FILL;
  }
  for (const cls of style.classes) {
    if (value >= cls.min && value <= cls.max) {
      return cls.color;
    }
  }
  return style.default?.color || DEFAULT_FILL;
}

function buildStyleFunction(style: GraduatedStyle | null) {
  return (feature: FeatureLike) => {
    const raw = style ? feature.get(style.field) : undefined;
    let color = DEFAULT_FILL;
    if (style && typeof raw === "number" && Number.isFinite(raw)) {
      color = styleClassFor(style, raw);
    } else if (style && typeof raw === "string" && !Number.isNaN(Number(raw))) {
      color = styleClassFor(style, Number(raw));
    }
    return new Style({
      fill: new Fill({ color }),
      stroke: new Stroke({
        color: style?.stroke?.color || DEFAULT_STROKE,
        width: style?.stroke?.width ?? 0.6
      })
    });
  };
}

export function WorkflowDock({
  projectId,
  mapRef,
  open = true,
  layerState,
  onRequestClose,
  onToast
}: WorkflowDockProps): JSX.Element | null {
  const [message, setMessage] = useState("");
  const [templates, setTemplates] = useState<WorkflowTemplateInfo[]>([]);
  const [templateId, setTemplateId] = useState<string>("");
  const [primaryDataset, setPrimaryDataset] = useState<string>("");
  const [secondaryDataset, setSecondaryDataset] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [activeWorkflowId, setActiveWorkflowId] = useState<string>("");

  /**
   * Build the dataset dropdown options. Uploaded layers come first (most
   * recent on top, i.e. what the teacher just imported), then built-ins.
   * The value stored is the `source` string the backend expects.
   */
  const datasetOptions = useMemo(() => {
    const uploaded: Array<{ source: string; label: string }> = [];
    const items = layerState?.items || [];
    for (const item of items) {
      if (item.source !== "upload") {
        continue;
      }
      const metadata = item.metadata || {};
      const qgisFile = typeof metadata.qgis_source_file === "string" ? metadata.qgis_source_file : "";
      const sourceFile = typeof metadata.source_file === "string" ? metadata.source_file : "";
      const filename = qgisFile || sourceFile;
      if (!filename || !projectId) {
        continue;
      }
      uploaded.push({
        source: `upload:${projectId}/${filename}`,
        label: `已上传 · ${item.name}`
      });
    }
    return [...uploaded, ...BUILTIN_DATASETS];
  }, [layerState, projectId]);

  const secondaryConfig = templateId ? SECONDARY_PARAM_BY_TEMPLATE[templateId] : undefined;

  const stream = useWorkflowStream(activeWorkflowId);

  const [styleObj, setStyleObj] = useState<GraduatedStyle | null>(null);
  const [statsObj, setStatsObj] = useState<StatsPayload | null>(null);
  const [summaryText, setSummaryText] = useState<string>("");

  const layerRef = useRef<VectorLayer<any> | null>(null);

  // Load template metadata once.
  useEffect(() => {
    listWorkflowTemplates()
      .then((res) => setTemplates(res.items || []))
      .catch(() => setTemplates([]));
  }, []);

  // Load style.json / stats.json / summary.md whenever artifacts change.
  useEffect(() => {
    let cancelled = false;
    const styleArtifact = pickArtifact(stream.artifacts, "style");
    const statsArtifact = pickArtifact(stream.artifacts, "stats");
    const summaryArtifact = pickArtifact(stream.artifacts, "summary");

    if (styleArtifact) {
      fetch(buildWorkflowFileUrl(styleArtifact.public_url))
        .then((res) => (res.ok ? res.json() : null))
        .then((payload) => {
          if (!cancelled && payload && typeof payload === "object" && payload.type === "graduated") {
            setStyleObj(payload as GraduatedStyle);
          }
        })
        .catch(() => undefined);
    } else {
      setStyleObj(null);
    }

    if (statsArtifact) {
      fetch(buildWorkflowFileUrl(statsArtifact.public_url))
        .then((res) => (res.ok ? res.json() : null))
        .then((payload) => {
          if (!cancelled && payload && typeof payload === "object") {
            setStatsObj(payload as StatsPayload);
          }
        })
        .catch(() => undefined);
    } else {
      setStatsObj(null);
    }

    if (summaryArtifact) {
      fetch(buildWorkflowFileUrl(summaryArtifact.public_url))
        .then((res) => (res.ok ? res.text() : ""))
        .then((text) => {
          if (!cancelled) {
            setSummaryText(text || "");
          }
        })
        .catch(() => undefined);
    } else {
      setSummaryText("");
    }

    return () => {
      cancelled = true;
    };
  }, [stream.artifacts]);

  // Load the GeoJSON onto the map whenever a geojson artifact arrives.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    const geojsonArtifact = pickArtifact(stream.artifacts, "geojson");
    if (!geojsonArtifact) {
      return;
    }
    const url = buildWorkflowFileUrl(geojsonArtifact.public_url);
    if (!url) {
      return;
    }

    let cancelled = false;
    fetch(url)
      .then((res) => (res.ok ? res.json() : null))
      .then((payload) => {
        if (cancelled || !payload) {
          return;
        }
        const format = new GeoJSON();
        const features = format.readFeatures(payload, {
          dataProjection: "EPSG:4326",
          featureProjection: "EPSG:3857"
        });
        if (layerRef.current) {
          map.removeLayer(layerRef.current);
          layerRef.current = null;
        }
        const source = new VectorSource({ features });
        const layer = new VectorLayer({
          source,
          style: buildStyleFunction(styleObj),
          zIndex: 220
        });
        layer.set("workflow_layer", true);
        layer.set("workflow_id", stream.workflowId);
        map.addLayer(layer);
        layerRef.current = layer;
        const extent = source.getExtent();
        if (extent && extent.every((value) => Number.isFinite(value))) {
          map.getView().fit(extent, { duration: 400, padding: [60, 60, 60, 60] });
        }
        if (onToast) {
          onToast("success", "工作流结果已加载到地图");
        }
      })
      .catch(() => {
        if (onToast) {
          onToast("error", "加载结果 GeoJSON 失败");
        }
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.artifacts, mapRef]);

  // Re-apply style when style.json updates.
  useEffect(() => {
    if (layerRef.current) {
      layerRef.current.setStyle(buildStyleFunction(styleObj));
      layerRef.current.changed();
    }
  }, [styleObj]);

  // Cleanup layer when dock unmounts or workflow id resets.
  useEffect(() => {
    return () => {
      const map = mapRef.current;
      if (map && layerRef.current) {
        map.removeLayer(layerRef.current);
        layerRef.current = null;
      }
    };
  }, [mapRef]);

  const handleSubmit = useCallback(async () => {
    if (!projectId) {
      onToast?.("error", "未找到当前项目，无法提交工作流");
      return;
    }
    const text = message.trim();
    if (!text) {
      return;
    }
    // Build parameters payload. When the user picks a primary dataset we
    // pass it under every parameter alias the backend templates recognise
    // (dataset / input_dataset / facility_dataset / province_dataset). Each
    // template builder only reads the alias it knows about, so the extras
    // are harmless and we don't need to know which template the backend
    // ends up routing "自动识别" to.
    const parameters: Record<string, unknown> = {};
    if (primaryDataset) {
      parameters.dataset = primaryDataset;
      parameters.input_dataset = primaryDataset;
      parameters.facility_dataset = primaryDataset;
      parameters.province_dataset = primaryDataset;
    }
    if (secondaryConfig && secondaryDataset) {
      parameters[secondaryConfig.paramName] = secondaryDataset;
    }
    setSubmitting(true);
    try {
      const response = await submitWorkflow({
        project_id: projectId,
        message: text,
        mode: "template",
        template_id: templateId || "",
        parameters
      });
      if (response.workflow_id) {
        setActiveWorkflowId(response.workflow_id);
        if (response.error) {
          onToast?.("error", response.error.user_friendly || response.error.message);
        }
      } else if (response.error) {
        onToast?.("error", response.error.user_friendly || response.error.message);
      }
    } catch (err) {
      onToast?.("error", err instanceof Error ? err.message : "提交工作流失败");
    } finally {
      setSubmitting(false);
    }
  }, [message, onToast, primaryDataset, projectId, secondaryConfig, secondaryDataset, templateId]);

  const handleClear = useCallback(() => {
    setActiveWorkflowId("");
    setStyleObj(null);
    setStatsObj(null);
    setSummaryText("");
    const map = mapRef.current;
    if (map && layerRef.current) {
      map.removeLayer(layerRef.current);
      layerRef.current = null;
    }
  }, [mapRef]);

  const placeholder = useMemo(() => {
    if (!templates.length) {
      return "示例：制作中国人口密度分级设色图";
    }
    return `示例：${templates[0]?.title || "制作专题图"}`;
  }, [templates]);

  if (!open) {
    return null;
  }

  return (
    <aside className="workflow-dock" data-testid="workflow-dock">
      <header className="workflow-dock__header">
        <h2>GIS 分析工作流</h2>
        {onRequestClose ? (
          <button type="button" className="workflow-dock__close" onClick={onRequestClose} aria-label="关闭">
            ×
          </button>
        ) : null}
      </header>

      <div className="workflow-dock__form">
        <label className="workflow-dock__label">
          工作流模板
          <select
            value={templateId}
            onChange={(event) => {
              setTemplateId(event.target.value);
              setSecondaryDataset("");
            }}
            disabled={submitting}
          >
            <option value="">自动识别</option>
            {templates.map((template) => (
              <option key={template.id} value={template.id}>
                {template.title}
              </option>
            ))}
          </select>
        </label>

        <label className="workflow-dock__label" data-testid="workflow-dock-dataset">
          数据集
          <select
            value={primaryDataset}
            onChange={(event) => setPrimaryDataset(event.target.value)}
            disabled={submitting}
          >
            <option value="">默认（按模板）</option>
            {datasetOptions.map((option) => (
              <option key={option.source} value={option.source}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        {secondaryConfig ? (
          <label className="workflow-dock__label" data-testid="workflow-dock-dataset-secondary">
            {secondaryConfig.label}
            <select
              value={secondaryDataset}
              onChange={(event) => setSecondaryDataset(event.target.value)}
              disabled={submitting}
            >
              <option value="">默认（按模板）</option>
              {datasetOptions.map((option) => (
                <option key={option.source} value={option.source}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <textarea
          className="workflow-dock__input"
          placeholder={placeholder}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          rows={3}
          disabled={submitting}
        />
        <div className="workflow-dock__actions">
          <button
            type="button"
            className="workflow-dock__submit"
            onClick={handleSubmit}
            disabled={submitting || !message.trim()}
          >
            {submitting ? "提交中…" : "提交工作流"}
          </button>
          {activeWorkflowId ? (
            <button type="button" className="workflow-dock__reset" onClick={handleClear}>
              清空当前结果
            </button>
          ) : null}
        </div>
      </div>

      <WorkflowPanel
        workflowId={stream.workflowId}
        status={stream.status}
        intent={stream.intent}
        steps={stream.steps}
        error={stream.error}
        onClear={activeWorkflowId ? handleClear : undefined}
      />
      <LegendPanel style={styleObj} />
      <StatsPanel stats={statsObj} />
      <ResultExplanation markdown={summaryText} />
    </aside>
  );
}
