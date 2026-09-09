import type View from "ol/View";
import { unByKey } from "ol/Observable";
import { toLonLat } from "ol/proj";

export interface PlaneViewState {
  lon: number;
  lat: number;
  zoom: number;
}

// Bind for the lifetime of the map, including when the 2D canvas is hidden.
export function observePlaneView(view: View, publish: (state: PlaneViewState) => void): () => void {
  const sync = () => {
    const center = view.getCenter();
    const zoom = view.getZoom();
    if (!center || zoom === undefined) return;
    const [lon, lat] = toLonLat(center, view.getProjection());
    if ([lon, lat, zoom].every(Number.isFinite)) publish({ lon, lat, zoom });
  };
  const keys = [view.on("change:center", sync), view.on("change:resolution", sync)];
  sync();
  return () => unByKey(keys);
}
