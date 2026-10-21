import { afterEach, describe, expect, it, vi } from "vitest";
import { BrushHistory } from "../lib/brushHistory";

describe("PPT session persistence", () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });
  it("serializes independent deck pages and restores them after module reload", async () => {
    const records = new Map<string, unknown>();
    const database = { createObjectStore() {}, transaction: () => {
      const transaction = { oncomplete: undefined as undefined | (() => void), objectStore: () => ({
        put: (value: unknown, key: string) => { records.set(key, structuredClone(value)); setTimeout(() => transaction.oncomplete?.(), 0); },
        get: (key: string) => { const request = { result: records.get(key), onsuccess: undefined as undefined | (() => void) }; setTimeout(() => request.onsuccess?.(), 0); return request; }
      }) }; return transaction;
    } };
    vi.stubGlobal("indexedDB", { open: () => { const request = { result: database, onsuccess: undefined as undefined | (() => void) }; setTimeout(() => request.onsuccess?.(), 0); return request; } });
    let sessions = await import("../lib/pptSession");
    const a = await sessions.loadPptSession("u:p:A");
    a.currentIndex = 4; a.widthPercent = 55; a.history.commit("4", "data:image/png;base64,inkA");
    await sessions.savePptSession("u:p:A", a);
    const b = await sessions.loadPptSession("u:p:B"); b.history.commit("0", "inkB");
    await sessions.savePptSession("u:p:B", b);
    vi.resetModules(); sessions = await import("../lib/pptSession");
    const restored = await sessions.loadPptSession("u:p:A");
    expect(restored.currentIndex).toBe(4); expect(restored.widthPercent).toBe(55);
    expect(restored.history.image("4")).toBe("data:image/png;base64,inkA");
    expect((await sessions.loadPptSession("u:p:B")).history.image("0")).toBe("inkB");
    expect((await sessions.loadPptSession("other:p:A")).history.image("4")).toBeNull();
  });

  it("round-trips only current ink snapshots while preserving live undo state", () => {
    const history = new BrushHistory(); history.commit("0", "A"); history.commit("0", "AB"); history.commit("1", "C");
    const restored = BrushHistory.restore(history.snapshot());
    expect(restored.image("0")).toBe("AB"); expect(restored.image("1")).toBe("C");
    expect(history.undo("0")).toBe(true); expect(history.image("0")).toBe("A");
    expect(restored.image("0")).toBe("AB");
  });

  it("caches private image bytes only in the active actor/project scope", async () => {
    vi.stubGlobal("Image", class { onload?: () => void; set src(_value: string) { queueMicrotask(() => this.onload?.()); } });
    const fetcher = vi.fn().mockResolvedValue({ ok: true, blob: async () => ({ size: 20 }) });
    vi.stubGlobal("fetch", fetcher);
    let next = 0;
    const create = vi.fn(() => `blob:test-${++next}`), revoke = vi.fn();
    vi.stubGlobal("URL", { createObjectURL: create, revokeObjectURL: revoke });
    const session = await import("../lib/pptSession");
    await session.preloadPptImage("/private.png", undefined, "user:project");
    await session.preloadPptImage("/private.png", undefined, "user:project");
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][1].credentials).toBe("include");
    expect(session.cachedPptImage("/private.png", "user:project")).toBe("blob:test-1");
    expect(session.cachedPptImage("/private.png", "other:project")).toBe("/private.png");
    await session.preloadPptImage("/private.png", undefined, "other:project");
    session.releasePptImages("user:project");
    expect(revoke).toHaveBeenCalledWith("blob:test-1");
    expect(session.cachedPptImage("/private.png", "user:project")).toBe("/private.png");
    expect(session.cachedPptImage("/private.png", "other:project")).toBe("blob:test-2");
  });

  it("discards a page finishing after its account/project was released", async () => {
    vi.stubGlobal("Image", class { onload?: () => void; set src(_value: string) { queueMicrotask(() => this.onload?.()); } });
    let finish!: (value: unknown) => void;
    vi.stubGlobal("fetch", () => new Promise(resolve => { finish = resolve; }));
    const revoke = vi.fn(); vi.stubGlobal("URL", { createObjectURL: () => "blob:late", revokeObjectURL: revoke });
    const session = await import("../lib/pptSession");
    const pending = session.preloadPptImage("/late.png", undefined, "old:project");
    session.releasePptImages("old:project");
    finish({ ok: true, blob: async () => ({ size: 20 }) });
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(session.cachedPptImage("/late.png", "old:project")).toBe("/late.png");
    expect(revoke).toHaveBeenCalledWith("blob:late");
  });
});
