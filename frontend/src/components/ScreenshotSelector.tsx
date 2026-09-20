import { useEffect, useState } from "react";
import type { DragEvent as ReactDragEvent, PointerEvent as ReactPointerEvent } from "react";

export type ScreenshotSelection = {
  left: number;
  top: number;
  width: number;
  height: number;
  viewportWidth: number;
  viewportHeight: number;
};

export type ScreenshotDestination = "assistant" | "database";
type Point = { x: number; y: number };

type Props = {
  bounds: { left: number; top: number; width: number; height: number };
  preview?: string;
  busy?: boolean;
  onSaveLocal: (selection: ScreenshotSelection) => void;
  onDestination: (destination: ScreenshotDestination, selection: ScreenshotSelection) => void;
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

export function ScreenshotSelector({ bounds, preview, busy = false, onSaveLocal, onDestination, onCancel }: Props) {
  const [start, setStart] = useState<Point | null>(null);
  const [current, setCurrent] = useState<Point | null>(null);
  const [lockedSelection, setLockedSelection] = useState<ScreenshotSelection | null>(null);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel, busy]);

  const drawingSelection = start && current ? normalizedSelection(start, current, bounds.width, bounds.height) : null;
  const selection = drawingSelection || lockedSelection;

  function pointer(event: ReactPointerEvent<HTMLDivElement>): Point {
    return {
      x: Math.min(Math.max(event.clientX - bounds.left, 0), bounds.width),
      y: Math.min(Math.max(event.clientY - bounds.top, 0), bounds.height)
    };
  }

  function useFullPage(): void {
    setError("");
    setLockedSelection({ left: 0, top: 0, width: bounds.width, height: bounds.height, viewportWidth: bounds.width, viewportHeight: bounds.height });
  }

  function handleDrop(destination: ScreenshotDestination, event: ReactDragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setDragging(false);
    if (!busy && lockedSelection && event.dataTransfer.getData("application/x-webgis-screenshot-draft")) {
      onDestination(destination, lockedSelection);
    }
  }

  return (
    <div
      className={`screenshot-selector${lockedSelection ? " is-selected" : ""}${dragging ? " is-dragging" : ""}`}
      data-testid="screenshot-selector"
      style={{ left: bounds.left, top: bounds.top, width: bounds.width, height: bounds.height, backgroundImage: preview ? `url("${preview}")` : undefined, backgroundSize: "100% 100%" }}
      aria-busy={busy}
      onPointerDown={(event) => {
        if (busy) return;
        event.currentTarget.setPointerCapture?.(event.pointerId);
        const point = pointer(event);
        setError("");
        setLockedSelection(null);
        setStart(point);
        setCurrent(point);
      }}
      onPointerMove={(event) => {
        if (start && !busy) setCurrent(pointer(event));
      }}
      onPointerUp={(event) => {
        if (!start || busy) return;
        const result = normalizedSelection(start, pointer(event), bounds.width, bounds.height);
        setStart(null);
        setCurrent(null);
        if (result.width < 24 || result.height < 24) {
          setError("范围过小，请重新框选。");
          return;
        }
        setLockedSelection(result);
      }}
    >
      <div className="screenshot-selector-hint" onPointerDown={(event) => event.stopPropagation()} onPointerUp={(event) => event.stopPropagation()}>
        <span>{busy ? "正在处理截图…" : lockedSelection ? `已选择 ${Math.round(lockedSelection.width)} × ${Math.round(lockedSelection.height)}` : "拖动框选当前 WebGIS 页面"}</span>
        {error ? <strong role="alert">{error}</strong> : null}
        {!lockedSelection ? <button type="button" className="toolbar-button compact" disabled={busy} onClick={useFullPage}>选择整个页面</button> : null}
        {lockedSelection ? (
          <>
            <button type="button" className="toolbar-button compact primary" disabled={busy} onClick={() => onSaveLocal(lockedSelection)}>保存 PNG</button>
            <button type="button" className="toolbar-button compact" disabled={busy} onClick={() => setLockedSelection(null)}>重新框选</button>
          </>
        ) : null}
        <button type="button" className="toolbar-button compact" disabled={busy} onClick={onCancel}>取消</button>
      </div>

      {selection ? <div className="screenshot-selector-box" style={{ left: selection.left, top: selection.top, width: selection.width, height: selection.height }} /> : null}

      {lockedSelection ? (
        <div className="screenshot-destination-tray" onPointerDown={(event) => event.stopPropagation()} onPointerUp={(event) => event.stopPropagation()}>
          <button
            type="button"
            className="screenshot-drag-source"
            draggable={!busy}
            disabled={busy}
            onDragStart={(event) => {
              event.dataTransfer.setData("application/x-webgis-screenshot-draft", "selected");
              event.dataTransfer.effectAllowed = "copy";
              setDragging(true);
            }}
            onDragEnd={() => setDragging(false)}
          >
            拖动选区到右侧
          </button>
          <div className="screenshot-drop-target" data-testid="screenshot-drop-assistant" onDragOver={(event) => event.preventDefault()} onDrop={(event) => handleDrop("assistant", event)}>智能助教</div>
          <div className="screenshot-drop-target" data-testid="screenshot-drop-database" onDragOver={(event) => event.preventDefault()} onDrop={(event) => handleDrop("database", event)}>数据库</div>
        </div>
      ) : null}
    </div>
  );
}
