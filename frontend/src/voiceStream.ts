/**
 * Streaming microphone capture → local backend ASR over WebSocket.
 *
 * The backend runs sherpa-onnx (streaming Paraformer zh-en) and returns
 * `{"type":"partial"|"final","text"}` JSON events. The browser side only
 * captures audio: getUserMedia → AudioContext → AudioWorklet downsampler
 * (48 kHz float → 16 kHz PCM16, batched into ~128 ms chunks) → binary
 * WebSocket frames. Browsers without AudioWorklet or mic permission fall
 * back to Web Speech via CopilotWidget.
 */

const TARGET_SAMPLE_RATE = 16000;
const CHUNK_SAMPLES = 2048;

const DOWNSAMPLER_WORKLET = `
class PcmDownsampler extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / ${TARGET_SAMPLE_RATE};
    this.acc = 0;
    this.count = 0;
    this.chunk = new Float32Array(${CHUNK_SAMPLES});
    this.chunkPos = 0;
  }
  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const channel = input[0];
    for (let i = 0; i < channel.length; i++) {
      this.acc += channel[i];
      this.count += 1;
      if (this.count >= this.ratio) {
        const sample = Math.max(-1, Math.min(1, this.acc / this.count));
        this.acc = 0;
        this.count = 0;
        this.chunk[this.chunkPos++] = sample;
        if (this.chunkPos >= this.chunk.length) {
          const pcm = new Int16Array(this.chunk.length);
          for (let j = 0; j < this.chunk.length; j++) {
            pcm[j] = this.chunk[j] < 0 ? this.chunk[j] * 0x8000 : this.chunk[j] * 0x7fff;
          }
          this.port.postMessage(pcm, [pcm.buffer]);
          this.chunkPos = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor("pcm-downsampler", PcmDownsampler);
`;

export type VoiceStreamState = "connecting" | "open" | "closed";

export type VoiceStreamEvents = {
  onPartial?: (text: string) => void;
  onFinal?: (text: string) => void;
  onOpen?: () => void;
  onError?: (detail: string) => void;
  onClose?: () => void;
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

export function createVoiceStream(apiBase: string, events: VoiceStreamEvents): Promise<VoiceStreamHandle> {
  return new Promise<VoiceStreamHandle>((resolve, reject) => {
    let state: VoiceStreamState = "connecting";
    let stream: MediaStream | null = null;
    let audioContext: AudioContext | null = null;
    let sourceNode: MediaStreamAudioSourceNode | null = null;
    let workletNode: AudioWorkletNode | null = null;
    let socket: WebSocket | null = null;
    let flushResolver: ((text: string | null) => void) | null = null;

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
      teardown();
      events.onClose?.();
    };

    const handleEvent = (data: string) => {
      let parsed: { type?: string; text?: string };
      try {
        parsed = JSON.parse(data) as { type?: string; text?: string };
      } catch {
        return;
      }
      const text = String(parsed.text || "");
      if (parsed.type === "final") {
        if (flushResolver) {
          flushResolver(text || null);
          flushResolver = null;
        } else {
          events.onFinal?.(text);
        }
      } else if (parsed.type === "partial") {
        events.onPartial?.(text);
      }
    };

    const fail = (detail: string) => {
      if (state === "closed") return;
      finish();
      closeSocket();
      reject(new Error(detail));
    };

    let wsUrl = `${apiBase.replace(/^http/, "ws")}/assistant/voice/stream`;
    const accessToken = new URLSearchParams(typeof location !== "undefined" ? location.search : "").get("access_token");
    if (accessToken) {
      wsUrl += `?access_token=${encodeURIComponent(accessToken)}`;
    }
    socket = new WebSocket(wsUrl);
    socket.binaryType = "arraybuffer";

    socket.onopen = () => {
      void (async () => {
        try {
          if (!audioWorkletSupported()) {
            throw new Error("AudioWorklet not supported");
          }
          stream = await navigator.mediaDevices.getUserMedia({
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
          });
          audioContext = new AudioContext();
          await audioContext.audioWorklet.addModule(
            URL.createObjectURL(new Blob([DOWNSAMPLER_WORKLET], { type: "application/javascript" }))
          );
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
            stop: () =>
              new Promise<string | null>((resolveStop) => {
                if (state === "closed") {
                  resolveStop(null);
                  return;
                }
                flushResolver = resolveStop;
                if (socket && socket.readyState === WebSocket.OPEN) {
                  socket.send("flush");
                }
                // Safety timeout: never leave the caller hanging if the
                // server drops without answering the flush.
                window.setTimeout(() => {
                  if (flushResolver === resolveStop) {
                    flushResolver = null;
                    resolveStop(null);
                    finish();
                    closeSocket();
                  }
                }, 2000);
              }),
            abort: () => {
              flushResolver?.(null);
              flushResolver = null;
              finish();
              closeSocket();
            },
            state: () => state,
          });
        } catch (exc) {
          fail(exc instanceof Error ? exc.message : String(exc));
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
        fail("voice stream connection failed");
      }
    };

    socket.onclose = (event: CloseEvent) => {
      if (state === "connecting") {
        const reason =
          event.code === 4401 ? "unauthorized" : event.code === 4403 ? "voice_asr_unavailable" : "connection closed";
        fail(reason);
        return;
      }
      flushResolver?.(null);
      flushResolver = null;
      finish();
    };
  });
}
