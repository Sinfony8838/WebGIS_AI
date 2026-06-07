import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { getSpeechRecognitionConstructor, getSpeechRecognitionErrorMessage, type BrowserSpeechRecognition } from "../speechRecognition";
import type { AssistantMode, ChatMessage, JobRecord } from "../types";

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

type VoiceStatus = "idle" | "listening" | "unsupported";

type Props = {
  assistantMode: AssistantMode;
  chatLog: ChatMessage[];
  currentJob: JobRecord | null;
  inputValue: string;
  onInputChange: (value: string) => void;
  onAssistantModeChange: (mode: AssistantMode) => void;
  onSubmit: () => void;
  onConfirm: (confirmationId: string, decision?: "approve" | "reject") => void;
  onVoiceSubmit: (transcript: string) => void;
  onVoiceNotice: (tone: "info" | "success" | "error", title: string, detail?: string) => void;
  busy: boolean;
};

// Map workflow / assistant-v2 stage keys to short, human-friendly status
// verbs used by the inline "AI 正在思考…" indicator. Anything not listed
// falls back to the generic ``正在思考…`` so the UI never leaks raw keys.
const stageVerbs: Record<string, string> = {
  // Assistant V2 stages
  routing: "正在理解你的问题",
  retrieval: "正在检索知识库",
  planning: "正在规划操作",
  confirmation: "等待你的确认",
  execution: "正在执行操作",
  grounding: "正在整合答复",
  artifacts: "正在整理结果",
  // Legacy workflow stages (v1.1)
  analysis: "正在解析意图",
  actions: "正在执行动作",
  map: "正在同步地图"
};

function pickThinkingLabel(stages: Array<[string, { status: string; summary?: string }]>): string {
  const running = stages.find(([, stage]) => stage.status === "running");
  if (running) {
    return stageVerbs[running[0]] || "正在思考";
  }
  return "正在思考";
}

/**
 * Shared face artwork used in both the collapsed orb and the expanded
 * header avatar. Same DOM, identical class structure — the only
 * difference is the class prefix, which scopes the sizing rules in
 * styles.css. This keeps the assistant character visually identical
 * across states.
 */
function AssistantFace({ variant }: { variant: "orb" | "avatar" }) {
  const prefix = variant === "orb" ? "copilot-orb" : "copilot-avatar";
  return (
    <>
      <span className={`${prefix}-ear left`} aria-hidden="true" />
      <span className={`${prefix}-ear right`} aria-hidden="true" />
      <span className={`${prefix}-face`}>
        <span className={`${prefix}-sheen`} aria-hidden="true" />
        <span className={`${prefix}-mouth`} aria-hidden="true" />
        <span className={`${prefix}-blush left`} aria-hidden="true" />
        <span className={`${prefix}-blush right`} aria-hidden="true" />
        <span className={`${prefix}-pulse`} aria-hidden="true" />
      </span>
    </>
  );
}

function roleLabel(role: string): string {
  if (role === "assistant") {
    return "助教";
  }
  if (role === "user") {
    return "教师";
  }
  return "系统";
}

function MicrophoneIcon({ active }: { active: boolean }) {
  if (active) {
    // Active state: filled square indicates "stop"
    return (
      <svg
        className="copilot-voice-icon"
        viewBox="0 0 16 16"
        width="14"
        height="14"
        aria-hidden="true"
        focusable="false"
      >
        <rect x="3.5" y="3.5" width="9" height="9" rx="1.5" fill="currentColor" />
      </svg>
    );
  }
  return (
    <svg
      className="copilot-voice-icon"
      viewBox="0 0 16 16"
      width="14"
      height="14"
      aria-hidden="true"
      focusable="false"
    >
      {/* Capsule body */}
      <rect x="6" y="2" width="4" height="7.5" rx="2" fill="currentColor" />
      {/* Stand arc */}
      <path
        d="M3.75 8 V8.75 a4.25 4.25 0 0 0 8.5 0 V8"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinecap="round"
      />
      {/* Neck + base */}
      <line x1="8" y1="13" x2="8" y2="14" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
      <line x1="6" y1="14" x2="10" y2="14" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
    </svg>
  );
}

const ORB_SIZE = 72;
const MIN_WIDTH = 440;
const MIN_HEIGHT = 420;
const PANEL_STORAGE_KEY = "webgis-ai-copilot-panel";
const ORB_STORAGE_KEY = "webgis-ai-copilot-orb";
const STATE_STORAGE_KEY = "webgis-ai-copilot-minimized";
const VOICE_IDLE_TEXT = "点击麦克风开始语音控制。";
const VOICE_UNSUPPORTED_TEXT = "当前浏览器不支持语音控制，请使用桌面版 Chrome 或 Edge。";

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

function initialVoiceStatus(supported: boolean): VoiceStatus {
  return supported ? "idle" : "unsupported";
}

function initialVoiceText(supported: boolean): string {
  return supported ? VOICE_IDLE_TEXT : VOICE_UNSUPPORTED_TEXT;
}

export function CopilotWidget({
  assistantMode = "tool",
  chatLog,
  currentJob,
  inputValue,
  onInputChange,
  onAssistantModeChange = () => undefined,
  onSubmit,
  onConfirm = () => undefined,
  onVoiceSubmit,
  onVoiceNotice,
  busy
}: Props) {
  const speechSupported = useMemo(() => Boolean(getSpeechRecognitionConstructor()), []);
  const [minimized, setMinimized] = useState<boolean>(() => readStorage(STATE_STORAGE_KEY, false));
  const [panelRect, setPanelRect] = useState<PanelRect>(() =>
    normalizePanelRect(readStorage<PanelRect | null>(PANEL_STORAGE_KEY, null))
  );
  const [orbPosition, setOrbPosition] = useState<Point>(() =>
    snapOrb(normalizeOrbPosition(readStorage<Point | null>(ORB_STORAGE_KEY, null)))
  );
  const [unreadCount, setUnreadCount] = useState(0);
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus>(() => initialVoiceStatus(speechSupported));
  const [voiceStatusText, setVoiceStatusText] = useState<string>(() => initialVoiceText(speechSupported));
  const [lastTranscript, setLastTranscript] = useState("");
  const preventRestoreOnClickRef = useRef(false);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const manualVoiceStopRef = useRef(false);
  const voiceTranscriptRef = useRef("");
  const voiceErrorRef = useRef(false);
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
  const isListening = voiceStatus === "listening";
  const citations = currentJob?.result?.citations || currentJob?.result?.knowledge?.citations || [];
  const plannedActions = currentJob?.result?.actions_planned || [];
  const confirmationId = String(currentJob?.result?.confirmation_id || "");
  const requiresConfirmation = Boolean(currentJob?.result?.requires_confirmation && confirmationId);
  const compactLayout = panelRect.height < 560 || panelRect.width < 560;

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

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
      recognitionRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!busy || !recognitionRef.current) {
      return;
    }
    manualVoiceStopRef.current = true;
    setVoiceStatusText("当前有任务在执行，语音输入已停止。");
    recognitionRef.current.stop();
  }, [busy]);

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

  function stopVoiceRecognition(manualStop = true) {
    if (!recognitionRef.current) {
      return;
    }
    manualVoiceStopRef.current = manualStop;
    recognitionRef.current.stop();
  }

  function handleVoiceToggle() {
    if (isListening) {
      setVoiceStatusText("语音输入已停止。");
      stopVoiceRecognition(true);
      return;
    }

    const RecognitionConstructor = getSpeechRecognitionConstructor();
    if (!RecognitionConstructor) {
      setVoiceStatus("unsupported");
      setVoiceStatusText(VOICE_UNSUPPORTED_TEXT);
      onVoiceNotice("error", "当前浏览器不支持语音控制", "请使用桌面版 Chrome 或 Edge 进行课堂演示。");
      return;
    }

    const recognition = new RecognitionConstructor();
    recognition.lang = "zh-CN";
    recognition.continuous = false;
    recognition.interimResults = false;
    voiceTranscriptRef.current = "";
    voiceErrorRef.current = false;
    manualVoiceStopRef.current = false;

    recognition.onresult = (event) => {
      const results = Array.from(event.results || []);
      const transcript = results
        .slice(event.resultIndex || 0)
        .filter((item) => item?.isFinal)
        .map((item) => item[0]?.transcript || "")
        .join("")
        .trim();

      if (!transcript) {
        return;
      }

      voiceTranscriptRef.current = transcript;
      recognition.stop();
    };

    recognition.onerror = (event) => {
      voiceErrorRef.current = true;
      const { title, detail } = getSpeechRecognitionErrorMessage(event.error);
      setVoiceStatus(speechSupported ? "idle" : "unsupported");
      setVoiceStatusText(detail);
      onVoiceNotice("error", title, detail);
    };

    recognition.onend = () => {
      const transcript = voiceTranscriptRef.current.trim();
      const stoppedManually = manualVoiceStopRef.current;
      const hadError = voiceErrorRef.current;
      recognitionRef.current = null;
      voiceTranscriptRef.current = "";
      manualVoiceStopRef.current = false;
      voiceErrorRef.current = false;
      setVoiceStatus(speechSupported ? "idle" : "unsupported");

      if (transcript) {
        setLastTranscript(transcript);
        setVoiceStatusText("语音识别完成，已提交课堂指令。");
        onVoiceSubmit(transcript);
        return;
      }

      if (hadError) {
        return;
      }

      if (stoppedManually) {
        return;
      }

      const detail = "没有识别到有效语音，请点击麦克风后直接说出课堂指令。";
      setVoiceStatusText(detail);
      onVoiceNotice("error", "没有识别到语音", detail);
    };

    try {
      recognitionRef.current = recognition;
      setVoiceStatus("listening");
      setVoiceStatusText("正在聆听课堂指令，请开始说话。");
      recognition.start();
    } catch (error) {
      recognitionRef.current = null;
      setVoiceStatus(speechSupported ? "idle" : "unsupported");
      setVoiceStatusText("浏览器没有成功启动语音识别，请重试一次。");
      onVoiceNotice("error", "语音识别失败", error instanceof Error ? error.message : "浏览器没有成功启动语音识别。");
    }
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
            <AssistantFace variant="orb" />
          </span>
          <span className="copilot-orb-label">助教</span>
          {unreadCount ? <span className="copilot-unread">{unreadCount}</span> : null}
        </button>
      </div>
    );
  }

  return (
    <section
      className={`copilot-widget${compactLayout ? " compact" : ""}`}
      style={{ left: panelRect.x, top: panelRect.y, width: panelRect.width, height: panelRect.height }}
    >
      <header className="copilot-widget-header" onPointerDown={(event) => startDrag("panel", event, panelRect)}>
        <div className="copilot-header-identity">
          <div className={`copilot-avatar ${busy ? "busy" : ""}`} aria-hidden="true">
            <AssistantFace variant="avatar" />
          </div>
          <div className="copilot-title-copy">
            <p className="copilot-eyebrow">AI Teaching Assistant</p>
            <h2>智能助教</h2>
          </div>
        </div>
        <div className="copilot-widget-actions" onPointerDown={(event) => event.stopPropagation()}>
          <span className={`status-pill ${busy ? "busy" : "ready"}`}>{busy ? "执行中" : "在线"}</span>
          <button
            type="button"
            className="mini-control copilot-collapse"
            onClick={() => setMinimized(true)}
            aria-label="最小化助教"
            title="最小化"
          >
            <span aria-hidden="true">−</span>
          </button>
        </div>
        <div
          className="assistant-mode-switch"
          role="tablist"
          aria-label="assistant mode"
          onPointerDown={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            role="tab"
            aria-selected={assistantMode === "knowledge"}
            className={`assistant-mode-chip ${assistantMode === "knowledge" ? "active" : ""}`}
            onClick={() => onAssistantModeChange("knowledge")}
          >
            知识助手
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={assistantMode === "tool"}
            className={`assistant-mode-chip ${assistantMode === "tool" ? "active" : ""}`}
            onClick={() => onAssistantModeChange("tool")}
          >
            工具助手
          </button>
        </div>
      </header>

      <div className="copilot-widget-body">
        <div className="copilot-widget-content">
          {requiresConfirmation ? (
            <div className="copilot-confirm-card" role="alert">
              <strong>高风险操作待确认</strong>
              <span>该计划未确认前不会执行。</span>
              <div className="copilot-confirm-actions">
                <button type="button" onClick={() => onConfirm(confirmationId, "approve")} disabled={busy}>
                  确认执行
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onConfirm(confirmationId, "reject")}
                  disabled={busy}
                >
                  拒绝计划
                </button>
              </div>
            </div>
          ) : null}

          {assistantMode === "tool" && plannedActions.length ? (
            <div className="copilot-plan-card">
              <strong>计划摘要</strong>
              {plannedActions.slice(0, 3).map((item) => (
                <span key={`${item.name}_${JSON.stringify(item.tool_params)}`}>
                  {item.name} <em>· 风险 {item.risk_level}</em>
                </span>
              ))}
            </div>
          ) : null}

          {citations.length ? (
            <div className="copilot-citation-list">
              <strong>引用来源</strong>
              {citations.map((item) => (
                <a key={`${item.title}_${item.url}`} href={item.url} target="_blank" rel="noreferrer">
                  {item.title}
                </a>
              ))}
            </div>
          ) : null}

          <div className="copilot-chat-log" data-testid="copilot-chat-log">
            {chatLog.map((message) => (
              <article key={`${message.timestamp}_${message.role}`} className={`copilot-bubble ${message.role}`}>
                <span className="copilot-role">{roleLabel(message.role)}</span>
                <p>{message.text}</p>
              </article>
            ))}
            {busy ? (
              <div
                className="copilot-thinking"
                role="status"
                aria-live="polite"
                data-testid="copilot-thinking"
              >
                <span className="copilot-thinking-dots" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </span>
                <span className="copilot-thinking-label">{pickThinkingLabel(jobStages)}</span>
              </div>
            ) : null}
          </div>
        </div>

        <form
          className="copilot-widget-form"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <div className="copilot-composer">
            <textarea
              data-testid="copilot-input"
              value={inputValue}
              placeholder="向智能助教提问 — 例如：解释当前视图的空间格局，或说明所选区域的区位特征。"
              onChange={(event) => onInputChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && inputValue.trim() && !busy) {
                  event.preventDefault();
                  onSubmit();
                }
              }}
            />
            <div className="copilot-composer-actions">
              <button
                type="button"
                className={`copilot-voice-button ${isListening ? "listening" : ""}`}
                aria-label={isListening ? "停止语音控制" : "开始语音控制"}
                title={isListening ? "停止语音" : speechSupported ? "语音输入" : "当前浏览器不支持语音"}
                onClick={handleVoiceToggle}
                disabled={busy || (!speechSupported && !isListening)}
              >
                <MicrophoneIcon active={isListening} />
                <span className="copilot-voice-label">{isListening ? "停止语音" : "麦克风"}</span>
              </button>
              <span className="copilot-composer-hint" aria-hidden="true">
                ⌘ / Ctrl + Enter 发送
              </span>
              <button type="submit" className="copilot-send-button" disabled={busy || !inputValue.trim()}>
                发送给助教
              </button>
            </div>
          </div>
          {voiceStatusText ? (
            <p className={`copilot-voice-status ${voiceStatus}`} role="status">
              {voiceStatusText}
            </p>
          ) : null}
          {lastTranscript ? <p className="copilot-voice-transcript">最近转写：{lastTranscript}</p> : null}
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
