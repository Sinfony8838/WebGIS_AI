import { useEffect, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

export type ScreenshotSelection = {
  left: number;
  top: number;
  width: number;
  height: number;
  viewportWidth: number;
  viewportHeight: number;
};

type Point = { x: number; y: number };

type Props = {
  bounds: { left: number; top: number; width: number; height: number };
  preview?: string;
  busy?: boolean;
  onComplete: (selection: ScreenshotSelection) => void;
  onCancel: () => void;
};

function normalizedSelection(start: Point, end: Point, viewportWidth = window.innerWidth, viewportHeight = window.innerHeight): ScreenshotSelection {
  return {
    left: Math.min(start.x, end.x),
    top: Math.min(start.y, end.y),
    width: Math.abs(end.x - start.x),
    height: Math.abs(end.y - start.y),
    viewportWidth,
    viewportHeight
  };
}

export function ScreenshotSelector({ bounds, preview, busy = false, onComplete, onCancel }: Props) {
  const [start, setStart] = useState<Point | null>(null);
  const [current, setCurrent] = useState<Point | null>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        onCancel();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel, busy]);

  const selection = start && current ? normalizedSelection(start, current, bounds.width, bounds.height) : null;

  function pointer(event: ReactPointerEvent<HTMLDivElement>): Point {
    return {
      x: Math.min(Math.max(event.clientX - bounds.left, 0), bounds.width),
      y: Math.min(Math.max(event.clientY - bounds.top, 0), bounds.height)
    };
  }

  return (
    <div
      className="screenshot-selector"
      data-testid="screenshot-selector"
      style={{ left: bounds.left, top: bounds.top, width: bounds.width, height: bounds.height, backgroundImage: preview ? `url("${preview}")` : undefined, backgroundSize: "100% 100%" }}
      aria-busy={busy}
      onPointerDown={(event) => {
        if (busy) return;
        event.currentTarget.setPointerCapture?.(event.pointerId);
        const point = pointer(event);
        setStart(point);
        setCurrent(point);
      }}
      onPointerMove={(event) => {
        if (start && !busy) {
          setCurrent(pointer(event));
        }
      }}
      onPointerUp={(event) => {
        if (!start || busy) {
          return;
        }
        const result = normalizedSelection(start, pointer(event), bounds.width, bounds.height);
        setStart(null);
        setCurrent(null);
        if (result.width < 24 || result.height < 24) {
          onCancel();
          return;
        }
        onComplete(result);
      }}
    >
      <div className="screenshot-selector-hint" style={{top:16,pointerEvents:"auto",display:"flex",flexWrap:"wrap",justifyContent:"center",whiteSpace:"normal",gap:12,alignItems:"center",maxWidth:"calc(100% - 24px)",boxSizing:"border-box"}}
        onPointerDown={event => event.stopPropagation()} onPointerUp={event => event.stopPropagation()}>
        <span>{busy ? "正在保存地图与资料…" : "框选地图，自动附上图例与来源"}</span>
        <button type="button" className="toolbar-button compact" disabled={busy} onClick={() => onComplete({left:0,top:0,width:bounds.width,height:bounds.height,viewportWidth:bounds.width,viewportHeight:bounds.height})}>截取整个地图</button>
        <button type="button" className="toolbar-button compact" disabled={busy} onClick={onCancel}>取消</button>
      </div>
      {selection ? (
        <div
          className="screenshot-selector-box"
          style={{ left: selection.left, top: selection.top, width: selection.width, height: selection.height }}
        />
      ) : null}
    </div>
  );
}
