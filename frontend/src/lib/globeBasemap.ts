import { Credit, ImageryLayer, Resource, UrlTemplateImageryProvider, type Viewer } from "cesium";
import type { BasemapLayerDescriptor } from "../types";
import { basemapSourceKey, globeTileTemplate } from "./basemap";
import { alternateTileUrl } from "./tileServers";
import { BasemapLoadWatchdog, type BasemapLoadPhase } from "./basemapLoadStatus";

type Entry = { key: string; layer: ImageryLayer; removeProgress?: () => void; status: BasemapLoadWatchdog };

/** Keep one loaded fallback while the replacement fills; never stack stale requests. */
export class GlobeBasemap {
  private active?: Entry;
  private pending?: Entry;
  private currentStatusKey?: string;

  constructor(private viewer: Pick<Viewer, "imageryLayers" | "scene">, private updateStatus: (phase: BasemapLoadPhase) => void = () => {}) {}

  set(descriptor: BasemapLayerDescriptor, retryKey = 0) {
    const key = `${basemapSourceKey(descriptor)}:${retryKey}`;
    this.currentStatusKey = key;
    if (this.pending?.key === key) {
      this.pending.layer.alpha = descriptor.opacity;
      this.pending.status.report();
      return;
    }
    this.removePending();
    if (this.active?.key === key) {
      this.active.layer.alpha = descriptor.opacity;
      this.active.status.report();
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
    const status = new BasemapLoadWatchdog(phase => {
      if (this.currentStatusKey === key) this.updateStatus(phase);
    });
    // Observe actual image completion, not request-queue emptiness or a rendered frame.
    const requestImage = provider.requestImage.bind(provider);
    provider.requestImage = (...args) => {
      const result = requestImage(...args);
      if (!result) return result;
      return Promise.resolve(result).then(image => {
        if (image) status.ready();
        return image;
      }, error => {
        status.failed();
        throw error;
      });
    };
    const entry: Entry = { key, layer: new ImageryLayer(provider, { alpha: descriptor.opacity }), status };
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
        this.active!.status.dispose();
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
    this.pending.status.dispose();
    this.viewer.imageryLayers.remove(this.pending.layer, true);
    this.pending = undefined;
  }

  destroy() {
    this.currentStatusKey = undefined;
    this.removePending();
    if (this.active) {
      this.active.status.dispose();
      this.viewer.imageryLayers.remove(this.active.layer, true);
    }
    this.active = undefined;
  }
}
