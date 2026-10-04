import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchReadRequest } from "../lib/readRequest";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("transient public read requests", () => {
  it("retries a Cloudflare 530 once while keeping credentials and signal", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockResolvedValueOnce(new Response("edge unavailable", { status: 530 })).mockResolvedValueOnce(new Response('{}'));
    vi.stubGlobal("fetch", fetcher);
    const signal = new AbortController().signal;
    const init = { credentials: "include" as const, signal };
    const pending = fetchReadRequest("/layers", init);
    await vi.advanceTimersByTimeAsync(350);
    expect((await pending).status).toBe(200);
    expect(fetcher.mock.calls).toEqual([["/layers", init], ["/layers", init]]);
  });

  it.each(["POST", "PATCH", "DELETE"])("never repeats %s on transient failure", async method => {
    const fetcher = vi.fn().mockResolvedValue(new Response("unavailable", { status: 530 }));
    vi.stubGlobal("fetch", fetcher);
    expect((await fetchReadRequest("/class-sessions", { method })).status).toBe(530);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("returns authentication failures immediately", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("unauthorized", { status: 401 }));
    vi.stubGlobal("fetch", fetcher);
    expect((await fetchReadRequest("/layers", {})).status).toBe(401);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("bounds retries and honors cancellation during the delay", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockResolvedValue(new Response("unavailable", { status: 503 }));
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    const pending = fetchReadRequest("/layers", { signal: controller.signal });
    const failure = expect(pending).rejects.toThrow("Request cancelled");
    await vi.advanceTimersByTimeAsync(0);
    controller.abort();
    await vi.advanceTimersByTimeAsync(350);
    await failure;
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("stops after a second transient error", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(new Response("unavailable", { status: 530 })));
    vi.stubGlobal("fetch", fetcher);
    const pending = fetchReadRequest("/layers", {});
    await vi.advanceTimersByTimeAsync(350);
    expect((await pending).status).toBe(530);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
