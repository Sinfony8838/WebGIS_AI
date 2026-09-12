import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createVoiceStream } from "../voiceStream";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

class FakeSocket {
  static OPEN = 1;
  static last: FakeSocket;
  readyState = 1;
  binaryType = "";
  onopen?: () => void;
  onmessage?: (event: { data: string }) => void;
  onerror?: () => void;
  onclose?: (event: { code: number }) => void;
  send = vi.fn();
  close = vi.fn(() => { this.readyState = 3; });
  constructor() { FakeSocket.last = this; }
}

const track = { stop: vi.fn() };
const media = { getTracks: () => [track] } as unknown as MediaStream;
const addModule = vi.fn();
const closeContext = vi.fn();
const createSource = vi.fn();
const getUserMedia = vi.fn();
const revokeObjectURL = vi.fn();

beforeEach(() => {
  vi.useFakeTimers();
  getUserMedia.mockResolvedValue(media);
  addModule.mockResolvedValue(undefined);
  closeContext.mockResolvedValue(undefined);
  createSource.mockReturnValue({ connect: vi.fn(), disconnect: vi.fn() });
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
  vi.stubGlobal("AudioContext", class {
    audioWorklet = { addModule };
    close = closeContext;
    createMediaStreamSource = createSource;
  });
  vi.stubGlobal("AudioWorkletNode", class {
    port = { onmessage: null };
    disconnect = vi.fn();
  });
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = vi.fn(() => "blob:voice-worklet");
    static revokeObjectURL = revokeObjectURL;
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

async function openStream() {
  const onFinal = vi.fn();
  const onClose = vi.fn();
  const pending = createVoiceStream("http://localhost:8000", { onFinal, onClose });
  FakeSocket.last.onopen?.();
  return { handle: await pending, socket: FakeSocket.last, onFinal, onClose };
}

describe("voice stream lifecycle", () => {
  it("stops a microphone granted after the connection has already closed", async () => {
    const permission = deferred<MediaStream>();
    getUserMedia.mockReturnValue(permission.promise);
    const onOpen = vi.fn();
    const pending = createVoiceStream("http://localhost:8000", { onOpen });
    const rejected = expect(pending).rejects.toThrow("连接中断");
    FakeSocket.last.onopen?.();
    FakeSocket.last.onclose?.({ code: 1006 });
    await rejected;
    permission.resolve(media);
    await vi.advanceTimersByTimeAsync(0);
    expect(track.stop).toHaveBeenCalledOnce();
    expect(addModule).not.toHaveBeenCalled();
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("does not resume initialization after closure during worklet loading", async () => {
    const module = deferred<void>();
    addModule.mockReturnValue(module.promise);
    const onOpen = vi.fn();
    const pending = createVoiceStream("http://localhost:8000", { onOpen });
    const rejected = expect(pending).rejects.toThrow("连接中断");
    FakeSocket.last.onopen?.();
    await vi.advanceTimersByTimeAsync(0);
    FakeSocket.last.onclose?.({ code: 1006 });
    await rejected;
    module.resolve();
    await vi.advanceTimersByTimeAsync(0);
    expect(createSource).not.toHaveBeenCalled();
    expect(onOpen).not.toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:voice-worklet");
  });

  it("releases resources when flush returns without waiting for server closure", async () => {
    const { handle, socket, onFinal, onClose } = await openStream();
    const stopped = handle.stop();
    expect(socket.send).toHaveBeenCalledWith("flush");
    socket.onmessage?.({ data: JSON.stringify({ type: "final", text: "切换到三维地球" }) });
    expect(await stopped).toBe("切换到三维地球");
    expect(handle.state()).toBe("closed");
    expect(track.stop).toHaveBeenCalledOnce();
    expect(socket.close).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
    expect(onFinal).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("settles repeated stop calls together and releases the worklet URL", async () => {
    const { handle, socket } = await openStream();
    const first = handle.stop();
    const second = handle.stop();
    socket.onmessage?.({ data: JSON.stringify({ type: "final", text: "完成" }) });
    await vi.advanceTimersByTimeAsync(2000);
    await expect(first).resolves.toBe("完成");
    await expect(second).resolves.toBe("完成");
    expect(socket.send).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledOnce();
  });

  it.each(["disconnect", "timeout", "abort"])("closes and resolves stop on %s", async (reason) => {
    const { handle, socket } = await openStream();
    const stopped = handle.stop();
    if (reason === "disconnect") socket.onclose?.({ code: 1006 });
    else if (reason === "abort") handle.abort();
    else await vi.advanceTimersByTimeAsync(2000);
    await expect(stopped).resolves.toBeNull();
    expect(handle.state()).toBe("closed");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("releases the microphone and object URL if worklet loading fails", async () => {
    addModule.mockRejectedValue(new Error("module unavailable"));
    const pending = createVoiceStream("http://localhost:8000", {});
    FakeSocket.last.onopen?.();
    await expect(pending).rejects.toThrow("module unavailable");
    expect(track.stop).toHaveBeenCalledOnce();
    expect(closeContext).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledOnce();
    expect(FakeSocket.last.close).toHaveBeenCalledOnce();
  });

  it("ignores invalid JSON values without interrupting later transcripts", async () => {
    const { handle, socket, onFinal } = await openStream();
    expect(() => socket.onmessage?.({ data: "null" })).not.toThrow();
    socket.onmessage?.({ data: JSON.stringify({ type: "final", text: "有效指令" }) });
    expect(onFinal).toHaveBeenCalledWith("有效指令");
    handle.abort();
  });
});
