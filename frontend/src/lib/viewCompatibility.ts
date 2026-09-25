import type { BasemapPreset, LayerRecord } from "../types";

/** Only sources actually rendered by Map3DGlobe may trigger an automatic flip. */
export function globeCompatibility(baseMap: BasemapPreset | undefined, layers: LayerRecord[]): { ready: boolean; reason: string } {
  if (!baseMap || baseMap.layers.length !== 1 || baseMap.layers[0].kind !== "xyz" ||
      baseMap.layers[0].usable_in_3d === false || !baseMap.layers[0].urls.length) {
    return { ready: false, reason: "当前底图尚未完整适配 3D" };
  }
  const unsupported = layers.find(layer => layer.visible &&
    !(layer.kind === "vector" && ["upload", "output_artifact"].includes(layer.source)));
  if (unsupported) return { ready: false, reason: `“${unsupported.name}”尚未适配 3D` };
  return { ready: true, reason: "" };
}
