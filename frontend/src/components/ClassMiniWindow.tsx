import { useEffect, useRef, useState, type ReactNode } from "react";

type Props = {
  title: string;
  onClose: () => void;
  /** 关闭按钮的提示语（小窗承载投屏题时说明题目仍在进行）。 */
  closeTitle?: string;
  children: ReactNode;
};

const STORAGE_KEY = "class-mini-window-position";
const VIEWPORT_MARGIN = 8;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function readStoredPosition(): { left: number; top: number } | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { left?: unknown; top?: unknown };
    if (typeof parsed.left !== "number" || typeof parsed.top !== "number") return null;
    if (!Number.isFinite(parsed.left) || !Number.isFinite(parsed.top)) return null;
    return { left: parsed.left, top: parsed.top };
  } catch {
    return null;
  }
}

/**
 * 课堂小窗：可拖拽悬浮卡。位置记忆在 localStorage；首次出现停靠在右下角，
 * 拖拽后按最终位置记忆。拖拽只认标题栏，正文保持可交互。
 */
export function ClassMiniWindow({ title, onClose, closeTitle = "收起课堂小窗", children }: Props) {
  const frameRef = useRef<HTMLElement | null>(null);
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(readStoredPosition);

  useEffect(() => {
    if (!position) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(position));
    } catch {
      /* localStorage 不可用（隐私模式等）时位置仅在本次会话内生效。 */
    }
  }, [position]);

  function startDrag(event: React.PointerEvent<HTMLDivElement>) {
    const frame = frameRef.current;
    if (!frame || event.button !== 0) return;
    const rect = frame.getBoundingClientRect();
    setPosition((previous) => previous || { left: rect.left, top: rect.top });
    dragRef.current = { dx: event.clientX - rect.left, dy: event.clientY - rect.top };
    try {
      frame.setPointerCapture(event.pointerId);
    } catch {
      /* 环境不支持指针捕获时，依靠 window 级事件流继续拖拽。 */
    }
  }

  function moveDrag(event: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    const frame = frameRef.current;
    if (!drag || !frame) return;
    const width = frame.offsetWidth;
    const height = frame.offsetHeight;
    setPosition({
      left: clamp(event.clientX - drag.dx, VIEWPORT_MARGIN, Math.max(VIEWPORT_MARGIN, window.innerWidth - width - VIEWPORT_MARGIN)),
      top: clamp(event.clientY - drag.dy, VIEWPORT_MARGIN, Math.max(VIEWPORT_MARGIN, window.innerHeight - height - VIEWPORT_MARGIN))
    });
  }

  function endDrag(event: React.PointerEvent<HTMLDivElement>) {
    dragRef.current = null;
    const frame = frameRef.current;
    if (frame?.hasPointerCapture?.(event.pointerId)) {
      frame.releasePointerCapture(event.pointerId);
    }
  }

  return (
    <section
      ref={frameRef}
      className="class-mini-window glass-panel"
      data-testid="class-mini-window"
      style={position ? { left: position.left, top: position.top, right: "auto", bottom: "auto" } : undefined}
    >
      <header
        className="class-mini-window-head"
        onPointerDown={startDrag}
        onPointerMove={moveDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <span className="class-mini-window-title">{title}</span>
        <button
          type="button"
          className="mini-control"
          onClick={onClose}
          aria-label="收起课堂小窗"
          title={closeTitle}
          data-testid="class-mini-window-close"
        >
          ×
        </button>
      </header>
      <div className="class-mini-window-body">{children}</div>
    </section>
  );
}
