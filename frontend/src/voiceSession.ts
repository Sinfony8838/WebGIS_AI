/**
 * Unified lifecycle controller for the always-listening voice session in
 * 智能交互 mode (默认聆听).
 *
 * One controller owns the single live capture session. Everything that used
 * to be scattered across CopilotWidget effects (常开 stream, busy pause, TTS
 * wait, visibility guard) funnels through here so the invariants hold in one
 * place:
 *
 * - Entering 智能交互 starts listening automatically (first use triggers the
 *   normal browser permission prompt; afterwards entry listens immediately).
 *   The 「进入时自动聆听」 setting is latched at entry; when off, the session
 *   starts user-paused instead of silently capturing.
 * - Exactly one WebSocket/mic session exists; every callback carries an
 *   epoch token so results from a torn-down session are dropped.
 * - A final transcript is submitted at most once. Results that arrive while
 *   a job is executing or an announcement is playing are stale and dropped.
 * - Capture pauses (stream aborted, no flush) while a command executes or
 *   the assistant speaks, so the system never hears itself; after real TTS
 *   end/error events — not a fixed delay — capture resumes.
 * - Manual pause survives re-renders and health refreshes; leaving the tab,
 *   hiding the page or losing window focus pauses, and returning follows the
 *   user's settings (re-entering the tab re-enables by default).
 * - Disconnects reconnect with bounded backoff (3 attempts). Permission
 *   denial, missing ASR backend and unsupported browsers surface as
 *   actionable 「识别不可用」 states with a retry entry — never an endless
 *   retry loop.
 */
import { createVoiceStream, VoiceStreamError, type VoiceStreamHandle } from "./voiceStream";
import { describeScreenRejection, screenTranscript, type GateMode } from "./voiceGate";
import { onSpeechLifecycle } from "./speechSynthesis";

export type VoicePhase =
  | "idle"
  | "awaiting_permission"
  | "connecting"
  | "listening"
  | "captured"
  | "executing"
  | "speaking"
  | "paused"
  | "unavailable";

export type UnavailableKind =
  | "unsupported_browser"
  | "asr_unavailable"
  | "permission_denied"
  | "no_device"
  | "unauthorized"
  | "connection_failed";

export const UNAVAILABLE_MESSAGES: Record<UnavailableKind, string> = {
  unsupported_browser: "当前浏览器不支持语音采集，请使用桌面版 Chrome 或 Edge，或改用文字输入。",
  asr_unavailable: "本地语音识别服务未就绪。请在服务端运行 scripts/download_voice_models.py 并重启后端，或改用文字输入。",
  permission_denied: "麦克风权限被拒绝。请在浏览器地址栏允许麦克风后点击重试，或改用文字输入。",
  no_device: "没有检测到可用麦克风。请连接录音设备后点击重试，或改用文字输入。",
  unauthorized: "登录状态已失效，请重新登录后再使用语音。",
  connection_failed: "本地语音识别连接失败。请确认后端已启动后点击重试，或改用文字输入。"
};

export type VoiceSessionSettings = {
  /** 进入智能交互时自动开始聆听（默认开）。 */
  autoListenOnEnter: boolean;
  /** 仅唤醒后执行：说「小智，+指令」才响应（嘈杂课堂用）。 */
  requireWakeWord: boolean;
};

export type VoiceSessionSnapshot = {
  phase: VoicePhase;
  /** Extra context for the status line (reason, attempt count, last command). */
  detail: string;
  partial: string;
  ignoredCount: number;
};

export type VoiceSessionCallbacks = {
  onSnapshot: (snapshot: VoiceSessionSnapshot) => void;
  /** A gated, de-duplicated command ready for the assistant. */
  onSubmitCommand: (command: string) => void;
  onPartial?: (text: string) => void;
  onListeningChange?: (listening: boolean) => void;
  onCapturedCommand?: (command: string) => void;
  onNotice?: (tone: "info" | "error", title: string, detail: string) => void;
};

export type VoiceSessionOptions = {
  apiBase: () => string;
  callbacks: VoiceSessionCallbacks;
  audioWorkletSupported?: () => boolean;
  /** Wall clock hook (ms); injectable for deterministic tests. */
  now?: () => number;
};

const RESUME_DELAY_MS = 400;
const RECONNECT_DELAYS_MS = [1000, 2000, 4000];
/** Two identical finals within this window count as one utterance. */
const DUPLICATE_FINAL_WINDOW_MS = 2000;
/** How long the 「已识别」 phase stays visible before reverting to listening. */
const CAPTURED_VISIBLE_MS = 1500;
/** After submitting, wait for busy to latch before accepting more finals. */
const AWAITING_BUSY_WINDOW_MS = 2500;

export class VoiceSessionController {
  private readonly options: VoiceSessionOptions;
  private settings: VoiceSessionSettings = { autoListenOnEnter: true, requireWakeWord: false };

  private interactionActive = false;
  private userPaused = false;
  private busy = false;
  private speaking = false;
  private docHidden = false;
  private windowBlurred = false;
  private asrAvailable = true;
  private asrDetail = "";

  private epoch = 0;
  private handle: VoiceStreamHandle | null = null;
  private phase: VoicePhase = "idle";
  private phaseDetail = "";
  private unavailableKind: UnavailableKind | null = null;
  private partial = "";
  private ignoredCount = 0;
  private reconnectAttempt = 0;
  private resumeTimer: number | null = null;
  private capturedTimer: number | null = null;
  private capturedUntil = 0;
  private awaitingBusyUntil = 0;
  private lastSubmittedText = "";
  private lastSubmittedAt = 0;
  private listening = false;
  private disposed = false;
  private unsubscribeSpeech: () => void;

  constructor(options: VoiceSessionOptions) {
    this.options = options;
    this.unsubscribeSpeech = onSpeechLifecycle(({ speaking }) => this.setSpeaking(speaking));
  }

  // ------------------------------------------------------------------
  // External inputs
  // ------------------------------------------------------------------

  /** Enter 智能交互: latch the auto-listen setting and start (default on). */
  enterInteraction(): void {
    if (this.disposed || this.interactionActive) return;
    this.interactionActive = true;
    this.userPaused = !this.settings.autoListenOnEnter;
    this.unavailableKind = null;
    this.ignoredCount = 0;
    this.reconnectAttempt = 0;
    this.recompute();
  }

  exitInteraction(): void {
    if (!this.interactionActive) return;
    this.interactionActive = false;
    this.userPaused = false;
    this.teardownStream();
    this.cancelTimers();
    this.unavailableKind = null;
    this.setListening(false);
    this.phase = "idle";
    this.phaseDetail = "";
    this.emit();
  }

  /** Bottom mic button: 暂停聆听 / 恢复聆听. */
  togglePaused(): void {
    if (this.disposed || !this.interactionActive) return;
    this.userPaused = !this.userPaused;
    if (!this.userPaused) {
      this.unavailableKind = null;
      this.reconnectAttempt = 0;
    }
    this.recompute();
  }

  isUserPaused(): boolean {
    return this.userPaused;
  }

  setSettings(patch: Partial<VoiceSessionSettings>): void {
    this.settings = { ...this.settings, ...patch };
    // Changing settings mid-session must not silently start or stop capture;
    // autoListenOnEnter applies the next time the tab is entered.
    this.emit();
  }

  settingsValue(): VoiceSessionSettings {
    return { ...this.settings };
  }

  setBusy(busy: boolean): void {
    if (this.busy === busy) return;
    this.busy = busy;
    if (!busy) {
      this.awaitingBusyUntil = 0;
    }
    this.recompute();
  }

  setSpeaking(speaking: boolean): void {
    if (this.speaking === speaking) return;
    this.speaking = speaking;
    this.recompute();
  }

  setDocumentHidden(hidden: boolean): void {
    if (this.docHidden === hidden) return;
    this.docHidden = hidden;
    this.recompute();
  }

  setWindowFocused(focused: boolean): void {
    if (this.windowBlurred === !focused) return;
    this.windowBlurred = !focused;
    this.recompute();
  }

  /** Health refresh: whether the backend local ASR route is usable. */
  setAsrAvailability(available: boolean, detail = ""): void {
    this.asrDetail = detail;
    if (this.asrAvailable === available) {
      this.emit();
      return;
    }
    this.asrAvailable = available;
    if (available) {
      this.unavailableKind = null;
      this.reconnectAttempt = 0;
    }
    this.recompute();
  }

  /** Manual retry from the 识别不可用 state. */
  retry(): void {
    if (this.disposed || !this.interactionActive) return;
    this.unavailableKind = null;
    this.reconnectAttempt = 0;
    // A retry is an explicit user action: it also clears a manual pause.
    this.userPaused = false;
    // Health is only sampled at page load; a retry must re-probe the backend
    // for real. Optimistically mark it available — if the backend is still
    // down, the connection attempt fails with the precise reason (4403 state)
    // and the unavailable state returns with that detail.
    this.asrAvailable = true;
    this.recompute();
  }

  dispose(): void {
    this.disposed = true;
    this.unsubscribeSpeech();
    this.teardownStream();
    this.cancelTimers();
    this.interactionActive = false;
    this.setListening(false);
  }

  snapshot(): VoiceSessionSnapshot {
    return {
      phase: this.phase,
      detail: this.phaseDetail,
      partial: this.partial,
      ignoredCount: this.ignoredCount
    };
  }

  // ------------------------------------------------------------------
  // Core transitions
  // ------------------------------------------------------------------

  private shouldListen(): boolean {
    return (
      this.interactionActive &&
      !this.userPaused &&
      !this.busy &&
      !this.speaking &&
      !this.docHidden &&
      !this.windowBlurred &&
      this.asrAvailable &&
      (this.options.audioWorkletSupported?.() ?? true)
    );
  }

  private recompute(): void {
    if (this.disposed) return;
    if (!this.interactionActive) {
      if (this.handle || this.phase !== "idle") {
        this.teardownStream();
        this.cancelTimers();
        this.setListening(false);
        this.phase = "idle";
        this.phaseDetail = "";
        this.emit();
      }
      return;
    }

    if (this.unavailableKind) {
      this.teardownStream();
      this.cancelTimers();
      this.setListening(false);
      this.phase = "unavailable";
      this.phaseDetail = UNAVAILABLE_MESSAGES[this.unavailableKind];
      this.emit();
      return;
    }

    if (!this.asrAvailable) {
      this.teardownStream();
      this.cancelTimers();
      this.setListening(false);
      this.phase = "unavailable";
      this.phaseDetail = this.asrDetail || UNAVAILABLE_MESSAGES.asr_unavailable;
      this.emit();
      return;
    }

    if (!(this.options.audioWorkletSupported?.() ?? true)) {
      this.unavailableKind = "unsupported_browser";
      this.phase = "unavailable";
      this.phaseDetail = UNAVAILABLE_MESSAGES.unsupported_browser;
      this.setListening(false);
      this.emit();
      return;
    }

    if (this.speaking) {
      this.teardownStream();
      this.cancelTimers();
      this.setListening(false);
      this.phase = "speaking";
      this.phaseDetail = "";
      this.emit();
      return;
    }

    if (this.busy) {
      this.teardownStream();
      this.cancelTimers();
      this.setListening(false);
      this.phase = "executing";
      this.phaseDetail = "";
      this.emit();
      return;
    }

    if (this.userPaused || this.docHidden || this.windowBlurred) {
      this.teardownStream();
      this.cancelTimers();
      this.setListening(false);
      this.phase = "paused";
      this.phaseDetail = this.userPaused ? "已暂停聆听，点击麦克风恢复。" : "";
      this.emit();
      return;
    }

    // Everything is clear: keep the live stream listening (unless the
    // transient 已识别 phase is still showing), or (re)start capture after a
    // short settle delay so a just-started announcement can still flip
    // `speaking` before the mic opens (prevents the system hearing itself).
    if (this.handle) {
      const now = this.options.now?.() ?? Date.now();
      if (!(this.phase === "captured" && now < this.capturedUntil) && this.phase !== "listening") {
        this.phase = "listening";
        this.phaseDetail = "";
        this.setListening(true);
        this.emit();
      }
      return;
    }
    this.scheduleStart();
  }

  private scheduleStart(): void {
    if (this.resumeTimer !== null) return;
    const delay = this.reconnectAttempt > 0 ? RECONNECT_DELAYS_MS[Math.min(this.reconnectAttempt - 1, RECONNECT_DELAYS_MS.length - 1)] : RESUME_DELAY_MS;
    if (this.reconnectAttempt > 0) {
      this.phase = "connecting";
      this.phaseDetail = `正在重新连接（第 ${this.reconnectAttempt}/${RECONNECT_DELAYS_MS.length} 次）…`;
      this.emit();
    }
    this.resumeTimer = window.setTimeout(() => {
      this.resumeTimer = null;
      if (this.shouldListen() && !this.handle) {
        void this.startStream();
      } else {
        this.recompute();
      }
    }, delay);
  }

  private async startStream(): Promise<void> {
    if (this.disposed || this.handle) return;
    const myEpoch = ++this.epoch;
    this.partial = "";
    this.phase = "connecting";
    this.phaseDetail = "";

    // Distinguish a first-use permission prompt from a plain reconnect so
    // the status line can say 等待授权 instead of 正在连接.
    let permissionState = "granted";
    try {
      const status = await navigator.permissions?.query({ name: "microphone" as PermissionName });
      permissionState = status?.state || "granted";
    } catch {
      /* Permissions API unavailable (older browser / test env) */
    }
    if (myEpoch !== this.epoch) return;
    if (permissionState === "denied") {
      this.unavailableKind = "permission_denied";
      this.recompute();
      return;
    }
    if (permissionState === "prompt") {
      this.phase = "awaiting_permission";
      this.phaseDetail = "浏览器正在请求麦克风权限，请在弹窗中允许。";
      this.emit();
    }

    try {
      const handle = await createVoiceStream(this.options.apiBase(), {
        onOpen: () => {
          if (myEpoch !== this.epoch || this.disposed) return;
          this.reconnectAttempt = 0;
          this.phase = "listening";
          this.phaseDetail = "";
          this.setListening(true);
          this.emit();
        },
        onPartial: (text) => {
          if (myEpoch !== this.epoch) return;
          this.partial = text;
          this.options.callbacks.onPartial?.(text);
          if (this.phase === "listening") this.emit();
        },
        onFinal: (text) => this.handleFinal(text, myEpoch),
        onServerError: (payload) => {
          if (myEpoch !== this.epoch) return;
          this.phaseDetail = payload.detail || payload.reason;
        },
        onClose: (info) => {
          if (myEpoch !== this.epoch) return;
          this.handle = null;
          this.setListening(false);
          if (info.code === 4401) {
            this.unavailableKind = "unauthorized";
          } else if (info.code === 4403) {
            this.unavailableKind = "asr_unavailable";
          } else if (this.shouldListen()) {
            this.scheduleReconnect();
            return;
          }
          this.recompute();
        }
      });
      if (myEpoch !== this.epoch || this.disposed || !this.shouldListen()) {
        // The user paused / a job started / the tab closed while the
        // connection and permission were still being set up.
        handle.abort();
        return;
      }
      this.handle = handle;
      // The stream may already be open; if onOpen fired before this line the
      // phase is listening and we leave it alone.
      if (this.phase === "connecting" || this.phase === "awaiting_permission") {
        this.phase = this.phase === "awaiting_permission" ? "awaiting_permission" : "connecting";
        this.emit();
      }
    } catch (error) {
      if (myEpoch !== this.epoch || this.disposed) return;
      this.handle = null;
      this.setListening(false);
      const kind = error instanceof VoiceStreamError ? error.kind : "unknown";
      const message = error instanceof Error ? error.message : String(error);
      if (kind === "permission_denied") {
        this.unavailableKind = "permission_denied";
      } else if (kind === "no_device") {
        this.unavailableKind = "no_device";
      } else if (kind === "unauthorized") {
        this.unavailableKind = "unauthorized";
      } else if (kind === "asr_unavailable") {
        this.unavailableKind = "asr_unavailable";
      } else if (kind === "audio_worklet_unsupported") {
        this.unavailableKind = "unsupported_browser";
      } else if (this.reconnectAttempt < RECONNECT_DELAYS_MS.length) {
        this.reconnectAttempt += 1;
        if (this.shouldListen()) {
          this.scheduleStart();
          this.options.callbacks.onNotice?.("info", "语音连接中断", `${message}，正在重试（${this.reconnectAttempt}/${RECONNECT_DELAYS_MS.length}）。`);
          return;
        }
      } else {
        this.unavailableKind = "connection_failed";
        this.options.callbacks.onNotice?.("error", "语音连接失败", message);
      }
      this.recompute();
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempt >= RECONNECT_DELAYS_MS.length) {
      this.unavailableKind = "connection_failed";
      this.options.callbacks.onNotice?.("error", "语音连接断开", "本地语音识别连接多次重试失败，请检查后端服务后点击重试。");
      this.recompute();
      return;
    }
    this.reconnectAttempt += 1;
    this.scheduleStart();
  }

  private handleFinal(text: string, myEpoch: number): void {
    if (myEpoch !== this.epoch) return; // stale session's result
    const clean = text.trim();
    if (!clean) return;
    if (this.busy || this.speaking) {
      // A result surfacing during execution/announcement is an old leftover.
      this.ignoredCount += 1;
      return;
    }
    const now = this.options.now?.() ?? Date.now();
    if (clean === this.lastSubmittedText && now - this.lastSubmittedAt < DUPLICATE_FINAL_WINDOW_MS) {
      return; // duplicate delivery of the same utterance
    }
    if (now < this.awaitingBusyUntil) {
      this.ignoredCount += 1; // a second final before busy latched: stale burst
      return;
    }

    const mode: GateMode = this.settings.requireWakeWord ? "wake_word" : "direct";
    const gate = screenTranscript(clean, { mode });
    if (!gate.accepted) {
      this.ignoredCount += 1;
      this.partial = "";
      this.options.callbacks.onPartial?.("");
      this.phaseDetail = describeScreenRejection(gate.reason);
      this.emit();
      return;
    }

    this.lastSubmittedText = gate.command;
    this.lastSubmittedAt = now;
    this.capturedUntil = now + CAPTURED_VISIBLE_MS;
    this.awaitingBusyUntil = now + AWAITING_BUSY_WINDOW_MS;
    this.partial = "";
    this.options.callbacks.onPartial?.("");
    this.options.callbacks.onCapturedCommand?.(gate.command);
    this.phase = "captured";
    this.phaseDetail = gate.command;
    this.emit();
    this.options.callbacks.onSubmitCommand(gate.command);
    // busy flips via setBusy; until then keep ignoring burst finals. When
    // the transient 已识别 display expires, fall back to the real phase.
    if (this.capturedTimer !== null) window.clearTimeout(this.capturedTimer);
    this.capturedTimer = window.setTimeout(() => {
      this.capturedTimer = null;
      this.recompute();
    }, CAPTURED_VISIBLE_MS);
  }

  private teardownStream(): void {
    if (!this.handle) {
      this.partial = "";
      return;
    }
    // Invalidate every callback of the discarded session before closing it.
    this.epoch += 1;
    this.handle.abort();
    this.handle = null;
    this.partial = "";
  }

  private cancelTimers(): void {
    if (this.resumeTimer !== null) {
      window.clearTimeout(this.resumeTimer);
      this.resumeTimer = null;
    }
    if (this.capturedTimer !== null) {
      window.clearTimeout(this.capturedTimer);
      this.capturedTimer = null;
    }
  }

  private setListening(listening: boolean): void {
    if (this.listening === listening) return;
    this.listening = listening;
    this.options.callbacks.onListeningChange?.(listening);
  }

  private emit(): void {
    this.options.callbacks.onSnapshot(this.snapshot());
  }
}
