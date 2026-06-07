import type { ReactNode } from "react";
import { MapModeToggle } from "./MapModeToggle";
import type { ViewMode } from "../lib/viewMode";

export type InteractionMode = "browse" | "annotate" | "measure" | "draw-search" | "brush";

type Props = {
  /** Current interaction mode (browse / annotate / measure / draw-search). */
  mode: InteractionMode;
  /** Current map view mode (3D globe vs 2D plane). Used to gate tools. */
  viewMode: ViewMode;
  hasSearchArea: boolean;
  hasMeasurements: boolean;
  hasAnnotations: boolean;
  busy: boolean;
  showGraticule: boolean;
  onChangeMode: (mode: InteractionMode) => void;
  onChangeViewMode: (next: ViewMode) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onClear: () => void;
  onToggleGraticule: () => void;
  /** Globe-only: reset the camera to the default Asia-centric view. */
  onResetGlobeView?: () => void;
};

type ToolDescriptor = {
  mode: InteractionMode;
  label: string;
  hint: string;
  shortcut: string;
  icon: ReactNode;
};

const STROKE_PROPS = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const
};

function CursorIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
      <path d="M5.5 4.2 L18 11.4 L11.4 12.8 L9 19.5 Z" {...STROKE_PROPS} />
    </svg>
  );
}

function PinIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
      <path d="M12 3 a6 6 0 0 1 6 6 c0 4.5-6 11.5-6 11.5 S6 13.5 6 9 a6 6 0 0 1 6-6 Z" {...STROKE_PROPS} />
      <circle cx="12" cy="9.2" r="2" {...STROKE_PROPS} />
    </svg>
  );
}

function RulerIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
      <rect x="2.5" y="9" width="19" height="6" rx="1.2" {...STROKE_PROPS} transform="rotate(-22 12 12)" />
      <path d="M6.4 13.6 L7 12.5 M9.1 14.6 L9.9 13.1 M11.9 15.6 L12.5 14.5 M14.7 16.6 L15.5 15.1 M17.4 17.6 L18 16.5" {...STROKE_PROPS} />
    </svg>
  );
}

function PolygonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
      <path d="M5 7 L13 4 L20 8.5 L17.5 18 L8 19 Z" {...STROKE_PROPS} strokeDasharray="3 2.5" />
      <circle cx="5" cy="7" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="13" cy="4" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="20" cy="8.5" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="17.5" cy="18" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="8" cy="19" r="1.4" fill="currentColor" stroke="none" />
    </svg>
  );
}

function BrushIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
      <path d="M4 20 Q6 14 10 15 Q14 16 14 10 Q14 6 18 4" {...STROKE_PROPS} />
      <circle cx="19" cy="3" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="18" cy="4" r="1.3" fill="currentColor" stroke="none" />
    </svg>
  );
}

function ZoomInIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <circle cx="11" cy="11" r="6" {...STROKE_PROPS} />
      <path d="M15.5 15.5 L20 20 M11 8 V14 M8 11 H14" {...STROKE_PROPS} />
    </svg>
  );
}

function ZoomOutIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <circle cx="11" cy="11" r="6" {...STROKE_PROPS} />
      <path d="M15.5 15.5 L20 20 M8 11 H14" {...STROKE_PROPS} />
    </svg>
  );
}

function ClearIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path d="M5 7 H19 M9 7 V5 a1.5 1.5 0 0 1 1.5-1.5 h3 A1.5 1.5 0 0 1 15 5 V7" {...STROKE_PROPS} />
      <path d="M6.5 7 L7.5 19 a1.5 1.5 0 0 0 1.5 1.5 h6 a1.5 1.5 0 0 0 1.5-1.5 L17.5 7" {...STROKE_PROPS} />
    </svg>
  );
}

function GraticuleIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="8.4" {...STROKE_PROPS} />
      <path d="M3.6 12 H20.4 M12 3.6 V20.4 M5.5 6.5 L18.5 17.5 M5.5 17.5 L18.5 6.5" {...STROKE_PROPS} strokeWidth="1.1" />
    </svg>
  );
}

function ResetViewIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path d="M5 12 A7 7 0 1 1 12 19" {...STROKE_PROPS} />
      <path d="M2.5 8.5 L5 12 L8.5 9.5" {...STROKE_PROPS} />
    </svg>
  );
}

const TOOLS: ToolDescriptor[] = [
  {
    mode: "browse",
    label: "选择",
    hint: "点击地图要素查看属性 (B)",
    shortcut: "B",
    icon: <CursorIcon />
  },
  {
    mode: "annotate",
    label: "标注",
    hint: "在地图上添加教学标注 (A)",
    shortcut: "A",
    icon: <PinIcon />
  },
  {
    mode: "measure",
    label: "测距",
    hint: "连续点击量算多段距离 (M)",
    shortcut: "M",
    icon: <RulerIcon />
  },
  {
    mode: "draw-search",
    label: "绘区",
    hint: "绘制多边形作为检索范围 (D)",
    shortcut: "D",
    icon: <PolygonIcon />
  },
  {
    mode: "brush",
    label: "画笔",
    hint: "在地图上自由圈画标注 (P)",
    shortcut: "P",
    icon: <BrushIcon />
  }
];

export function MapToolRail({
  mode,
  viewMode,
  hasSearchArea,
  hasMeasurements,
  hasAnnotations,
  busy,
  showGraticule,
  onChangeMode,
  onChangeViewMode,
  onZoomIn,
  onZoomOut,
  onClear,
  onToggleGraticule,
  onResetGlobeView
}: Props) {
  const canClear = hasSearchArea || hasMeasurements || hasAnnotations || mode !== "browse";
  const isGlobe = viewMode === "globe";
  // 2D-only modes (annotate / measure / draw-search) can't run on the 3D globe
  // because they rely on OpenLayers Draw and pixel-based hit detection.
  const visibleTools = TOOLS.filter((tool) => (isGlobe ? tool.mode === "browse" : true));

  return (
    <section className="tool-group tool-group-rail glass-panel" data-testid="map-tool-rail">
      <header className="tool-group-header">
        <span>地图工具</span>
      </header>

      <div className="tool-rail-mode-row">
        <MapModeToggle mode={viewMode} busy={busy} onChange={onChangeViewMode} />
      </div>

      <div className="tool-rail-divider" aria-hidden="true" />

      <div className="tool-rail-grid" role="group" aria-label="交互模式">
        {visibleTools.map((tool) => {
          const active = mode === tool.mode;
          return (
            <button
              key={tool.mode}
              type="button"
              className={`tool-rail-button ${active ? "active" : ""}`}
              aria-pressed={active}
              aria-label={`${tool.label}模式 · 快捷键 ${tool.shortcut}`}
              title={tool.hint}
              onClick={() => onChangeMode(tool.mode)}
            >
              <span className="tool-rail-icon" aria-hidden="true">
                {tool.icon}
              </span>
              <span className="tool-rail-label">{tool.label}</span>
              <span className="tool-rail-shortcut" aria-hidden="true">
                {tool.shortcut}
              </span>
            </button>
          );
        })}

        <button
          type="button"
          className={`tool-rail-button ${showGraticule ? "active" : ""}`}
          aria-pressed={showGraticule}
          aria-label="经纬网"
          title="切换经纬网叠加"
          onClick={onToggleGraticule}
        >
          <span className="tool-rail-icon" aria-hidden="true">
            <GraticuleIcon />
          </span>
          <span className="tool-rail-label">经纬网</span>
        </button>

        {isGlobe && onResetGlobeView ? (
          <button
            type="button"
            className="tool-rail-button"
            aria-label="重置视角"
            title="将相机重置回亚洲全景视角"
            onClick={onResetGlobeView}
          >
            <span className="tool-rail-icon" aria-hidden="true">
              <ResetViewIcon />
            </span>
            <span className="tool-rail-label">重置视角</span>
          </button>
        ) : null}
      </div>

      <div className="tool-rail-divider" aria-hidden="true" />

      <div className="tool-rail-secondary" role="group" aria-label="视图与清理">
        <button
          type="button"
          className="tool-rail-mini"
          aria-label="放大"
          title="放大视图"
          onClick={onZoomIn}
          disabled={busy}
        >
          <ZoomInIcon />
        </button>
        <button
          type="button"
          className="tool-rail-mini"
          aria-label="缩小"
          title="缩小视图"
          onClick={onZoomOut}
          disabled={busy}
        >
          <ZoomOutIcon />
        </button>
        <button
          type="button"
          className="tool-rail-mini danger"
          aria-label="清除当前操作"
          title="清除标注、测距与检索区"
          onClick={onClear}
          disabled={!canClear}
        >
          <ClearIcon />
        </button>
      </div>
    </section>
  );
}
