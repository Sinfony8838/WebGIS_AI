import { useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent as ReactDragEvent, PointerEvent as ReactPointerEvent } from "react";
import { getSpeechRecognitionConstructor, getSpeechRecognitionErrorMessage, type BrowserSpeechRecognition } from "../speechRecognition";
import type { ChatMessage, ImageAttachment, JobRecord } from "../types";
import { TeachingPet } from "./TeachingPet";

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
  chatLog: ChatMessage[];
  currentJob: JobRecord | null;
  inputValue: string;
  onInputChange: (value: string) => void;
  onSubmit: () => void;
  onQuickPrompt?: (prompt: string) => void;
  onConfirm: (confirmationId: string, decision?: "approve" | "reject") => void;
  onVoiceSubmit: (transcript: string) => void;
  onVoiceNotice: (tone: "info" | "success" | "error", title: string, detail?: string) => void;
  busy: boolean;
  /** Current lesson-workflow phase; drives the header chip and chip ordering. */
  teachingPhase?: "course_prep" | "in_class" | "post_class" | "";
  pendingImage?: ImageAttachment | null;
  onAttachImage?: (image: ImageAttachment) => void;
  onUploadImage?: (file: File) => void;
  onRemoveImage?: () => void;
  openSignal?: number;
};

// One-tap teaching capabilities. Each chip sends a templated prompt that the
// backend router maps to one of the four teaching intents. "读图" only fills
// the composer; the teacher explicitly chooses a screenshot or library image.
// Surfacing these as chips (rather than a sidebar
// button) makes the agent's capabilities visible inside the agent itself.
const CAPABILITY_CHIPS: Array<{ key: string; label: string; prompt: string }> = [
  {
    key: "read-map",
    label: "读图",
    prompt: "请结合我附加的图片进行地理读图分析，说明画面中的主要要素、空间关系和可能成因。"
  },
  {
    key: "follow-up",
    label: "追问",
    prompt: "请围绕当前教学主题设计一组递进式课堂追问，并说明每问的认知层次。"
  },
  {
    key: "reflect",
    label: "复盘",
    prompt: "请对本节课进行小结，指出可强化的区域认知方法与下一步建议。"
  },
  {
    key: "switch-basemap",
    label: "切换底图",
    prompt: "请切换到更适合当前教学目标的底图，并说明选择原因。"
  }
];

// The agent knows which workflow phase it is serving (teaching_context); the
// header chip surfaces that awareness to the teacher, and the capability
// chips are re-ordered so the most phase-relevant action always comes first.
const PHASE_META: Record<string, { label: string; cls: string; chipOrder: string[] }> = {
  course_prep: { label: "课前备课", cls: "phase-prep", chipOrder: ["follow-up", "read-map", "reflect", "switch-basemap"] },
  in_class: { label: "课堂进行中", cls: "phase-class", chipOrder: ["read-map", "follow-up", "switch-basemap", "reflect"] },
  post_class: { label: "课后复盘", cls: "phase-review", chipOrder: ["reflect", "follow-up", "read-map", "switch-basemap"] }
};

// Map the routed intent to a short badge so the teacher can see how the agent
// understood the request - the most compact "agent" signal per message.
const INTENT_BADGES: Record<string, { label: string; cls: string }> = {
  teaching_explain: { label: "讲解", cls: "intent-explain" },
  teaching_question: { label: "追问", cls: "intent-question" },
  teaching_action: { label: "操作", cls: "intent-action" },
  teaching_reflect: { label: "复盘", cls: "intent-reflect" },
  knowledge: { label: "知识", cls: "intent-knowledge" },
  tool: { label: "操作", cls: "intent-action" },
  hybrid: { label: "操作", cls: "intent-action" }
};

function intentBadge(intent?: string | null): { label: string; cls: string } | null {
  if (!intent) {
    return null;
  }
  return INTENT_BADGES[intent] || null;
}

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

const ORB_WIDTH = 96;
const ORB_HEIGHT = 150;
const MIN_WIDTH = 440;
const MIN_HEIGHT = 420;
const PANEL_STORAGE_KEY = "webgis-ai-copilot-panel-v2";
const ORB_STORAGE_KEY = "webgis-ai-copilot-orb-v2";
const STATE_STORAGE_KEY = "webgis-ai-copilot-minimized-v2";
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
    x: Math.max(24, viewportWidth - ORB_WIDTH - 36),
    y: Math.max(140, viewportHeight - ORB_HEIGHT - 120)
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
  const maxX = Math.max(margin, viewportWidth - ORB_WIDTH - margin);
  const maxY = Math.max(margin, viewportHeight - ORB_HEIGHT - margin);
  const distanceToLeft = point.x;
  const distanceToRight = viewportWidth - point.x - ORB_WIDTH;
  const distanceToTop = point.y;
  const distanceToBottom = viewportHeight - point.y - ORB_HEIGHT;
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
    x: clamp(point.x, margin, Math.max(margin, viewportWidth - ORB_WIDTH - margin)),
    y: clamp(point.y, margin, Math.max(margin, viewportHeight - ORB_HEIGHT - margin))
  };
}

function initialVoiceStatus(supported: boolean): VoiceStatus {
  return supported ? "idle" : "unsupported";
}

function initialVoiceText(supported: boolean): string {
  return supported ? VOICE_IDLE_TEXT : VOICE_UNSUPPORTED_TEXT;
}

export function CopilotWidget({
  chatLog,
  currentJob,
  inputValue,
  onInputChange,
  onSubmit,
  onQuickPrompt = () => undefined,
  onConfirm = () => undefined,
  onVoiceSubmit,
  onVoiceNotice,
  busy,
  teachingPhase = "",
  pendingImage = null,
  onAttachImage = () => undefined,
  onUploadImage = () => undefined,
  onRemoveImage = () => undefined,
  openSignal = 0
}: Props) {
  const speechSupported = useMemo(() => Boolean(getSpeechRecognitionConstructor()), []);
  const phaseMeta = teachingPhase ? PHASE_META[teachingPhase] || null : null;
  const orderedChips = useMemo(() => {
    if (!phaseMeta) {
      return CAPABILITY_CHIPS;
    }
    const order = phaseMeta.chipOrder;
    return [...CAPABILITY_CHIPS].sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
  }, [phaseMeta]);
  const [minimized, setMinimized] = useState<boolean>(() =>
    safeWindowWidth() <= 640 ? true : readStorage(STATE_STORAGE_KEY, true)
  );
  const [welcomeToken, setWelcomeToken] = useState(0);
  const [panelRect, setPanelRect] = useState<PanelRect>(() =>
    normalizePanelRect(readStorage<PanelRect | null>(PANEL_STORAGE_KEY, null))
  );
  const [orbPosition, setOrbPosition] = useState<Point>(() =>
    snapOrb(normalizeOrbPosition(readStorage<Point | null>(ORB_STORAGE_KEY, null)))
  );
  const [unreadCount, setUnreadCount] = useState(0);
  const [orbDragging, setOrbDragging] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus>(() => initialVoiceStatus(speechSupported));
  const [voiceStatusText, setVoiceStatusText] = useState<string>(() => initialVoiceText(speechSupported));
  const [lastTranscript, setLastTranscript] = useState("");
  const [expandedTraces, setExpandedTraces] = useState<Record<string, boolean>>({});
  const [imageDragActive, setImageDragActive] = useState(false);
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const preventRestoreOnClickRef = useRef(false);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const manualVoiceStopRef = useRef(false);
  const voiceTranscriptRef = useRef("");
  const voiceErrorRef = useRef(false);

  useEffect(() => {
    if (openSignal > 0) {
      setMinimized(false);
    }
  }, [openSignal]);
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
  const inputPlaceholder = "向专业教学智能体提问 - 例如：讲解当前视图的空间格局，或切换底图并说明原因。";

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (window.innerWidth <= 640) {
      return;
    }
    window.localStorage.setItem(PANEL_STORAGE_KEY, JSON.stringify(panelRect));
  }, [panelRect]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (window.innerWidth <= 640) {
      return;
    }
    window.localStorage.setItem(ORB_STORAGE_KEY, JSON.stringify(orbPosition));
  }, [orbPosition]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (window.innerWidth <= 640) {
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
      if (state.kind === "orb") {
        setOrbDragging(true);
      }
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
        if (state.kind === "orb") {
          setOrbDragging(true);
        }
      }
    }

    if (state.kind === "orb") {
      setOrbPosition((previous) => snapOrb(previous));
      preventRestoreOnClickRef.current = state.moved;
      setOrbDragging(false);
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
      if (window.innerWidth <= 640) {
        return;
      }
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
    if (kind === "orb") {
      setOrbDragging(false);
    }
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
    setWelcomeToken((token) => token + 1);
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

  function handleImageDrop(event: ReactDragEvent<HTMLFormElement>) {
    event.preventDefault();
    setImageDragActive(false);
    if (busy) {
      return;
    }
    const file = event.dataTransfer.files?.[0];
    if (file) {
      onUploadImage(file);
      return;
    }
    const serialized = event.dataTransfer.getData("application/x-webgis-image");
    if (!serialized) {
      return;
    }
    try {
      const image = JSON.parse(serialized) as ImageAttachment;
      if (image.artifact_id && image.public_url) {
        onAttachImage(image);
      }
    } catch {
      // Ignore malformed drag payloads from outside the application.
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
            <TeachingPet
              busy={busy}
              currentJob={currentJob}
              minimized={minimized}
              isListening={isListening}
              size="orb"
              dragging={orbDragging}
              welcomeToken={welcomeToken}
            />
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
            <TeachingPet
              busy={busy}
              currentJob={currentJob}
              minimized={minimized}
              isListening={isListening}
              size="header"
              welcomeToken={welcomeToken}
            />
          </div>
          <div className="copilot-title-copy">
            <h2>专业教学智能体</h2>
            <div className="copilot-header-meta">
              <span className={`status-pill ${busy ? "busy" : "ready"}`}>{busy ? "执行中" : "在线"}</span>
              {phaseMeta ? (
                <span className={`copilot-phase-chip ${phaseMeta.cls}`} data-testid="copilot-phase-chip">
                  {phaseMeta.label}
                </span>
              ) : null}
            </div>
          </div>
        </div>
        <div className="copilot-widget-actions" onPointerDown={(event) => event.stopPropagation()}>
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

          {plannedActions.length ? (
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
            {chatLog.map((message, index) => {
              const body = message.text;
              const badge = message.role === "assistant" ? intentBadge(message.intent) : null;
              const actions = message.actions_executed || [];
              const traceKey = `trace-${index}`;
              const traceOpen = Boolean(expandedTraces[traceKey]);
              return (
                <article key={`${message.timestamp}_${message.role}`} className={`copilot-bubble ${message.role}`}>
                  <span className="copilot-role">
                    {roleLabel(message.role)}
                    {badge ? (
                      <span className={`copilot-intent-badge ${badge.cls}`} data-testid="copilot-intent-badge">
                        {badge.label}
                      </span>
                    ) : null}
                  </span>
                  {message.image_attachment ? (
                    <img
                      className="copilot-message-image"
                      src={message.image_attachment.public_url}
                      alt={message.image_attachment.title || "对话图片"}
                    />
                  ) : null}
                  {body ? <p>{body}</p> : null}
                  {actions.length ? (
                    <div className="copilot-tool-trace" data-testid={`copilot-tool-trace-${index}`}>
                      <button
                        type="button"
                        className="copilot-tool-trace-toggle"
                        onClick={() =>
                          setExpandedTraces((prev) => ({ ...prev, [traceKey]: !prev[traceKey] }))
                        }
                        aria-expanded={traceOpen}
                      >
                        {traceOpen ? "▾" : "▸"} 工具调用 ({actions.length})
                      </button>
                      {traceOpen ? (
                        <ul className="copilot-tool-trace-items">
                          {actions.map((item, idx) => (
                            <li
                              key={`${item.action.tool_name}_${idx}`}
                              className="copilot-tool-trace-item"
                            >
                              <span className="copilot-tool-name">{item.action.tool_name}</span>
                              {item.risk_level ? <em>· 风险 {item.risk_level}</em> : null}
                              <span className="copilot-tool-outcome">{item.result ? "✓" : "·"}</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  ) : null}
                </article>
              );
            })}
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
          className={`copilot-widget-form${imageDragActive ? " image-drag-active" : ""}`}
          onDragEnter={(event) => {
            event.preventDefault();
            if (!busy) setImageDragActive(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
              setImageDragActive(false);
            }
          }}
          onDrop={handleImageDrop}
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <div className="copilot-capability-chips" data-testid="copilot-capability-chips">
            {orderedChips.map((chip) => (
              <button
                key={chip.key}
                type="button"
                className="copilot-capability-chip"
                data-testid={`copilot-chip-${chip.key}`}
                onClick={() => {
                  if (chip.key === "read-map") {
                    onInputChange(chip.prompt);
                    return;
                  }
                  onQuickPrompt(chip.prompt);
                }}
                disabled={busy}
              >
                {chip.label}
              </button>
            ))}
          </div>
          {pendingImage ? (
            <div className="copilot-image-preview" data-testid="copilot-image-preview">
              <img src={pendingImage.public_url} alt={pendingImage.title || "待发送图片"} />
              <div>
                <strong>{pendingImage.title || "待发送图片"}</strong>
                <small>将结合你的问题识别图片内容</small>
              </div>
              <button type="button" onClick={onRemoveImage} aria-label="移除待发送图片">
                ×
              </button>
            </div>
          ) : null}
          <div className="copilot-composer">
            <textarea
              data-testid="copilot-input"
              value={inputValue}
              placeholder={inputPlaceholder}
              onChange={(event) => onInputChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && (inputValue.trim() || pendingImage) && !busy) {
                  event.preventDefault();
                  onSubmit();
                }
              }}
            />
            <div className="copilot-composer-actions">
              <input
                ref={imageInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                className="copilot-image-input"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) onUploadImage(file);
                  event.currentTarget.value = "";
                }}
              />
              <button
                type="button"
                className="copilot-attach-button"
                onClick={() => imageInputRef.current?.click()}
                disabled={busy}
                aria-label="上传图片"
                title="上传图片"
              >
                ＋ 图片
              </button>
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
              <button type="submit" className="copilot-send-button" disabled={busy || (!inputValue.trim() && !pendingImage)}>
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
