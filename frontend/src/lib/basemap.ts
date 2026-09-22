import TileLayer from "ol/layer/Tile";
import XYZ from "ol/source/XYZ";
import type ImageTile from "ol/ImageTile";
import TileState from "ol/TileState";
import type { BasemapLayerDescriptor } from "../types";
import { healthyTileUrl, loadTileImage } from "./tileServers";

export const DEFAULT_IMAGERY_LAYER: BasemapLayerDescriptor = {
  layer_id: "amap_imagery_base", title: "高德影像底图", kind: "xyz",
  urls: ["01", "02", "03", "04"].map(server => `https://webst${server}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}`),
  attribution: "© 高德地图", opacity: 1, z_index: 1, usable_in_3d: true
};

/** Only source settings affect tile identity; refreshed API objects do not. */
export function basemapSourceKey(layer: BasemapLayerDescriptor): string {
  return JSON.stringify([layer.urls, layer.max_zoom ?? 18, layer.attribution || "", layer.cross_origin || "anonymous"]);
}

/** Use the same server for a tile in Cesium and OL, allowing HTTP cache reuse. */
export function globeTileTemplate(urls: string[]) {
  const first = urls[0];
  if (urls.length < 2) return { url: first };
  let prefix = 0;
  while (prefix < first.length && urls.every(url => url[prefix] === first[prefix])) prefix++;
  let suffix = 0;
  while (suffix < first.length - prefix && urls.every(url => url.length - suffix > prefix && url[url.length - suffix - 1] === first[first.length - suffix - 1])) suffix++;
  const segments = urls.map(url => url.slice(prefix, suffix ? -suffix : undefined));
  // Only fold interchangeable server names/numbers, never coordinate expressions.
  if (!segments.every(value => /^[\w.-]+$/.test(value))) return { url: first };
  return {
    url: `${first.slice(0, prefix)}{tileServer}${suffix ? first.slice(-suffix) : ""}`,
    customTags: {
      tileServer: (_provider: unknown, x: number, y: number, level: number) => {
        const hash = (x << level) + y; // OpenLayers tilecoord.hash
        const index = ((hash % segments.length) + segments.length) % segments.length;
        const healthy = healthyTileUrl(urls[index], urls);
        const healthyIndex = urls.indexOf(healthy.replaceAll("%7B", "{").replaceAll("%7D", "}"));
        return segments[healthyIndex < 0 ? index : healthyIndex];
      }
    }
  };
}

/** A small source cache preserves decoded tiles when switching away and back. */
export class BasemapLayerCache {
  private layers = new Map<string, TileLayer<XYZ>>();
  private failed = new WeakSet<TileLayer<XYZ>>();
  private requests = new Map<TileLayer<XYZ>, AbortController>();

  private release(layer: TileLayer<XYZ>) {
    this.requests.get(layer)?.abort();
    this.requests.delete(layer);
    layer.getSource()?.dispose();
    layer.dispose();
  }

  get(descriptor: BasemapLayerDescriptor): TileLayer<XYZ> {
    // Keep different presentation layers separate even when they share a URL.
    const key = JSON.stringify([descriptor.layer_id, basemapSourceKey(descriptor), descriptor.class_name]);
    let layer = this.layers.get(key);
    if (layer && (this.failed.has(layer) || descriptor.class_name?.includes("basemap-weather-overlay"))) {
      this.release(layer);
      layer = undefined;
    }
    if (!layer) {
      const requests = new AbortController();
      layer = new TileLayer({ className: descriptor.class_name, source: new XYZ({
        ...(descriptor.urls.length > 1 ? { urls: descriptor.urls } : { url: descriptor.urls[0] }),
        attributions: descriptor.attribution || undefined,
        maxZoom: descriptor.max_zoom ?? 18,
        crossOrigin: descriptor.cross_origin || "anonymous",
        transition: 0,
        ...(descriptor.urls.length > 1 ? { tileLoadFunction: (tile, src) => {
          void loadTileImage(src, descriptor.urls, descriptor.cross_origin || "anonymous", requests.signal)
            .then(image => { if (!requests.signal.aborted) (tile as ImageTile).setImage(image); })
            .catch(() => { if (!requests.signal.aborted) tile.setState(TileState.ERROR); });
        } } : {})
      }) });
      this.requests.set(layer, requests);
      const currentLayer = layer;
      layer.getSource()!.on("tileloaderror", () => this.failed.add(currentLayer));
    }
    this.layers.delete(key);
    this.layers.set(key, layer);
    layer.setOpacity(descriptor.opacity);
    layer.setZIndex(descriptor.z_index);
    while (this.layers.size > 8) {
      const oldestKey = this.layers.keys().next().value!;
      const oldest = this.layers.get(oldestKey)!;
      this.layers.delete(oldestKey);
      this.release(oldest);
    }
    return layer;
  }

  clear() {
    for (const layer of this.layers.values()) {
      this.release(layer);
    }
    this.layers.clear();
  }
}
