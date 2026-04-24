import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import type { ChatMessage, JobRecord } from "../types";

type PanelRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

type Point = {
  x: number;
  y: number;
};

type Props = {
  chatLog: ChatMessage[];
  currentJob: JobRecord | null;
  inputValue: string;
  onInputChange: (value: string) => void;
  onSubmit: () => void;
  busy: boolean;
};

const stageLabels: Record<string, string> = {
  analysis: "意图解析",
  actions: "动作执行",
  map: "地图同步",
  artifacts: "产物登记"
};

const ORB_SIZE = 72;
const MIN_WIDTH = 440;
const MIN_HEIGHT = 420;
const PANEL_STORAGE_KEY = "webgis-ai-copilot-panel";
const ORB_STORAGE_KEY = "webgis-ai-copilot-orb";
const STATE_STORAGE_KEY = "webgis-ai-copilot-minimized";

function safeWindowWidth(): number {
  return typeof window === "undefined" ? 1440 : window.innerWidth;
}

function safeWindowHeight(): number {
  return typeof window === "undefined" ? 900 : window.innerHeight;
}

function defaultPanelRect(): PanelRect {
  const viewportWidth = safeWindowWidth();
  const viewportHeight = safeWindowHeight();
  return {
    x: Math.max(24, viewportWidth - 476),
    y: Math.max(96, viewportHeight - 580),
    width: 440,
    height: 520
  };
}

function defaultOrbPosition(): Point {
  const viewportWidth = safeWindowWidth();
  const viewportHeight = safeWindowHeight();
  return {
    x: Math.max(24, viewportWidth - ORB_SIZE - 36),
    y: Math.max(140, viewportHeight - ORB_SIZE - 120)
  };
}

function readStorage<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") {
    return fallback;
  }
  const raw = window.localStorage.getItem(key);
  if (!raw) {
    return fallback;
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function resolvePointerPosition(event: { clientX: number; clientY: number }): Point | null {
  if (!isFiniteNumber(event.clientX) || !isFiniteNumber(event.clientY)) {
    return null;
  }
  return { x: event.clientX, y: event.clientY };
}

export function exceedsDragThreshold(start: Point, end: Point): boolean {
  return Math.abs(end.x - start.x) > 4 || Math.abs(end.y - start.y) > 4;
}

function clampPanel(rect: PanelRect): PanelRect {
  const viewportWidth = safeWindowWidth();
  const viewportHeight = safeWindowHeight();
  const width = clamp(rect.width, MIN_WIDTH, Math.max(MIN_WIDTH, viewportWidth - 24));
  const height = clamp(rect.height, MIN_HEIGHT, Math.max(MIN_HEIGHT, viewportHeight - 24));
  return {
    width,
    height,
    x: clamp(rect.x, 8, Math.max(8, viewportWidth - width - 8)),
    y: clamp(rect.y, 8, Math.max(8, viewportHeight - height - 8))
  };
}

export function normalizePanelRect(candidate: unknown): PanelRect {
  const fallback = defaultPanelRect();
  if (
    !candidate ||
    typeof candidate !== "object" ||
    !isFiniteNumber((candidate as Partial<PanelRect>).x) ||
    !isFiniteNumber((candidate as Partial<PanelRect>).y) ||
    !isFiniteNumber((candidate as Partial<PanelRect>).width) ||
    !isFiniteNumber((candidate as Partial<PanelRect>).height)
  ) {
    return clampPanel(fallback);
  }

  return clampPanel({
    x: (candidate as PanelRect).x,
    y: (candidate as PanelRect).y,
    width: (candidate as PanelRect).width,
    height: (candidate as PanelRect).height
  });
}

function snapOrb(point: Point): Point {
  const viewportWidth = safeWindowWidth();
  const viewportHeight = safeWindowHeight();
  const margin = 14;
  const maxX = Math.max(margin, viewportWidth - ORB_SIZE - margin);
  const maxY = Math.max(margin, viewportHeight - ORB_SIZE - margin);
  const distanceToLeft = point.x;
  const distanceToRight = viewportWidth - point.x - ORB_SIZE;
  const distanceToTop = point.y;
  const distanceToBottom = viewportHeight - point.y - ORB_SIZE;
  const nearestDistance = Math.min(distanceToLeft, distanceToRight, distanceToTop, distanceToBottom);

  if (nearestDistance === distanceToLeft) {
    return { x: margin, y: clamp(point.y, margin, maxY) };
  }
  if (nearestDistance === distanceToRight) {
    return { x: maxX, y: clamp(point.y, margin, maxY) };
  }
  if (nearestDistance === distanceToTop) {
    return { x: clamp(point.x, margin, maxX), y: margin };
  }
  return { x: clamp(point.x, margin, maxX), y: maxY };
}

export function normalizeOrbPosition(candidate: unknown): Point {
  const fallback = defaultOrbPosition();
  if (
    !candidate ||
    typeof candidate !== "object" ||
    !isFiniteNumber((candidate as Partial<Point>).x) ||
    !isFiniteNumber((candidate as Partial<Point>).y)
  ) {
    return snapOrb(fallback);
  }

  return snaplessOrb({
    x: (candidate as Point).x,
    y: (candidate as Point).y
  });
}

function snaplessOrb(point: Point): Point {
  const viewportWidth = safeWindowWidth();
  const viewportHeight = safeWindowHeight();
  const margin = 14;
  return {
    x: clamp(point.x, margin, Math.max(margin, viewportWidth - ORB_SIZE - margin)),
    y: clamp(point.y, margin, Math.max(margin, viewportHeight - ORB_SIZE - margin))
  };
}

export function CopilotWidget({ chatLog, currentJob, inputValue, onInputChange, onSubmit, busy }: Props) {
  const [minimized, setMinimized] = useState<boolean>(() => readStorage(STATE_STORAGE_KEY, false));
  const [panelRect, setPanelRect] = useState<PanelRect>(() =>
    normalizePanelRect(readStorage<PanelRect | null>(PANEL_STORAGE_KEY, null))
  );
  const [orbPosition, setOrbPosition] = useState<Point>(() =>
    snapOrb(normalizeOrbPosition(readStorage<Point | null>(ORB_STORAGE_KEY, null)))
  );
  const [unreadCount, setUnreadCount] = useState(0);
  const preventRestoreOnClickRef = useRef(false);
  const dragStateRef = useRef<
    | {
        kind: "orb" | "panel" | "resize";
        startX: number;
        startY: number;
        originX: number;
        originY: number;
        originWidth: number;
        originHeight: number;
        moved: boolean;
      }
    | null
  >(null);
  const lastSeenMessages = useRef(chatLog.length);

  const jobStages = useMemo(() => (currentJob ? Object.entries(currentJob.stages) : []), [currentJob]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(PANEL_STORAGE_KEY, JSON.stringify(panelRect));
  }, [panelRect]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(ORB_STORAGE_KEY, JSON.stringify(orbPosition));
  }, [orbPosition]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(STATE_STORAGE_KEY, JSON.stringify(minimized));
  }, [minimized]);

  useEffect(() => {
    if (chatLog.length <= lastSeenMessages.current) {
      return;
    }
    if (minimized) {
      setUnreadCount((count) => count + (chatLog.length - lastSeenMessages.current));
    } else {
      setUnreadCount(0);
    }
    lastSeenMessages.current = chatLog.length;
  }, [chatLog.length, minimized]);

  function updateDrag(pointer: Point) {
    const state = dragStateRef.current;
    if (!state) {
      return;
    }

    if (!state.moved && exceedsDragThreshold({ x: state.startX, y: state.startY }, pointer)) {
      state.moved = true;
    }

    if (state.kind === "orb") {
      setOrbPosition(
        snaplessOrb({
          x: state.originX + (pointer.x - state.startX),
          y: state.originY + (pointer.y - state.startY)
        })
      );
      return;
    }

    if (state.kind === "panel") {
      setPanelRect((previous) =>
        clampPanel({
          ...previous,
          x: state.originX + (pointer.x - state.startX),
          y: state.originY + (pointer.y - state.startY)
        })
      );
      return;
    }

    setPanelRect(
      clampPanel({
        x: state.originX,
        y: state.originY,
        width: state.originWidth + (pointer.x - state.startX),
        height: state.originHeight + (pointer.y - state.startY)
      })
    );
  }

  function finishDrag(pointer?: Point | null) {
    const state = dragStateRef.current;
    if (!state) {
      return;
    }

    if (pointer) {
      if (!state.moved && exceedsDragThreshold({ x: state.startX, y: state.startY }, pointer)) {
        state.moved = true;
      }
    }

    if (state.kind === "orb") {
      setOrbPosition((previous) => snapOrb(previous));
      preventRestoreOnClickRef.current = state.moved;
    }

    dragStateRef.current = null;
  }

  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      const state = dragStateRef.current;
      if (!state || state.kind === "orb") {
        return;
      }

      const pointer = resolvePointerPosition(event);
      if (!pointer) {
        return;
      }
      updateDrag(pointer);
    };

    const handlePointerUp = (event: PointerEvent) => {
      const state = dragStateRef.current;
      if (!state || state.kind === "orb") {
        return;
      }
      finishDrag(resolvePointerPosition(event));
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
  }, []);

  useEffect(() => {
    const handleResize = () => {
      setPanelRect((previous) => normalizePanelRect(previous));
      setOrbPosition((previous) => snapOrb(normalizeOrbPosition(previous)));
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  function startDrag(kind: "orb" | "panel" | "resize", event: ReactPointerEvent, rect?: PanelRect | Point) {
    event.preventDefault();
    const baseRect = rect || (kind === "orb" ? orbPosition : panelRect);
    const panelCandidate = baseRect as Partial<PanelRect>;
    dragStateRef.current = {
      kind,
      startX: event.clientX,
      startY: event.clientY,
      originX: baseRect.x,
      originY: baseRect.y,
      originWidth: typeof panelCandidate.width === "number" ? panelCandidate.width : panelRect.width,
      originHeight: typeof panelCandidate.height === "number" ? panelCandidate.height : panelRect.height,
      moved: false
    };
  }

  function restorePanel() {
    preventRestoreOnClickRef.current = false;
    setUnreadCount(0);
    setPanelRect((previous) => normalizePanelRect(previous));
    setMinimized(false);
  }

  if (minimized) {
    return (
      <div className="copilot-orb-shell" style={{ left: orbPosition.x, top: orbPosition.y }}>
        <button
          type="button"
          className={`copilot-orb ${busy ? "busy" : ""}`}
          aria-label="展开智能助教"
          onClick={() => {
            if (preventRestoreOnClickRef.current) {
              preventRestoreOnClickRef.current = false;
              return;
            }
            restorePanel();
          }}
          onPointerDown={(event) => {
            event.stopPropagation();
            event.currentTarget.setPointerCapture?.(event.pointerId);
            startDrag("orb", event, orbPosition);
          }}
          onPointerMove={(event) => {
            if (dragStateRef.current?.kind !== "orb") {
              return;
            }
            const pointer = resolvePointerPosition(event);
            if (!pointer) {
              return;
            }
            event.stopPropagation();
            updateDrag(pointer);
          }}
          onPointerUp={(event) => {
            if (dragStateRef.current?.kind !== "orb") {
              return;
            }
            event.stopPropagation();
            event.currentTarget.releasePointerCapture?.(event.pointerId);
            finishDrag(resolvePointerPosition(event));
          }}
          onPointerCancel={(event) => {
            if (dragStateRef.current?.kind !== "orb") {
              return;
            }
            event.stopPropagation();
            finishDrag(resolvePointerPosition(event));
          }}
        >
          <span className="copilot-orb-body">
            <span className="copilot-orb-ear left" />
            <span className="copilot-orb-ear right" />
            <span className="copilot-orb-face">
              <span className="copilot-orb-sheen" />
              <span className="copilot-orb-mouth" />
              <span className="copilot-orb-blush left" />
              <span className="copilot-orb-blush right" />
              <span className="copilot-orb-pulse" />
            </span>
          </span>
          <span className="copilot-orb-label">助教</span>
          {unreadCount ? <span className="copilot-unread">{unreadCount}</span> : null}
        </button>
      </div>
    );
  }

  return (
    <section className="copilot-widget" style={{ left: panelRect.x, top: panelRect.y, width: panelRect.width, height: panelRect.height }}>
      <header className="copilot-widget-header" onPointerDown={(event) => startDrag("panel", event, panelRect)}>
        <div className="copilot-widget-title">
          <div className="copilot-avatar">
            <span className="copilot-avatar-ear left" />
            <span className="copilot-avatar-ear right" />
            <span className="copilot-avatar-face">
              <span className="copilot-avatar-mouth" />
            </span>
          </div>
          <p className="panel-tag">Classroom Copilot</p>
          <div>
            <h2>智能助教</h2>
            <span>{busy ? "正在同步课堂动作与图层状态。" : "地图副驾已就绪，可继续提问或触发任务。"}</span>
          </div>
        </div>
        <div className="copilot-widget-actions">
          <span className={`status-pill ${busy ? "busy" : "ready"}`}>{busy ? "执行中" : "在线"}</span>
          <button type="button" className="mini-control" onClick={() => setMinimized(true)} aria-label="最小化助教">
            −
          </button>
        </div>
      </header>

      <div className="copilot-widget-body">
        {jobStages.length ? (
          <div className="copilot-stage-strip">
            {jobStages.map(([key, stage]) => (
              <div key={key} className={`copilot-stage ${stage.status || "pending"}`}>
                <strong>{stageLabels[key] || key}</strong>
                <span>{stage.summary || "等待中"}</span>
              </div>
            ))}
          </div>
        ) : null}

        <div className="copilot-chat-log" data-testid="copilot-chat-log">
          {chatLog.map((message) => (
            <article key={`${message.timestamp}_${message.role}`} className={`copilot-bubble ${message.role}`}>
              <span className="copilot-role">
                {message.role === "assistant" ? "助教" : message.role === "user" ? "教师" : "系统"}
              </span>
              <p>{message.text}</p>
            </article>
          ))}
        </div>

        <form
          className="copilot-widget-form"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <textarea
            data-testid="copilot-input"
            value={inputValue}
            placeholder="例如：解释当前视图的空间格局，或说明所选区域的区位特征。"
            onChange={(event) => onInputChange(event.target.value)}
          />
          <button type="submit" disabled={busy || !inputValue.trim()}>
            发送给助教
          </button>
        </form>
      </div>

      <button
        type="button"
        className="copilot-resize-handle"
        aria-label="调整助教窗口大小"
        onPointerDown={(event) => startDrag("resize", event, panelRect)}
      />
    </section>
  );
}
