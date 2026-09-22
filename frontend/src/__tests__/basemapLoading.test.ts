import { afterEach, describe, expect, it, vi } from "vitest";
import { Event, ImageryLayerCollection, Resource, UrlTemplateImageryProvider, type Viewer } from "cesium";
import { createXYZ } from "ol/tilegrid";
import { createFromTemplates } from "ol/tileurlfunction";
import { get as getProjection } from "ol/proj";
import { BasemapLayerCache, DEFAULT_IMAGERY_LAYER, globeTileTemplate } from "../lib/basemap";
import { GlobeBasemap } from "../lib/globeBasemap";

afterEach(() => vi.restoreAllMocks());

describe("shared basemap tiles", () => {
  it("requests the exact same tile URL in Cesium and OpenLayers across servers and zoom levels", async () => {
    const fetchImage = vi.spyOn(Resource.prototype, "fetchImage").mockResolvedValue(document.createElement("img"));
    const urls = DEFAULT_IMAGERY_LAYER.urls;
    const provider = new UrlTemplateImageryProvider(globeTileTemplate(urls));
    const olUrl = createFromTemplates(urls, createXYZ());
    for (const [z, x, y] of [[0, 0, 0], [4, 12, 5], [4, 13, 6], [4, 14, 7], [18, 204001, 102002]]) {
      await provider.requestImage(x, y, z);
      const resource = fetchImage.mock.contexts.at(-1)!;
      expect(resource.getUrlComponent(true)).toBe(olUrl([z, x, y], 1, getProjection("EPSG:3857")!));
    }
    expect(new Set(fetchImage.mock.contexts.map(resource => new URL(resource.getUrlComponent(true)).hostname)).size).toBeGreaterThan(1);
  });

  it("does not fold unrelated custom URLs or alter single URLs", () => {
    expect(globeTileTemplate(["https://a.test/{z}/{x}/{y}"]).url).toBe("https://a.test/{z}/{x}/{y}");
    expect(globeTileTemplate(["https://a.test/{z}/{x}/{y}", "https://b.test/{x}/{z}/{y}"]).url).toBe("https://a.test/{z}/{x}/{y}");
  });

  it("reuses decoded OL tiles through API refreshes and switching away and back", () => {
    const cache = new BasemapLayerCache();
    const first = cache.get(DEFAULT_IMAGERY_LAYER);
    const source = first.getSource()!;
    const tile = source.getTile(4, 12, 6, 1, getProjection("EPSG:3857")!);
    cache.get({ ...DEFAULT_IMAGERY_LAYER, layer_id: "other", urls: ["https://a.test/{z}/{x}/{y}"] });
    const restored = cache.get(JSON.parse(JSON.stringify(DEFAULT_IMAGERY_LAYER)));
    expect(restored).toBe(first);
    expect(restored.getSource()!.getTile(4, 12, 6, 1, getProjection("EPSG:3857")!)).toBe(tile);
    cache.clear();
  });

  it("refreshes failed and time-dependent weather sources when reselected", () => {
    const cache = new BasemapLayerCache();
    const failed = cache.get(DEFAULT_IMAGERY_LAYER);
    failed.getSource()!.dispatchEvent("tileloaderror");
    expect(cache.get(DEFAULT_IMAGERY_LAYER)).not.toBe(failed);
    const weather = { ...DEFAULT_IMAGERY_LAYER, layer_id: "weather", class_name: "basemap-weather-overlay" };
    const first = cache.get(weather);
    expect(cache.get(weather)).not.toBe(first);
    cache.clear();
  });

  it("bounds the OL source cache", () => {
    const cache = new BasemapLayerCache();
    const first = cache.get(DEFAULT_IMAGERY_LAYER);
    const dispose = vi.spyOn(first, "dispose");
    for (let i = 0; i < 8; i++) cache.get({ ...DEFAULT_IMAGERY_LAYER, layer_id: `extra-${i}` });
    expect(dispose).toHaveBeenCalledOnce();
    cache.clear();
  });
});

function globe() {
  const imageryLayers = new ImageryLayerCollection();
  const progress = new Event();
  const postRender = new Event();
  const scene = { globe: { tileLoadProgressEvent: progress, tilesLoaded: false }, postRender, requestRender: vi.fn() };
  const controller = new GlobeBasemap({ imageryLayers, scene } as unknown as Viewer);
  return { controller, imageryLayers, scene, progress, postRender };
}
const other = { ...DEFAULT_IMAGERY_LAYER, urls: ["https://a.test/{z}/{x}/{y}.png"] };

describe("globe basemap replacement", () => {
  it("retries a failed Cesium resource on one configured mirror with coordinates intact", async () => {
    const fetchImage = vi.spyOn(Resource.prototype, "fetchImage").mockResolvedValue(document.createElement("img"));
    const g = globe();
    g.controller.set({ ...DEFAULT_IMAGERY_LAYER, urls: ["https://one.retry.test/{z}/{x}/{y}.png", "https://two.retry.test/{z}/{x}/{y}.png"] });
    await g.imageryLayers.get(0).imageryProvider.requestImage(11, 5, 4);
    const resource = fetchImage.mock.contexts.at(-1)! as Resource & { retryOnError(error: Error): Promise<boolean> };
    expect(resource.url).toBe("https://two.retry.test/4/11/5.png");
    expect(await resource.retryOnError(new Error("server unavailable"))).toBe(true);
    expect(resource.url).toBe("https://one.retry.test/4/11/5.png");
    expect(await resource.retryOnError(new Error("second failure"))).toBe(false);
    g.controller.destroy();
  });

  it("creates one initial provider and ignores equivalent refreshed descriptors", () => {
    const g = globe();
    g.controller.set(DEFAULT_IMAGERY_LAYER);
    const layer = g.imageryLayers.get(0);
    g.controller.set(JSON.parse(JSON.stringify(DEFAULT_IMAGERY_LAYER)));
    expect(g.imageryLayers.length).toBe(1);
    expect(g.imageryLayers.get(0)).toBe(layer);
    g.controller.destroy();
  });

  it("keeps the old layer until new tiles complete and cleans all listeners", () => {
    const g = globe();
    g.controller.set(DEFAULT_IMAGERY_LAYER);
    const old = g.imageryLayers.get(0);
    g.controller.set(other);
    expect(g.imageryLayers.length).toBe(2);
    expect(old.isDestroyed()).toBe(false);
    g.progress.raiseEvent(3);
    g.progress.raiseEvent(0);
    expect(g.imageryLayers.length).toBe(1);
    expect(old.isDestroyed()).toBe(true);
    expect(g.progress.numberOfListeners).toBe(0);
    expect(g.postRender.numberOfListeners).toBe(0);
    g.controller.destroy();
  });

  it("finishes a cached replacement without requiring a network progress event", () => {
    const g = globe();
    g.controller.set(DEFAULT_IMAGERY_LAYER);
    g.controller.set(other);
    g.scene.globe.tilesLoaded = true;
    g.postRender.raiseEvent();
    expect(g.imageryLayers.length).toBe(2);
    g.postRender.raiseEvent();
    expect(g.imageryLayers.length).toBe(1);
    g.controller.destroy();
  });

  it("cancels obsolete replacements and restores the active source without reloading", () => {
    const g = globe();
    g.controller.set(DEFAULT_IMAGERY_LAYER);
    const old = g.imageryLayers.get(0);
    g.controller.set(other);
    const cancelled = g.imageryLayers.get(1);
    g.controller.set(DEFAULT_IMAGERY_LAYER);
    expect(cancelled.isDestroyed()).toBe(true);
    expect(g.imageryLayers.length).toBe(1);
    expect(g.imageryLayers.get(0)).toBe(old);
    g.progress.raiseEvent(0);
    expect(old.isDestroyed()).toBe(false);
    g.controller.destroy();
    expect(g.progress.numberOfListeners).toBe(0);
  });

  it("retains a usable fallback when the new provider fails", () => {
    const g = globe();
    g.controller.set(DEFAULT_IMAGERY_LAYER);
    const old = g.imageryLayers.get(0);
    g.controller.set(other);
    g.imageryLayers.get(1).imageryProvider.errorEvent.raiseEvent({ message: "offline" });
    g.progress.raiseEvent(2);
    g.progress.raiseEvent(0);
    expect(old.isDestroyed()).toBe(false);
    g.controller.destroy();
    expect(g.imageryLayers.length).toBe(0);
    expect(g.postRender.numberOfListeners).toBe(0);
  });
});
