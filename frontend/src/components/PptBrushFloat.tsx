import { useEffect, useRef, useState } from "react";
import "./PptBrushFloat.css";
import type { BrushSettings } from "./BrushOverlay";

type Props = {
  settings: BrushSettings;
  hasContent: boolean;
  onChangeSettings: (next: Partial<BrushSettings>) => void;
  onUndo: () => void;
  onClear: () => void;
  onExit: () => void;
};

const TOOLS: Array<{ id: BrushSettings["tool"]; label: string }> = [
  { id: "freehand", label: "自由" },
  { id: "line", label: "直线" },
  { id: "rectangle", label: "矩形" },
  { id: "ellipse", label: "椭圆" },
  { id: "arrow", label: "箭头" },
  { id: "eraser", label: "橡皮" }
];
const COLORS = ["#ff4444", "#ffcc00", "#44cc44", "#4488ff", "#ffffff", "#cc66ff"];
const WIDTHS = [2, 4, 8];

// 放映界面内的轻量画笔浮层：选完工具收起为小把手，结束画笔退出绘制状态。
export function PptBrushFloat({ settings, hasContent, onChangeSettings, onUndo, onClear, onExit }: Props) {
  const [expanded, setExpanded] = useState(true);
  const handleRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!expanded) handleRef.current?.focus();
  }, [expanded]);
  if (!expanded) {
    return (
      <div className="ppt-brush-float ppt-brush-mini" data-testid="ppt-brush-mini">
        <button
          ref={handleRef}
          type="button"
          className="ppt-brush-handle"
          aria-label="展开画笔设置"
          aria-expanded={false}
          title={`${TOOLS.find((item) => item.id === settings.tool)?.label || settings.tool} · ${settings.color}`}
          onClick={() => setExpanded(true)}
        >
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="m4 16 12-12 4 4L8 20H4v-4Zm10-10 4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </button>
        <button type="button" className="ppt-brush-exit" data-testid="ppt-brush-exit" onClick={onExit}>
          结束画笔
        </button>
      </div>
    );
  }
  return (
    <div className="ppt-brush-float" data-testid="ppt-brush-float" role="toolbar" aria-label="PPT 画笔设置">
      <div className="ppt-brush-row">
        {TOOLS.map((tool) => (
          <button
            key={tool.id}
            type="button"
            className={`ppt-brush-chip ${settings.tool === tool.id ? "active" : ""}`}
            aria-label={`画笔工具${tool.label}`}
            aria-pressed={settings.tool === tool.id}
            onClick={() => {
              onChangeSettings({ tool: tool.id });
              setExpanded(false); // 选完工具收起设置，回到放映画面
            }}
          >
            {tool.label}
          </button>
        ))}
        <button type="button" className="ppt-brush-action" aria-label="收起画笔设置" onClick={() => setExpanded(false)}>
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="m4 10 4-4 4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </button>
      </div>
      <div className="ppt-brush-row">
        {COLORS.map((color) => (
          <button
            key={color}
            type="button"
            aria-label={`画笔颜色${color}`}
            aria-pressed={settings.color === color}
            className={`ppt-brush-color ${settings.color === color ? "active" : ""}`}
            style={{ background: color }}
            onClick={() => onChangeSettings({ color })}
          />
        ))}
        {WIDTHS.map((width) => (
          <button
            key={width}
            type="button"
            aria-label={`画笔粗细${width}`}
            aria-pressed={settings.lineWidth === width}
            className={`ppt-brush-width ${settings.lineWidth === width ? "active" : ""}`}
            onClick={() => onChangeSettings({ lineWidth: width })}
          >
            <span style={{ width: width + 4, height: width + 4 }} />
          </button>
        ))}
        <span className="ppt-brush-spacer" />
        <button type="button" className="ppt-brush-action" disabled={!hasContent} onClick={onUndo}>
          撤销
        </button>
        <button type="button" className="ppt-brush-action" disabled={!hasContent} onClick={onClear}>
          清空
        </button>
        <button type="button" className="ppt-brush-exit" data-testid="ppt-brush-exit" onClick={onExit}>
          结束画笔
        </button>
      </div>
    </div>
  );
}
