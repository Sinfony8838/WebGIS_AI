import type { BrushTool, BrushSettings } from "./BrushOverlay";

type Props = {
  settings: BrushSettings;
  hasContent: boolean;
  onChangeSettings: (next: Partial<BrushSettings>) => void;
  onUndo: () => void;
  onClear: () => void;
};

const STROKE = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const
};

const TOOLS: Array<{ tool: BrushTool; label: string; tip: string }> = [
  { tool: "freehand", label: "画笔", tip: "自由绘制" },
  { tool: "line", label: "直线", tip: "绘制直线" },
  { tool: "rectangle", label: "矩形", tip: "绘制矩形" },
  { tool: "ellipse", label: "椭圆", tip: "绘制椭圆" },
  { tool: "arrow", label: "箭头", tip: "绘制箭头" },
  { tool: "eraser", label: "橡皮", tip: "擦除笔迹" }
];

const COLORS = [
  { value: "#ff4444", name: "红" },
  { value: "#ffcc00", name: "黄" },
  { value: "#44cc44", name: "绿" },
  { value: "#4488ff", name: "蓝" },
  { value: "#ffffff", name: "白" },
  { value: "#cc66ff", name: "紫" }
];

const WIDTHS = [
  { value: 2, label: "细" },
  { value: 4, label: "中" },
  { value: 8, label: "粗" }
];

function FreehandIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path d="M4 18 Q8 10 12 14 Q16 18 20 8" {...STROKE} />
      <circle cx="20" cy="8" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

function LineIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path d="M5 19 L19 5" {...STROKE} />
      <circle cx="5" cy="19" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="19" cy="5" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

function RectIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <rect x="4" y="6" width="16" height="12" rx="1" {...STROKE} />
    </svg>
  );
}

function EllipseIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <ellipse cx="12" cy="12" rx="8" ry="6" {...STROKE} />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path d="M5 19 L19 5" {...STROKE} />
      <path d="M13 5 L19 5 L19 11" {...STROKE} />
    </svg>
  );
}

function EraserIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path d="M9 20 H20" {...STROKE} />
      <path d="M5.5 16.5 L3 19 L9 20 L18.5 10.5 L13.5 5.5 Z" {...STROKE} />
      <path d="M13.5 5.5 L18.5 10.5" {...STROKE} />
    </svg>
  );
}

function UndoIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path d="M5 12 A7 7 0 1 1 12 19" {...STROKE} />
      <path d="M2.5 8.5 L5 12 L8.5 9.5" {...STROKE} />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
      <path d="M5 7 H19 M9 7 V5 a1.5 1.5 0 0 1 1.5-1.5 h3 A1.5 1.5 0 0 1 15 5 V7" {...STROKE} />
      <path d="M6.5 7 L7.5 19 a1.5 1.5 0 0 0 1.5 1.5 h6 a1.5 1.5 0 0 0 1.5-1.5 L17.5 7" {...STROKE} />
    </svg>
  );
}

const TOOL_ICONS: Record<BrushTool, () => JSX.Element> = {
  freehand: FreehandIcon,
  line: LineIcon,
  rectangle: RectIcon,
  ellipse: EllipseIcon,
  arrow: ArrowIcon,
  eraser: EraserIcon
};

export function BrushToolbar({ settings, hasContent, onChangeSettings, onUndo, onClear }: Props) {
  return (
    <div className="brush-toolbar glass-panel" role="toolbar" aria-label="画笔工具">
      <div className="brush-toolbar-section">
        <span className="brush-toolbar-label">工具</span>
        <div className="brush-toolbar-tools">
          {TOOLS.map(({ tool, label, tip }) => {
            const Icon = TOOL_ICONS[tool];
            return (
              <button
                key={tool}
                type="button"
                className={`brush-tool-btn ${settings.tool === tool ? "active" : ""}`}
                aria-pressed={settings.tool === tool}
                aria-label={label}
                title={tip}
                onClick={() => onChangeSettings({ tool })}
              >
                <Icon />
              </button>
            );
          })}
        </div>
      </div>

      <div className="brush-toolbar-divider" aria-hidden="true" />

      <div className="brush-toolbar-section">
        <span className="brush-toolbar-label">颜色</span>
        <div className="brush-toolbar-colors">
          {COLORS.map(({ value, name }) => (
            <button
              key={value}
              type="button"
              className={`brush-color-btn ${settings.color === value ? "active" : ""}`}
              aria-label={name}
              title={name}
              style={{ "--brush-swatch": value } as React.CSSProperties}
              onClick={() => onChangeSettings({ color: value })}
            >
              <span className="brush-color-dot" />
            </button>
          ))}
        </div>
      </div>

      <div className="brush-toolbar-divider" aria-hidden="true" />

      <div className="brush-toolbar-section">
        <span className="brush-toolbar-label">粗细</span>
        <div className="brush-toolbar-widths">
          {WIDTHS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              className={`brush-width-btn ${settings.lineWidth === value ? "active" : ""}`}
              aria-label={label}
              title={`${label} (${value}px)`}
              onClick={() => onChangeSettings({ lineWidth: value })}
            >
              <span
                className="brush-width-dot"
                style={{ width: value + 4, height: value + 4 }}
              />
            </button>
          ))}
        </div>
      </div>

      <div className="brush-toolbar-divider" aria-hidden="true" />

      <div className="brush-toolbar-section brush-toolbar-actions">
        <button
          type="button"
          className="brush-tool-btn"
          aria-label="撤销"
          title="撤销上一步绘制"
          onClick={onUndo}
        >
          <UndoIcon />
        </button>
        <button
          type="button"
          className="brush-tool-btn danger"
          aria-label="清除"
          title="清除所有画笔内容"
          disabled={!hasContent}
          onClick={onClear}
        >
          <TrashIcon />
        </button>
      </div>
    </div>
  );
}
