/**
 * Browser TTS for voice-initiated assistant turns (智能交互语音播报).
 *
 * zh-CN utterance, markdown stripped before speaking, and a `cancel()` so a
 * new turn or an explicit stop can interrupt the previous announcement.
 * Uses a Chinese voice when available, otherwise the browser default.
 * Without speechSynthesis the text answer remains available on screen.
 *
 * The voice session must resume listening the moment playback actually
 * ends (and never resume while it is still running), so `speak` exposes
 * real start/end/error events plus a module-level lifecycle broadcast that
 * App.tsx and voiceSession.ts subscribe to. A hard timeout guards against
 * browsers that never fire the end event, replacing the old fixed-delay
 * wait that could resume the mic too early or mute it for ages.
 */

const SPEAK_LANG = "zh-CN";
/** Bound a playback slot; cancel sound before releasing it on expiry. */
const SPEAK_HARD_LIMIT_MS = 30_000;

export type SpeechHandlers = {
  onStart?: () => void;
  onEnd?: () => void;
  onError?: () => void;
};

type LifecycleListener = (state: { speaking: boolean }) => void;

const lifecycleListeners = new Set<LifecycleListener>();
let speechActive = false;
let clearActiveTimer: (() => void) | null = null;

/** Subscribe to playback start/end (used to pause/resume mic capture). */
export function onSpeechLifecycle(listener: LifecycleListener): () => void {
  lifecycleListeners.add(listener);
  listener({ speaking: speechActive });
  return () => {
    lifecycleListeners.delete(listener);
  };
}

function notifyLifecycle(speaking: boolean): void {
  speechActive = speaking;
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
  // Supersede before cancel(): some engines synchronously dispatch the old
  // utterance's error event while clearing their queue.
  stopSpeech(false);
  const myGeneration = generation;
  if (!speechSynthesisSupported()) {
    notifyLifecycle(false);
    handlers?.onError?.();
    return;
  }
  const clean = stripMarkdown(String(text || ""));
  if (!clean) {
    notifyLifecycle(false);
    handlers?.onEnd?.();
    return;
  }
  const synth = window.speechSynthesis;
  let settled = false;
  let hardLimitTimer: number | null = null;
  let emptyQueueTimer: number | null = null;
  const clearTimers = () => {
    if (hardLimitTimer !== null) window.clearTimeout(hardLimitTimer);
    if (emptyQueueTimer !== null) window.clearTimeout(emptyQueueTimer);
    hardLimitTimer = null;
    emptyQueueTimer = null;
  };
  clearActiveTimer = clearTimers;

  const settle = (outcome: "end" | "error", stopPlayback = false) => {
    if (settled) return;
    settled = true;
    clearTimers();
    if (myGeneration !== generation) return;
    clearActiveTimer = null;
    // A watchdog must stop actual sound before the microphone resumes.
    if (stopPlayback) synth.cancel();
    notifyLifecycle(false);
    if (outcome === "end") handlers?.onEnd?.();
    else handlers?.onError?.();
  };

  const utterance = new SpeechSynthesisUtterance(clean.slice(0, 500));
  utterance.lang = SPEAK_LANG;
  utterance.rate = 1.05;
  utterance.pitch = 1.0;
  const zhVoice = synth.getVoices().find((voice) => voice.lang && voice.lang.toLowerCase().startsWith("zh"));
  if (zhVoice) utterance.voice = zhVoice;
  utterance.onstart = () => {
    if (myGeneration !== generation || settled) return;
    handlers?.onStart?.();
  };
  utterance.onend = () => settle("end");
  utterance.onerror = () => settle("error");
  hardLimitTimer = window.setTimeout(() => settle("error", true), SPEAK_HARD_LIMIT_MS);
  // Own the microphone exclusion from queue time, including delayed onstart.
  notifyLifecycle(true);
  try {
    synth.speak(utterance);
  } catch {
    settle("error", true);
    return;
  }
  if (!synth.speaking && !synth.pending && !settled) {
    emptyQueueTimer = window.setTimeout(() => {
      if (myGeneration === generation && !settled && !synth.speaking && !synth.pending) {
        settle("error", true);
      }
    }, 300);
  }
}

function stopSpeech(notify: boolean): void {
  generation += 1;
  clearActiveTimer?.();
  clearActiveTimer = null;
  if (speechSynthesisSupported()) window.speechSynthesis.cancel();
  if (notify) notifyLifecycle(false);
}

/** Stop any in-flight announcement (called when a new turn starts or the
 * user turns 回复播报 off). Invalidates pending speak() handlers. */
export function cancelSpeech(): void {
  stopSpeech(true);
}

/** Whether an announcement is currently playing (used to pause the mic). */
export function isSpeaking(): boolean {
  if (!speechSynthesisSupported()) {
    return false;
  }
  return speechActive || window.speechSynthesis.speaking || window.speechSynthesis.pending;
}
