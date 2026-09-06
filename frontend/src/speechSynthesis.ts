/**
 * Browser TTS for voice-initiated assistant turns (智能交互语音播报).
 *
 * Kept deliberately tiny: zh-CN utterance, markdown stripped before
 * speaking, and a `cancel()` so a new command can interrupt the previous
 * announcement (barge-in). Falls back to a no-op when the browser has no
 * speechSynthesis or no Chinese voice is available — the text answer is
 * always on screen anyway.
 */

const SPEAK_LANG = "zh-CN";

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

/** Speak text in Chinese; cancels anything already queued. */
export function speak(text: string): void {
  if (!speechSynthesisSupported()) {
    return;
  }
  const clean = stripMarkdown(String(text || ""));
  if (!clean) {
    return;
  }
  const synth = window.speechSynthesis;
  synth.cancel();
  const utterance = new SpeechSynthesisUtterance(clean.slice(0, 500));
  utterance.lang = SPEAK_LANG;
  utterance.rate = 1.05;
  utterance.pitch = 1.0;
  const zhVoice = synth.getVoices().find((voice) => voice.lang && voice.lang.toLowerCase().startsWith("zh"));
  if (zhVoice) {
    utterance.voice = zhVoice;
  }
  synth.speak(utterance);
}

/** Stop any in-flight announcement (called when a new turn starts). */
export function cancelSpeech(): void {
  if (!speechSynthesisSupported()) {
    return;
  }
  window.speechSynthesis.cancel();
}

/** Whether an announcement is currently playing (used to pause the mic). */
export function isSpeaking(): boolean {
  if (!speechSynthesisSupported()) {
    return false;
  }
  return window.speechSynthesis.speaking || window.speechSynthesis.pending;
}
