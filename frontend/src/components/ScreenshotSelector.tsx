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

export function ScreenshotSelector({ bounds, onComplete, onCancel }: Props) {
  const [start, setStart] = useState<Point | null>(null);
  const [current, setCurrent] = useState<Point | null>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onCancel();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

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
      style={{ left: bounds.left, top: bounds.top, width: bounds.width, height: bounds.height }}
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture?.(event.pointerId);
        const point = pointer(event);
        setStart(point);
        setCurrent(point);
      }}
      onPointerMove={(event) => {
        if (start) {
          setCurrent(pointer(event));
        }
      }}
      onPointerUp={(event) => {
        if (!start) {
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
      <div className="screenshot-selector-hint">拖动框选截图范围 · Esc 取消</div>
      {selection ? (
        <div
          className="screenshot-selector-box"
          style={{ left: selection.left, top: selection.top, width: selection.width, height: selection.height }}
        />
      ) : null}
    </div>
  );
}
