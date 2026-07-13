import type { ReactNode } from "react";
import type { InteractionMode } from "./MapToolRail";

type Props = {
  mode: InteractionMode;
  measureHint?: string;
  measureTotalKm?: number | null;
  hasSearchArea: boolean;
  onCancel: () => void;
  onFinishMeasure?: () => void;
};

type Instruction = {
  icon: ReactNode;
  title: string;
  desc: string;
};

const STROKE = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const
};

function PinIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <path d="M12 3 a6 6 0 0 1 6 6 c0 4.5-6 11.5-6 11.5 S6 13.5 6 9 a6 6 0 0 1 6-6 Z" {...STROKE} />
      <circle cx="12" cy="9.2" r="2" {...STROKE} />
    </svg>
  );
}

function RulerIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <rect x="2.5" y="9" width="19" height="6" rx="1.2" {...STROKE} transform="rotate(-22 12 12)" />
      <path d="M6.4 13.6 L7 12.5 M9.1 14.6 L9.9 13.1 M11.9 15.6 L12.5 14.5 M14.7 16.6 L15.5 15.1 M17.4 17.6 L18 16.5" {...STROKE} />
    </svg>
  );
}

function PolygonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <path d="M5 7 L13 4 L20 8.5 L17.5 18 L8 19 Z" {...STROKE} strokeDasharray="3 2.5" />
    </svg>
  );
}

function BrushSmallIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <path d="M4 20 Q6 14 10 15 Q14 16 14 10 Q14 6 18 4" {...STROKE} />
      <circle cx="19" cy="3" r="1.3" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function MapInstructionStrip({
  mode,
  measureHint,
  measureTotalKm,
  hasSearchArea,
  onCancel,
  onFinishMeasure
}: Props) {
  if (mode === "browse") {
    return null;
  }

  const instructions: Record<Exclude<InteractionMode, "browse">, Instruction> = {
    annotate: {
      icon: <PinIcon />,
      title: "标注模式",
      desc: "点击地图任意位置添加教学注释，可在弹窗中填写文字内容。"
    },
    measure: {
      icon: <RulerIcon />,
      title: "测距模式",
      desc: measureHint || "依次点击地图添加测点，双击结束当前测线。"
    },
    "draw-search": {
      icon: <PolygonIcon />,
      title: "绘区模式",
      desc: hasSearchArea
        ? "已存在检索区。继续绘制将覆盖原区域，双击结束绘制。"
        : "在地图上依次点击勾勒多边形，双击结束 — 用作 POI 区域检索范围。"
    },
    brush: {
      icon: <BrushSmallIcon />,
      title: "画笔模式",
      desc: "在地图上自由圈画、标注。右侧工具栏可切换画笔、形状、颜色和粗细。"
    }
  };

  const info = instructions[mode];
  const showFinishButton = mode === "measure" && Boolean(onFinishMeasure);

  return (
    <div className="map-instruction-strip" role="status" aria-live="polite">
      <span className="map-instruction-icon" aria-hidden="true">
        {info.icon}
      </span>
      <div className="map-instruction-text">
        <strong>
          {info.title}
          {mode === "measure" && typeof measureTotalKm === "number" ? (
            <em className="map-instruction-meta"> · 当前 {measureTotalKm.toFixed(2)} 千米</em>
          ) : null}
        </strong>
        <span>{info.desc}</span>
      </div>
      <div className="map-instruction-actions">
        {showFinishButton ? (
          <button type="button" className="map-instruction-finish" onClick={onFinishMeasure}>
            完成
          </button>
        ) : null}
        <button type="button" className="map-instruction-cancel" onClick={onCancel}>
          <kbd>Esc</kbd>
          <span>取消</span>
        </button>
      </div>
    </div>
  );
}
