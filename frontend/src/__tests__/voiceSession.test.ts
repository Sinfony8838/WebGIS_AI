/**
 * 智能交互语音会话控制器的状态测试：默认开启、拒绝授权、手动暂停、
 * 模式切换、播报互斥、断连恢复、过期回调、重复提交。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../voiceStream", () => ({
  VoiceStreamError: class VoiceStreamError extends Error {
    kind: string;
    constructor(kind: string, message?: string) {
      super(message ?? kind);
      this.name = "VoiceStreamError";
      this.kind = kind;
    }
  },
  createVoiceStream: vi.fn()
}));

type SpeechEvent =
  | { kind: "open" }
  | { kind: "final"; text: string }
  | { kind: "close"; code: number };

type FakeHandle = {
  events: {
    onOpen?: () => void;
    onFinal?: (text: string) => void;
    onClose?: (info: { code: number; reason: string }) => void;
  };
  abort: ReturnType<typeof vi.fn>;
  emit: (event: SpeechEvent) => void;
};

const handles: FakeHandle[] = [];
let speakingListener: ((state: { speaking: boolean }) => void) | null = null;

vi.mock("../speechSynthesis", () => ({
  onSpeechLifecycle: (listener: (state: { speaking: boolean }) => void) => {
    speakingListener = listener;
    return () => {
      speakingListener = null;
    };
  }
}));

import { createVoiceStream } from "../voiceStream";
import { VoiceSessionController, type VoiceSessionSnapshot } from "../voiceSession";

let nowMs = 1_000_000;

function makeController(overrides?: { requireWakeWord?: boolean }) {
  const snapshots: VoiceSessionSnapshot[] = [];
  const submitted: string[] = [];
  const controller = new VoiceSessionController({
    apiBase: () => "http://backend.test",
    audioWorkletSupported: () => true,
    now: () => nowMs,
    callbacks: {
      onSnapshot: (snapshot) => snapshots.push(snapshot),
      onSubmitCommand: (command) => submitted.push(command)
    }
  });
  if (overrides?.requireWakeWord) {
    controller.setSettings({ requireWakeWord: true });
  }
  return { controller, snapshots, submitted };
}

function lastPhase(controller: VoiceSessionController): VoiceSessionSnapshot["phase"] {
  return controller.snapshot().phase;
}

function installStreamFactory(): FakeHandle[] {
  handles.length = 0;
  vi.mocked(createVoiceStream).mockImplementation(async (_apiBase, events) => {
    const handle: FakeHandle = {
      events,
      abort: vi.fn(),
      emit: (event: SpeechEvent) => {
        if (event.kind === "open") events.onOpen?.();
        else if (event.kind === "final") events.onFinal?.(event.text);
        else events.onClose?.({ code: event.code, reason: "" });
      }
    };
    handles.push(handle);
    return { abort: handle.abort, stop: vi.fn(async () => null), state: () => "open" as const };
  });
  return handles;
}

function setPermissionState(state: "granted" | "prompt" | "denied") {
  Object.defineProperty(window.navigator, "permissions", {
    configurable: true,
    value: { query: async () => ({ state, onchange: null, addEventListener: () => undefined }) }
  });
}

describe("VoiceSessionController", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    nowMs = 1_000_000;
    installStreamFactory();
    setPermissionState("granted");
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("进入智能交互默认自动开始聆听（无需任何点击）", async () => {
    const { controller, snapshots } = makeController();
    controller.enterInteraction();
    // 短暂防自听延迟后自动建立采音会话。
    await vi.advanceTimersByTimeAsync(500); // RESUME_DELAY_MS=400 + 余量
    expect(vi.mocked(createVoiceStream)).toHaveBeenCalledOnce();
    handles[0].emit({ kind: "open" });
    expect(lastPhase(controller)).toBe("listening");
    expect(snapshots.at(-1)?.partial).toBe("");
  });

  it("拒绝授权：进入识别不可用，不循环重试，重试入口可恢复", async () => {
    setPermissionState("denied");
    const { controller } = makeController();
    controller.enterInteraction();
    await vi.advanceTimersByTimeAsync(500);
    expect(vi.mocked(createVoiceStream)).not.toHaveBeenCalled();
    expect(controller.snapshot().phase).toBe("unavailable");
    expect(controller.snapshot().detail).toContain("权限");
    // 长时间过去也不会无限重试。
    await vi.advanceTimersByTimeAsync(60_000);
    expect(vi.mocked(createVoiceStream)).not.toHaveBeenCalled();

    // 用户解除拒绝后点击重试：恢复聆听。
    setPermissionState("granted");
    controller.retry();
    await vi.advanceTimersByTimeAsync(500);
    expect(vi.mocked(createVoiceStream)).toHaveBeenCalledOnce();
    handles[0].emit({ kind: "open" });
    expect(lastPhase(controller)).toBe("listening");
  });

  it("手动暂停：采音停止、不提交；busy 翻转不会擅自重新打开", async () => {
    const { controller, submitted } = makeController();
    controller.enterInteraction();
    await vi.advanceTimersByTimeAsync(500);
    handles[0].emit({ kind: "open" });

    controller.togglePaused();
    expect(handles[0].abort).toHaveBeenCalledOnce();
    expect(controller.snapshot().phase).toBe("paused");
    handles[0].emit({ kind: "final", text: "切换到三维地球" });
    expect(submitted).toEqual([]);

    // 执行期 busy 翻转（重渲染/健康刷新）不得绕过手动暂停。
    controller.setBusy(true);
    controller.setBusy(false);
    await vi.advanceTimersByTimeAsync(5_000);
    expect(vi.mocked(createVoiceStream)).toHaveBeenCalledOnce();
    expect(controller.snapshot().phase).toBe("paused");

    // 恢复聆听后重建会话。
    controller.togglePaused();
    await vi.advanceTimersByTimeAsync(500);
    expect(vi.mocked(createVoiceStream)).toHaveBeenCalledTimes(2);
  });

  it("模式切换：离开交互立即停采音，旧会话的 final 不得提交；再次进入默认开启", async () => {
    const { controller, submitted } = makeController();
    controller.enterInteraction();
    await vi.advanceTimersByTimeAsync(500);
    const firstHandle = handles[0];
    firstHandle.emit({ kind: "open" });

    controller.exitInteraction();
    expect(firstHandle.abort).toHaveBeenCalledOnce();
    expect(controller.snapshot().phase).toBe("idle");

    // 离开后旧连接迟到的 final 被丢弃。
    firstHandle.emit({ kind: "final", text: "切换到三维地球" });
    expect(submitted).toEqual([]);

    // 再次进入交互：默认重新开始聆听。
    controller.enterInteraction();
    await vi.advanceTimersByTimeAsync(500);
    expect(vi.mocked(createVoiceStream)).toHaveBeenCalledTimes(2);
    handles[1].emit({ kind: "open" });
    expect(lastPhase(controller)).toBe("listening");
  });

  it("播报互斥：TTS 期间停采音并丢弃旧结果，真实 end 事件后恢复", async () => {
    const { controller, submitted } = makeController();
    controller.enterInteraction();
    await vi.advanceTimersByTimeAsync(500);
    handles[0].emit({ kind: "open" });

    speakingListener?.({ speaking: true });
    expect(handles[0].abort).toHaveBeenCalledOnce();
    expect(controller.snapshot().phase).toBe("speaking");

    // 播报期间到达的旧 final 不执行。
    handles[0].emit({ kind: "final", text: "打开图层管理器" });
    expect(submitted).toEqual([]);

    speakingListener?.({ speaking: false });
    await vi.advanceTimersByTimeAsync(500);
    expect(vi.mocked(createVoiceStream)).toHaveBeenCalledTimes(2);
    handles[1].emit({ kind: "open" });
    expect(lastPhase(controller)).toBe("listening");
  });

  it("断连恢复：有限退避重连，超过上限转不可用，可手动重试", async () => {
    const { controller } = makeController();
    controller.enterInteraction();
    await vi.advanceTimersByTimeAsync(500);
    expect(vi.mocked(createVoiceStream)).toHaveBeenCalledTimes(1);

    // 第 1 次异常断连 → ~1s 后重连（未 open 即再次断连）。
    handles[0].emit({ kind: "close", code: 1006 });
    await vi.advanceTimersByTimeAsync(1_200);
    expect(vi.mocked(createVoiceStream)).toHaveBeenCalledTimes(2);

    // 第 2 次断连 → ~2s 后重连。
    handles[1].emit({ kind: "close", code: 1006 });
    await vi.advanceTimersByTimeAsync(2_200);
    expect(vi.mocked(createVoiceStream)).toHaveBeenCalledTimes(3);

    // 第 3 次断连 → ~4s 后重连。
    handles[2].emit({ kind: "close", code: 1006 });
    await vi.advanceTimersByTimeAsync(4_200);
    expect(vi.mocked(createVoiceStream)).toHaveBeenCalledTimes(4);

    // 第 4 次断连 → 超过重试上限，转「识别不可用」，不再连接。
    handles[3].emit({ kind: "close", code: 1006 });
    await vi.advanceTimersByTimeAsync(20_000);
    expect(vi.mocked(createVoiceStream)).toHaveBeenCalledTimes(4);
    expect(controller.snapshot().phase).toBe("unavailable");
    expect(controller.snapshot().detail).toContain("重试");

    // 手动重试恢复。
    controller.retry();
    await vi.advanceTimersByTimeAsync(500);
    expect(vi.mocked(createVoiceStream)).toHaveBeenCalledTimes(5);
  });

  it("一条最终转写只提交一次；重复投递与突发旧结果被丢弃", async () => {
    const { controller, submitted } = makeController();
    controller.enterInteraction();
    await vi.advanceTimersByTimeAsync(500);
    const handle = handles[0];
    handle.emit({ kind: "open" });

    handle.emit({ kind: "final", text: "切换到三维地球" });
    expect(submitted).toEqual(["切换到三维地球"]);
    expect(controller.snapshot().phase).toBe("captured");

    // 同一条 final 重复投递（flush 与端点同时到达）→ 只提交一次。
    handle.emit({ kind: "final", text: "切换到三维地球" });
    expect(submitted).toHaveLength(1);

    // 提交后 busy 尚未挂起的短暂窗口内的突发 final → 丢弃。
    nowMs += 1_000;
    handle.emit({ kind: "final", text: "打开图层管理器" });
    expect(submitted).toHaveLength(1);
    expect(controller.snapshot().ignoredCount).toBe(1);

    // busy 期间的旧结果不执行；执行结束恢复后新指令正常提交。
    nowMs += 3_000;
    controller.setBusy(true);
    controller.setBusy(false);
    await vi.advanceTimersByTimeAsync(600);
    handles[1].emit({ kind: "open" });
    handles[1].emit({ kind: "final", text: "转到长三角" });
    expect(submitted).toEqual(["切换到三维地球", "转到长三角"]);
  });

  it("「仅唤醒后执行」设置生效；默认 direct 模式不强制唤醒词", async () => {
    const { controller, submitted } = makeController();
    controller.enterInteraction();
    await vi.advanceTimersByTimeAsync(500);
    handles[0].emit({ kind: "open" });

    // direct：无唤醒词直接通过。
    handles[0].emit({ kind: "final", text: "切换到三维地球" });
    expect(submitted).toEqual(["切换到三维地球"]);

    // wake_word：无唤醒词的明确指令被门控忽略。
    const strict = makeController({ requireWakeWord: true });
    strict.controller.enterInteraction();
    await vi.advanceTimersByTimeAsync(500);
    const strictHandle = handles[1];
    strictHandle.emit({ kind: "open" });
    strictHandle.emit({ kind: "final", text: "切换到三维地球" });
    expect(strict.submitted).toEqual([]);
    expect(strict.controller.snapshot().ignoredCount).toBe(1);

    // wake_word：带唤醒词通过并剥离。
    strictHandle.emit({ kind: "final", text: "小智，打开图层管理器" });
    expect(strict.submitted).toEqual(["打开图层管理器"]);
  });
});
