import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const urls = ["a", "b", "c"].map(host => `https://${host}.test/tiles/{z}/{x}/{y}?style=6`);
const tileUrl = "https://a.test/tiles/4/11/5?style=6";
let images: FakeImage[];
class FakeImage {
  src = "";
  crossOrigin = "";
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() { images.push(this); }
}

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  images = [];
  vi.stubGlobal("Image", FakeImage);
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("configured tile mirrors", () => {
  it("preserves tile coordinates and avoids a failed server for one minute", async () => {
    const { alternateTileUrl, healthyTileUrl } = await import("../lib/tileServers");
    expect(healthyTileUrl(tileUrl, urls)).toBe(tileUrl);
    expect(alternateTileUrl(tileUrl, urls, true)).toBe("https://b.test/tiles/4/11/5?style=6");
    expect(healthyTileUrl(tileUrl, urls)).toContain("https://b.test/");
    await vi.advanceTimersByTimeAsync(60_000);
    expect(healthyTileUrl(tileUrl, urls)).toBe(tileUrl);
  });

  it("does not redirect single, unrelated, unknown or relative sources", async () => {
    const { alternateTileUrl } = await import("../lib/tileServers");
    expect(alternateTileUrl(tileUrl, [urls[0]], true)).toBeUndefined();
    expect(alternateTileUrl(tileUrl, [urls[0], "https://b.test/different/{z}/{x}/{y}"], true)).toBeUndefined();
    expect(alternateTileUrl("https://other.test/tiles/4/11/5", urls, true)).toBeUndefined();
    expect(alternateTileUrl("/tiles/4/11/5", urls, true)).toBeUndefined();
  });

  it("retries a stalled image after four seconds and returns the loaded mirror image", async () => {
    const { loadTileImage } = await import("../lib/tileServers");
    const result = loadTileImage(tileUrl, urls, "anonymous");
    expect(images[0].src).toBe(tileUrl);
    await vi.advanceTimersByTimeAsync(4000);
    expect(images).toHaveLength(2);
    expect(images[0].src).toBe("");
    expect(images[1].src).toBe("https://b.test/tiles/4/11/5?style=6");
    expect(images[1].crossOrigin).toBe("anonymous");
    images[1].onload!();
    expect(await result).toBe(images[1]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops after two failed attempts instead of retrying all mirrors indefinitely", async () => {
    const { loadTileImage } = await import("../lib/tileServers");
    const result = loadTileImage(tileUrl, urls, "anonymous");
    const failure = expect(result).rejects.toThrow("Tile unavailable");
    images[0].onerror!();
    await vi.advanceTimersByTimeAsync(0);
    images[1].onerror!();
    await failure;
    expect(images).toHaveLength(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("cancels image work without retrying or marking a healthy server unavailable", async () => {
    const { loadTileImage, healthyTileUrl } = await import("../lib/tileServers");
    const controller = new AbortController();
    const result = loadTileImage(tileUrl, urls, "anonymous", controller.signal);
    const failure = expect(result).rejects.toThrow("Tile load cancelled");
    controller.abort();
    await failure;
    expect(images).toHaveLength(1);
    expect(images[0].src).toBe("");
    expect(images[0].onload).toBeNull();
    expect(healthyTileUrl(tileUrl, urls)).toBe(tileUrl);
    expect(vi.getTimerCount()).toBe(0);
  });
});
