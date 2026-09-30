import { useState } from "react";
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
  if (!expanded) {
    return (
      <div className="ppt-brush-float ppt-brush-mini" data-testid="ppt-brush-mini">
        <button
          type="button"
          className="ppt-brush-handle"
          aria-label="展开画笔设置"
          title={`${TOOLS.find((item) => item.id === settings.tool)?.label || settings.tool} · ${settings.color}`}
          onClick={() => setExpanded(true)}
        >
          ✎
        </button>
        <button type="button" className="ppt-brush-exit" data-testid="ppt-brush-exit" onClick={onExit}>
          结束画笔
        </button>
      </div>
    );
  }
  return (
    <div className="ppt-brush-float" data-testid="ppt-brush-float">
      <div className="ppt-brush-row">
        {TOOLS.map((tool) => (
          <button
            key={tool.id}
            type="button"
            className={`ppt-brush-chip ${settings.tool === tool.id ? "active" : ""}`}
            aria-label={`画笔工具${tool.label}`}
            onClick={() => {
              onChangeSettings({ tool: tool.id });
              setExpanded(false); // 选完工具收起设置，回到放映画面
            }}
          >
            {tool.label}
          </button>
        ))}
      </div>
      <div className="ppt-brush-row">
        {COLORS.map((color) => (
          <button
            key={color}
            type="button"
            aria-label={`画笔颜色${color}`}
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
