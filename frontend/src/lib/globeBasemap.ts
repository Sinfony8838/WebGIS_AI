import { Credit, ImageryLayer, Resource, UrlTemplateImageryProvider, type Viewer } from "cesium";
import type { BasemapLayerDescriptor } from "../types";
import { basemapSourceKey, globeTileTemplate } from "./basemap";
import { alternateTileUrl } from "./tileServers";

type Entry = { key: string; layer: ImageryLayer; removeProgress?: () => void };

/** Keep one loaded fallback while the replacement fills; never stack stale requests. */
export class GlobeBasemap {
  private active?: Entry;
  private pending?: Entry;

  constructor(private viewer: Pick<Viewer, "imageryLayers" | "scene">) {}

  set(descriptor: BasemapLayerDescriptor) {
    const key = basemapSourceKey(descriptor);
    if (this.pending?.key === key) {
      this.pending.layer.alpha = descriptor.opacity;
      return;
    }
    this.removePending();
    if (this.active?.key === key) {
      this.active.layer.alpha = descriptor.opacity;
      this.viewer.scene.requestRender();
      return;
    }
    const template = globeTileTemplate(descriptor.urls);
    const resource = new Resource({ url: template.url, retryAttempts: 1, retryCallback: failedResource => {
      if (!failedResource) return false;
      const next = alternateTileUrl(failedResource.url, descriptor.urls, true);
      if (!next) return false;
      failedResource.url = next;
      return true;
    } });
    const provider = new UrlTemplateImageryProvider({
      ...template, url: resource, maximumLevel: descriptor.max_zoom ?? 18,
      credit: new Credit(descriptor.attribution || "", true)
    });
    const entry: Entry = { key, layer: new ImageryLayer(provider, { alpha: descriptor.opacity }) };
    const index = this.active ? this.viewer.imageryLayers.indexOf(this.active.layer) + 1 : 0;
    this.viewer.imageryLayers.add(entry.layer, index);
    if (!this.active) {
      this.active = entry;
    } else {
      this.pending = entry;
      let loadingObserved = false;
      let failed = false;
      const removeError = provider.errorEvent.addEventListener(() => { failed = true; });
      const finish = () => {
        if (this.pending !== entry) return;
        entry.removeProgress?.();
        entry.removeProgress = undefined;
        // A failed replacement cannot blank out the last usable map.
        if (failed) return;
        this.viewer.imageryLayers.remove(this.active!.layer, true);
        this.active = entry;
        this.pending = undefined;
        this.viewer.scene.requestRender();
      };
      const removeProgress = this.viewer.scene.globe.tileLoadProgressEvent.addEventListener((count: number) => {
        if (count > 0) loadingObserved = true;
        if (loadingObserved && count === 0) finish();
      });
      let frames = 0;
      const removeRender = this.viewer.scene.postRender.addEventListener(() => {
        // An entirely cached replacement may never enqueue a network request.
        if (++frames >= 2 && this.viewer.scene.globe.tilesLoaded) finish();
      });
      entry.removeProgress = () => { removeProgress(); removeRender(); removeError(); };
    }
    this.viewer.scene.requestRender();
  }

  private removePending() {
    if (!this.pending) return;
    this.pending.removeProgress?.();
    this.viewer.imageryLayers.remove(this.pending.layer, true);
    this.pending = undefined;
  }

  destroy() {
    this.removePending();
    if (this.active) this.viewer.imageryLayers.remove(this.active.layer, true);
    this.active = undefined;
  }
}
