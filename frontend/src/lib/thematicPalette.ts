import { asArray } from "ol/color";
import type { LayerRecord } from "../types";
import { rankColor } from "./populationVisual";

/** Recolor a sequential scale without changing its classes, order or missing values. */
export function thematicColor(layer: LayerRecord | undefined, original: string): string {
  const requested = (layer?.metadata?.style_overrides as Record<string, unknown> | undefined)?.fillColor;
  if (typeof requested !== "string" || original.toLowerCase() === "#dbe1e6") return original;
  try {
    const rgb = asArray(requested).slice(0, 3).map(v => v / 255);
    const source = asArray(original).slice(0, 3).map(v => v / 255);
    const hi = Math.max(...rgb), lo = Math.min(...rgb), delta = hi - lo;
    const targetLight = (hi + lo) / 2;
    const saturation = delta === 0 ? 0 : delta / (1 - Math.abs(2 * targetLight - 1));
    const light = (Math.max(...source) + Math.min(...source)) / 2;
    const chroma = (1 - Math.abs(2 * light - 1)) * saturation;
    return "#" + rgb.map(v => Math.round(255 * (light - chroma / 2 + (delta ? (v - lo) / delta : 0) * chroma)).toString(16).padStart(2, "0")).join("");
  } catch { return original; }
}

export function hasThematicScale(layer: LayerRecord): boolean {
  return Boolean(layer.metadata?.visualization || layer.metadata?.workflow_style ||
    ["builtin_population_regions", "builtin_population_density"].includes(layer.layer_id) ||
    ["shanghai_population_density", "shanghai_age_60_plus_2020"].includes(String(layer.metadata?.catalog_id)));
}

export function rankLegend(layer: LayerRecord) {
  const visualization = layer.metadata?.visualization as { items?: Array<{ rank: number; name: string; value: number; unit?: string }>; unit?: string } | undefined;
  const items = visualization?.items || [];
  return [...items].sort((a, b) => a.rank - b.rank).map(item => ({
    ...item, color: thematicColor(layer, rankColor(item.rank, items.length)),
    label: `${Number(item.value).toLocaleString("zh-CN")} ${item.unit || visualization?.unit || ""}`
  }));
}
