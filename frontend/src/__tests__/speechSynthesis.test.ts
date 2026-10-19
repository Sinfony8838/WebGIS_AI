import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cancelSpeech, isSpeaking, onSpeechLifecycle, speak } from "../speechSynthesis";

class FakeUtterance {
  lang = "";
  rate = 1;
  pitch = 1;
  voice: unknown;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public text: string) {}
}

const utterances: FakeUtterance[] = [];
const synth = {
  speaking: false,
  pending: false,
  getVoices: vi.fn(() => []),
  speak: vi.fn((utterance: FakeUtterance) => { utterances.push(utterance); synth.pending = true; }),
  cancel: vi.fn(() => { synth.speaking = false; synth.pending = false; })
};
const unsubscribers: (() => void)[] = [];

function observeSpeech() {
  const listener = vi.fn();
  unsubscribers.push(onSpeechLifecycle(listener));
  listener.mockClear();
  return listener;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
  vi.stubGlobal("speechSynthesis", synth);
  synth.speaking = false;
  synth.pending = false;
  utterances.length = 0;
  cancelSpeech();
  vi.clearAllMocks();
});

afterEach(() => {
  unsubscribers.splice(0).forEach((unsubscribe) => unsubscribe());
  cancelSpeech();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("speech playback ownership", () => {
  it("pauses capture as soon as speech is queued, before a delayed start event", () => {
    const lifecycle = observeSpeech();
    speak("已经打开图层管理器。");
    expect(lifecycle).toHaveBeenLastCalledWith({ speaking: true });
    expect(isSpeaking()).toBe(true);
    utterances[0].onend?.();
    expect(lifecycle).toHaveBeenLastCalledWith({ speaking: false });
  });

  it("stops real playback before the watchdog allows microphone capture again", async () => {
    const lifecycle = observeSpeech();
    const onError = vi.fn();
    const onEnd = vi.fn();
    speak("一段没有结束事件的回复", { onError, onEnd });
    synth.speaking = true;
    synth.pending = false;
    utterances[0].onstart?.();
    lifecycle.mockClear();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(synth.cancel).toHaveBeenCalledTimes(2);
    expect(synth.speaking).toBe(false);
    expect(lifecycle).toHaveBeenLastCalledWith({ speaking: false });
    expect(onError).toHaveBeenCalledOnce();
    expect(onEnd).not.toHaveBeenCalled();
  });

  it("a superseded utterance cannot unmute capture during the next reply", () => {
    const lifecycle = observeSpeech();
    speak("第一条回复");
    const first = utterances[0];
    first.onstart?.();
    speak("第二条回复");
    lifecycle.mockClear();
    first.onend?.();
    first.onerror?.();
    expect(lifecycle).not.toHaveBeenCalled();
    utterances[1].onend?.();
    expect(lifecycle).toHaveBeenLastCalledWith({ speaking: false });
  });

  it("an empty replacement stops the previous reply instead of leaving it playing", () => {
    const lifecycle = observeSpeech();
    speak("旧回复");
    const onEnd = vi.fn();
    speak("  ", { onEnd });
    expect(synth.cancel).toHaveBeenCalledTimes(2);
    expect(synth.pending).toBe(false);
    expect(lifecycle).toHaveBeenLastCalledWith({ speaking: false });
    expect(onEnd).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("a new subscriber observes already queued speech", () => {
    speak("已经排队的回复");
    const listener = vi.fn();
    unsubscribers.push(onSpeechLifecycle(listener));
    expect(listener).toHaveBeenLastCalledWith({ speaking: true });
  });

  it("a synchronous speech engine failure resumes capture and reports error", () => {
    const lifecycle = observeSpeech();
    synth.speak.mockImplementationOnce(() => { throw new Error("engine unavailable"); });
    const onError = vi.fn();
    expect(() => speak("回复", { onError })).not.toThrow();
    expect(onError).toHaveBeenCalledOnce();
    expect(lifecycle).toHaveBeenLastCalledWith({ speaking: false });
    expect(vi.getTimerCount()).toBe(0);
  });
});
