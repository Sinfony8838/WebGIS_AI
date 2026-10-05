import type ImageWrapper from "ol/Image";
import type { LayerRecord } from "../types";

export const POPULATION_SOURCE_COLORS = ["#fffcda", "#fceda1", "#fad277", "#f1ae4e", "#e1802d", "#c04f1e", "#912919", "#5c181c", "#36101c"];
export const POPULATION_OVERLAY_COLORS = ["#eee2f3", "#dfbde4", "#ce92d7", "#bc65c7", "#a943af", "#922996", "#751b7b", "#58135d", "#3d0d40"];
// At the existing 50% layer opacity, dense cells still retain at least 54% of the terrain.
export const POPULATION_OVERLAY_ALPHA = [0.2, 0.34, 0.5, 0.64, 0.74, 0.82, 0.88, 0.92, 0.92];
const colorNumber = (hex: string) => parseInt(hex.slice(1), 16);
const sourceBins = new Map(POPULATION_SOURCE_COLORS.map((color, index) => [colorNumber(color), index]));

export function hasPopulationOverlayStyle(layer: Pick<LayerRecord, "kind" | "metadata">): boolean {
  return layer.kind === "raster" && layer.metadata?.teaching_map_id === "worldpop_global_teacher"
    && layer.metadata.registration === "georeferenced_raster";
}

/** Restyle display pixels only, before reprojection; preserve density bins and nodata. */
export function restylePopulationPixels(pixels: Uint8ClampedArray, colors = POPULATION_OVERLAY_COLORS): void {
  const palette = colors.map(colorNumber);
  for (let offset = 0; offset < pixels.length; offset += 4) {
    if (!pixels[offset + 3]) continue;
    const bin = sourceBins.get((pixels[offset] << 16) | (pixels[offset + 1] << 8) | pixels[offset + 2]);
    if (bin === undefined) continue;
    const color = palette[bin];
    pixels[offset] = color >> 16;
    pixels[offset + 1] = (color >> 8) & 255;
    pixels[offset + 2] = color & 255;
    pixels[offset + 3] = Math.round(pixels[offset + 3] * POPULATION_OVERLAY_ALPHA[bin]);
  }
}

export function loadPopulationOverlay(wrapper: ImageWrapper, url: string): void {
  const target = wrapper.getImage() as HTMLImageElement;
  const original = new Image();
  original.crossOrigin = "use-credentials";
  const fail = () => { original.onload = original.onerror = null; target.src = "data:,"; };
  original.onerror = fail;
  original.onload = () => {
    try {
      const canvas = document.createElement("canvas");
      canvas.width = original.naturalWidth;
      canvas.height = original.naturalHeight;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) throw new Error("Canvas is unavailable");
      context.drawImage(original, 0, 0);
      const image = context.getImageData(0, 0, canvas.width, canvas.height);
      restylePopulationPixels(image.data);
      context.putImageData(image, 0, 0);
      target.src = canvas.toDataURL("image/png");
      original.onload = original.onerror = null;
    } catch { fail(); }
  };
  original.src = url;
}

export function populationOverlayLegend(layer: LayerRecord): Array<{ label: string; color: string }> {
  const legend = (layer.metadata.legend || []) as Array<{ label: string; color: string }>;
  return hasPopulationOverlayStyle(layer)
    ? legend.map(item => {
      const bin = sourceBins.get(colorNumber(item.color));
      return bin === undefined ? item : { ...item, color: POPULATION_OVERLAY_COLORS[bin] };
    }) : legend;
}
