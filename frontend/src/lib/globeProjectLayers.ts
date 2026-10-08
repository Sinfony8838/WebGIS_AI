import * as Cesium from "cesium";
import type { LayerRecord } from "../types";
import { normalizeGlobeGeoJson } from "./globeGeojson";
import { applyCesiumVectorStyle } from "./vectorStyle";

type Host = Pick<Cesium.Viewer, "dataSources" | "isDestroyed" | "scene">;
type Loader = (data: Record<string, unknown>) => Promise<Cesium.GeoJsonDataSource>;
type Entry = {
  layer: LayerRecord;
  geometry: string;
  source?: Cesium.GeoJsonDataSource;
  style?: string;
  phase: "loading" | "ready" | "adding" | "attached";
};

function geometryKey(layer: LayerRecord): string {
  const revision = layer.data_rev;
  // Older clients without a revision still detect actual payload changes.
  return JSON.stringify([layer.kind, layer.source,
    typeof revision === "number" && Number.isInteger(revision) && revision >= 0
      ? ["revision", revision] : ["legacy", layer.data]]);
}
function styleKey(layer: LayerRecord): string {
  const visualization = layer.metadata?.visualization as { items?: unknown[] } | undefined;
  return JSON.stringify([layer.style, layer.opacity, layer.metadata?.catalog_id,
    !!visualization, visualization?.items?.length, layer.data.features instanceof Array ? layer.data.features.length : 0]);
}
function eligible(layer: LayerRecord) {
  return layer.kind === "vector" && ["upload", "output_artifact"].includes(layer.source);
}

/** Own only project vectors. Camera, imagery, urban and thematic sources stay independent. */
export class GlobeProjectLayers {
  private entries = new Map<string, Entry>();
  private wanted = new Map<string, LayerRecord>();
  private scope = "";
  private visible = false;
  private disposed = false;
  private order = "";

  constructor(
    private host: Host,
    private error: (name: string, message: string) => void = () => {},
    private load: Loader = data => Cesium.GeoJsonDataSource.load(normalizeGlobeGeoJson(data), { clampToGround: true }),
    private apply: typeof applyCesiumVectorStyle = applyCesiumVectorStyle
  ) {}

  sync(scope: string, layers: LayerRecord[], visible: boolean) {
    if (this.disposed || this.host.isDestroyed()) return;
    if (this.scope !== scope) {
      this.clear();
      this.scope = scope;
    }
    this.visible = visible;
    this.wanted = new Map(layers.filter(eligible).map(layer => [layer.layer_id, layer]));
    for (const [id, entry] of this.entries) {
      if (!this.wanted.has(id)) this.remove(id, entry);
      else if (!visible && entry.source) entry.source.show = false;
    }
    // Coalesce hidden updates without loading GeoJSON or applying per-feature styles.
    if (!visible) return;
    for (const [id, layer] of this.wanted) {
      const geometry = geometryKey(layer);
      let entry = this.entries.get(id);
      if (entry && entry.geometry !== geometry) {
        this.remove(id, entry);
        entry = undefined;
      }
      if (entry) {
        entry.layer = layer;
        if (entry.source) this.update(entry);
      } else if (layer.visible) {
        entry = { layer, geometry, phase: "loading" };
        this.entries.set(id, entry);
        this.start(id, entry);
      }
    }
    this.sort();
    this.host.scene.requestRender();
  }

  private current(id: string, entry: Entry) {
    return !this.disposed && !this.host.isDestroyed() && this.entries.get(id) === entry;
  }

  private start(id: string, entry: Entry) {
    // Catch synchronous loader errors as well as asynchronous parsing failures.
    void Promise.resolve().then(() => {
      if (!this.current(id, entry)) return undefined;
      if (!this.visible || !this.wanted.get(id)?.visible) { this.remove(id, entry); return undefined; }
      return this.load(entry.layer.data);
    }).then(source => {
      if (!source) return;
      if (!this.current(id, entry)) { this.release(source); return; }
      entry.source = source;
      entry.phase = "ready";
      source.show = false;
      // A load already running on hide may finish; it stays unattached until re-show.
      if (this.visible) this.update(entry);
    }).catch(error => this.fail(id, entry, error));
  }

  private update(entry: Entry) {
    const source = entry.source!;
    try {
      const key = styleKey(entry.layer);
      if (entry.style !== key) {
        this.apply(source, entry.layer);
        entry.style = key;
      }
      source.show = entry.phase === "attached" && entry.layer.visible;
      if (entry.phase === "ready" && entry.layer.visible) {
        entry.phase = "adding";
        // Cesium add is asynchronous even for a fully loaded source.
        void this.host.dataSources.add(source).then(() => {
          if (!this.current(entry.layer.layer_id, entry)) { this.release(source); return; }
          entry.phase = "attached";
          if (!this.visible) { source.show = false; return; }
          this.update(entry);
          this.sort(true);
          this.host.scene.requestRender();
        }).catch(error => this.fail(entry.layer.layer_id, entry, error));
      }
    } catch (error) { this.fail(entry.layer.layer_id, entry, error); }
  }

  private fail(id: string, entry: Entry, error: unknown) {
    if (!this.current(id, entry)) return;
    this.remove(id, entry);
    if (this.visible && this.wanted.get(id)?.visible) this.error(entry.layer.name, String(error));
    // A later snapshot may retry; never create an automatic retry loop.
  }

  private sort(force = false) {
    const ordered = [...this.wanted.values()].sort((a, b) => a.z_index - b.z_index);
    const key = JSON.stringify(ordered.map(layer => [layer.layer_id, layer.z_index]));
    if (!force && key === this.order) return;
    this.order = key;
    for (const layer of ordered) {
      const source = this.entries.get(layer.layer_id)?.source;
      if (source && this.host.dataSources.contains(source)) this.host.dataSources.raiseToTop(source);
    }
  }

  private release(source: Cesium.GeoJsonDataSource) {
    if (!this.host.isDestroyed()) this.host.dataSources.remove(source, true);
    // GeoJsonDataSource has no destroy(): also release stale unattached entity collections.
    source.entities.removeAll();
  }

  private remove(id: string, entry: Entry) {
    this.entries.delete(id);
    if (entry.source) this.release(entry.source);
  }

  private clear() {
    for (const [id, entry] of this.entries) this.remove(id, entry);
    this.wanted.clear();
    this.order = "";
  }

  destroy() {
    if (this.disposed) return;
    this.disposed = true;
    this.clear();
  }
}
