/**
 * Browser TTS for voice-initiated assistant turns (智能交互语音播报).
 *
 * zh-CN utterance, markdown stripped before speaking, and a `cancel()` so a
 * new command can interrupt the previous announcement (barge-in). Falls back
 * to a no-op when the browser has no speechSynthesis or no Chinese voice is
 * available — the text answer is always on screen anyway.
 *
 * The voice session must resume listening the moment playback actually
 * ends (and never resume while it is still running), so `speak` exposes
 * real start/end/error events plus a module-level lifecycle broadcast that
 * App.tsx and voiceSession.ts subscribe to. A hard timeout guards against
 * browsers that never fire the end event, replacing the old fixed-delay
 * wait that could resume the mic too early or mute it for ages.
 */

const SPEAK_LANG = "zh-CN";
/** No real announcement runs longer than this; guards hung utterances. */
const SPEAK_HARD_LIMIT_MS = 30_000;

export type SpeechHandlers = {
  onStart?: () => void;
  onEnd?: () => void;
  onError?: () => void;
};

type LifecycleListener = (state: { speaking: boolean }) => void;

const lifecycleListeners = new Set<LifecycleListener>();

/** Subscribe to playback start/end (used to pause/resume mic capture). */
export function onSpeechLifecycle(listener: LifecycleListener): () => void {
  lifecycleListeners.add(listener);
  return () => {
    lifecycleListeners.delete(listener);
  };
}

function notifyLifecycle(speaking: boolean): void {
  lifecycleListeners.forEach((listener) => {
    try {
      listener({ speaking });
    } catch {
      /* listener errors must not break speech */
    }
  });
}

function stripMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*_~#>|]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function speechSynthesisSupported(targetWindow: Window & typeof globalThis = window): boolean {
  return typeof targetWindow.speechSynthesis !== "undefined" && typeof SpeechSynthesisUtterance !== "undefined";
}

// Incremented by every speak()/cancelSpeech(); events from a superseded
// utterance are dropped so a cancelled announcement never un-pauses the mic.
let generation = 0;

/** Speak text in Chinese; cancels anything already queued. */
export function speak(text: string, handlers?: SpeechHandlers): void {
  if (!speechSynthesisSupported()) {
    handlers?.onError?.();
    return;
  }
  const clean = stripMarkdown(String(text || ""));
  if (!clean) {
    handlers?.onEnd?.();
    return;
  }
  const synth = window.speechSynthesis;
  synth.cancel();
  const myGeneration = ++generation;
  let settled = false;

  const settle = (outcome: "end" | "error") => {
    if (settled) return;
    settled = true;
    if (hardLimitTimer !== null) {
      window.clearTimeout(hardLimitTimer);
      hardLimitTimer = null;
    }
    if (myGeneration !== generation) return;
    if (outcome === "end") {
      handlers?.onEnd?.();
    } else {
      handlers?.onError?.();
    }
    notifyLifecycle(false);
  };

  const utterance = new SpeechSynthesisUtterance(clean.slice(0, 500));
  utterance.lang = SPEAK_LANG;
  utterance.rate = 1.05;
  utterance.pitch = 1.0;
  const zhVoice = synth.getVoices().find((voice) => voice.lang && voice.lang.toLowerCase().startsWith("zh"));
  if (zhVoice) {
    utterance.voice = zhVoice;
  }
  utterance.onstart = () => {
    if (myGeneration !== generation) return;
    handlers?.onStart?.();
    notifyLifecycle(true);
  };
  utterance.onend = () => settle("end");
  utterance.onerror = () => settle("error");
  // Some engines never fire onend (Chrome tab suspension, missing voices);
  // the hard limit keeps the microphone from staying muted forever.
  let hardLimitTimer: number | null = window.setTimeout(() => settle("end"), SPEAK_HARD_LIMIT_MS);
  synth.speak(utterance);
  // Chrome populates voices asynchronously; if nothing actually started
  // because the queue is empty, surface the end so listeners resume.
  if (!synth.speaking && !synth.pending) {
    window.setTimeout(() => {
      if (myGeneration === generation && !settled && !synth.speaking) {
        settle("end");
      }
    }, 300);
  }
}

/** Stop any in-flight announcement (called when a new turn starts or the
 * user turns 回复播报 off). Invalidates pending speak() handlers. */
export function cancelSpeech(): void {
  generation += 1;
  if (!speechSynthesisSupported()) {
    return;
  }
  window.speechSynthesis.cancel();
  notifyLifecycle(false);
}

/** Whether an announcement is currently playing (used to pause the mic). */
export function isSpeaking(): boolean {
  if (!speechSynthesisSupported()) {
    return false;
  }
  return window.speechSynthesis.speaking || window.speechSynthesis.pending;
}
