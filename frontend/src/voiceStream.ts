/**
 * Streaming microphone capture → local backend ASR over WebSocket.
 *
 * The backend runs sherpa-onnx (streaming Paraformer zh-en) and returns
 * `{"type":"partial"|"final","text"}` JSON events. The browser side only
 * captures audio: getUserMedia → AudioContext (pinned to 16 kHz so the
 * browser itself resamples 44.1/48 kHz input; the worklet downsampler with
 * fractional phase-carry is the safety net for engines that ignore the
 * rate hint) → PCM16, batched into ~128 ms chunks → binary WebSocket
 * frames. Browsers without AudioWorklet or mic permission fall back to
 * Web Speech via CopilotWidget.
 *
 * Reliability contract (consumed by voiceSession.ts):
 * - failures surface as typed {@link VoiceStreamError}s with actionable
 *   Chinese messages (permission denied / no device / timeout / ASR down);
 * - the server can reject the stream with a JSON error event before
 *   closing (4403), reported via onServerError + onClose;
 * - `stop()` flushes exactly once, aborts cleanly, and never leaves the
 *   mic track or the WebSocket behind.
 */
import { buildDownsamplerWorkletSource, TARGET_SAMPLE_RATE } from "./voiceResampler";

const CONNECT_TIMEOUT_MS = 8000;
const FLUSH_TIMEOUT_MS = 2000;

export type VoiceStreamState = "connecting" | "open" | "closed";

export type VoiceStreamErrorKind =
  | "permission_denied"
  | "no_device"
  | "connect_timeout"
  | "unauthorized"
  | "asr_unavailable"
  | "audio_worklet_unsupported"
  | "connection_failed"
  | "unknown";

const ERROR_MESSAGES: Record<VoiceStreamErrorKind, string> = {
  permission_denied: "麦克风权限被拒绝。请在浏览器地址栏的权限设置中允许麦克风，然后点击重试。",
  no_device: "没有检测到可用麦克风。请连接或选择录音设备后重试。",
  connect_timeout: "连接本地语音识别服务超时，请确认后端已启动后重试。",
  unauthorized: "登录状态已失效，请重新登录后再使用语音。",
  asr_unavailable: "本地语音识别不可用（模型未就绪）。可在服务端运行 scripts/download_voice_models.py，或改用文字输入。",
  audio_worklet_unsupported: "当前浏览器不支持音频采集（AudioWorklet），请使用桌面版 Chrome 或 Edge。",
  connection_failed: "本地语音识别连接中断。",
  unknown: "语音识别出现未知错误，可重试或改用文字输入。"
};

export class VoiceStreamError extends Error {
  readonly kind: VoiceStreamErrorKind;

  constructor(kind: VoiceStreamErrorKind, message?: string) {
    super(message || ERROR_MESSAGES[kind]);
    this.name = "VoiceStreamError";
    this.kind = kind;
  }
}

export type VoiceStreamCloseInfo = { code: number; reason: string };

export type VoiceStreamEvents = {
  onPartial?: (text: string) => void;
  onFinal?: (text: string) => void;
  onOpen?: () => void;
  /** Fatal setup/transport failure (typed, with an actionable message). */
  onError?: (error: VoiceStreamError) => void;
  /** Server refused the stream (JSON error event before a 4403 close). */
  onServerError?: (payload: { reason: string; detail?: string }) => void;
  onClose?: (info: VoiceStreamCloseInfo) => void;
};

export type VoiceStreamHandle = {
  /** Flush pending audio (server returns a final transcript) and close. */
  stop: () => Promise<string | null>;
  /** Close immediately without waiting for a final transcript. */
  abort: () => void;
  state: () => VoiceStreamState;
};

type WindowWithAudioWorklet = Window &
  typeof globalThis & {
    AudioWorkletNode?: typeof AudioWorkletNode;
  };

export function audioWorkletSupported(targetWindow: Window & typeof globalThis = window): boolean {
  return typeof (targetWindow as WindowWithAudioWorklet).AudioWorkletNode === "function";
}

function mapMediaError(exc: unknown): VoiceStreamError {
  const name = exc instanceof DOMException ? exc.name : exc instanceof Error ? exc.name : "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") {
    return new VoiceStreamError("permission_denied");
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError") {
    return new VoiceStreamError("no_device");
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return new VoiceStreamError("no_device", "麦克风被其他应用占用或无法读取，请关闭占用它的程序后重试。");
  }
  return new VoiceStreamError("unknown", exc instanceof Error ? exc.message : String(exc));
}

export function createVoiceStream(apiBase: string, events: VoiceStreamEvents): Promise<VoiceStreamHandle> {
  return new Promise<VoiceStreamHandle>((resolve, reject) => {
    let state: VoiceStreamState = "connecting";
    let stream: MediaStream | null = null;
    let audioContext: AudioContext | null = null;
    let sourceNode: MediaStreamAudioSourceNode | null = null;
    let workletNode: AudioWorkletNode | null = null;
    let socket: WebSocket | null = null;
    let flushResolver: ((text: string | null) => void) | null = null;
    let flushTimer: number | null = null;
    let connectTimer: number | null = null;
    let stopPromise: Promise<string | null> | null = null;
    let closeInfo: VoiceStreamCloseInfo = { code: 0, reason: "" };

    const teardown = () => {
      try {
        workletNode?.disconnect();
      } catch {
        /* already disconnected */
      }
      try {
        sourceNode?.disconnect();
      } catch {
        /* already disconnected */
      }
      void audioContext?.close().catch(() => undefined);
      stream?.getTracks().forEach((track) => track.stop());
      audioContext = null;
      sourceNode = null;
      workletNode = null;
      stream = null;
    };

    const closeSocket = () => {
      if (socket && socket.readyState <= WebSocket.OPEN) {
        socket.close();
      }
      socket = null;
    };

    const finish = () => {
      if (state === "closed") return;
      state = "closed";
      if (connectTimer !== null) {
        window.clearTimeout(connectTimer);
        connectTimer = null;
      }
      if (flushTimer !== null) {
        window.clearTimeout(flushTimer);
        flushTimer = null;
      }
      flushResolver?.(null);
      flushResolver = null;
      teardown();
      events.onClose?.(closeInfo);
    };

    const handleEvent = (data: string) => {
      let parsed: { type?: string; text?: string; reason?: string; detail?: string } | null = null;
      try {
        parsed = JSON.parse(data) as { type?: string; text?: string; reason?: string; detail?: string };
      } catch {
        return;
      }
      if (!parsed || typeof parsed !== "object" || state === "closed") return;
      const text = String(parsed.text || "");
      if (parsed.type === "final") {
        if (flushResolver) {
          flushResolver(text || null);
          flushResolver = null;
          finish();
          closeSocket();
        } else {
          events.onFinal?.(text);
        }
      } else if (parsed.type === "partial") {
        events.onPartial?.(text);
      } else if (parsed.type === "error") {
        events.onServerError?.({ reason: String(parsed.reason || "unavailable"), detail: String(parsed.detail || "") });
      }
    };

    const fail = (error: VoiceStreamError) => {
      if (state === "closed") return;
      closeInfo = { code: 0, reason: error.kind };
      finish();
      closeSocket();
      reject(error);
    };

    let wsUrl = `${apiBase.replace(/^http/, "ws")}/assistant/voice/stream`;
    const accessToken = new URLSearchParams(typeof location !== "undefined" ? location.search : "").get("access_token");
    if (accessToken) {
      wsUrl += `?access_token=${encodeURIComponent(accessToken)}`;
    }
    socket = new WebSocket(wsUrl);
    socket.binaryType = "arraybuffer";

    // Covers "backend down / wrong port / firewall". The mic permission
    // prompt is allowed to take longer: this timer is cleared once the
    // socket opens, before getUserMedia runs.
    connectTimer = window.setTimeout(() => {
      fail(new VoiceStreamError("connect_timeout"));
    }, CONNECT_TIMEOUT_MS);

    socket.onopen = () => {
      if (connectTimer !== null) {
        window.clearTimeout(connectTimer);
        connectTimer = null;
      }
      void (async () => {
        try {
          if (!audioWorkletSupported()) {
            throw new VoiceStreamError("audio_worklet_unsupported");
          }
          stream = await navigator.mediaDevices.getUserMedia({
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
          });
          // The socket can close while the permission prompt is still open.
          if (state === "closed") {
            teardown();
            return;
          }
          // Pin the context to 16 kHz: Chromium resamples the mic stream
          // natively, so 44.1/48 kHz hardware input becomes exact 16 kHz
          // here. If an engine ignores the hint, the worklet's fractional
          // resampler below still produces true 16 kHz output.
          audioContext = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
          const moduleUrl = URL.createObjectURL(new Blob([buildDownsamplerWorkletSource()], { type: "application/javascript" }));
          try {
            await audioContext.audioWorklet.addModule(moduleUrl);
          } finally {
            URL.revokeObjectURL(moduleUrl);
          }
          if ((state as VoiceStreamState) === "closed") return;
          sourceNode = audioContext.createMediaStreamSource(stream);
          workletNode = new AudioWorkletNode(audioContext, "pcm-downsampler");
          workletNode.port.onmessage = (event: MessageEvent<Int16Array>) => {
            if (socket && socket.readyState === WebSocket.OPEN && event.data) {
              socket.send(event.data);
            }
          };
          sourceNode.connect(workletNode);
          // Deliberately not connected to destination: no local playback.
          state = "open";
          events.onOpen?.();
          resolve({
            stop: () => {
              if (stopPromise) return stopPromise;
              stopPromise = new Promise<string | null>((resolveStop) => {
                if (state === "closed") {
                  resolveStop(null);
                  return;
                }
                teardown();
                flushResolver = resolveStop;
                if (socket && socket.readyState === WebSocket.OPEN) {
                  socket.send("flush");
                }
                // Safety timeout: never leave the caller hanging if the
                // server drops without answering the flush.
                flushTimer = window.setTimeout(() => {
                  if (flushResolver === resolveStop) {
                    flushResolver = null;
                    resolveStop(null);
                    finish();
                    closeSocket();
                  }
                }, FLUSH_TIMEOUT_MS);
              });
              return stopPromise;
            },
            abort: () => {
              flushResolver?.(null);
              flushResolver = null;
              finish();
              closeSocket();
            },
            state: () => state,
          });
        } catch (exc) {
          fail(exc instanceof VoiceStreamError ? exc : mapMediaError(exc));
        }
      })();
    };

    socket.onmessage = (event: MessageEvent) => {
      if (typeof event.data === "string") {
        handleEvent(event.data);
      }
    };

    socket.onerror = () => {
      if (state === "connecting") {
        fail(new VoiceStreamError("connection_failed"));
      }
    };

    socket.onclose = (event: CloseEvent) => {
      closeInfo = { code: event.code, reason: event.reason || "" };
      if (state === "connecting") {
        const kind: VoiceStreamErrorKind =
          event.code === 4401 ? "unauthorized" : event.code === 4403 ? "asr_unavailable" : "connection_failed";
        fail(new VoiceStreamError(kind));
        return;
      }
      flushResolver?.(null);
      flushResolver = null;
      finish();
    };
  });
}
