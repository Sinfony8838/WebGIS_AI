import type { LayerRecord } from "../types";

type RankedItem = { rank: number; name?: string; adm_code?: string };

/** Build a temporary focus record; never replace the full ranking layer. */
export function visualQueryFocusRecord(item: RankedItem, layer: LayerRecord): LayerRecord | null {
  if (layer.kind !== "vector" || !Array.isArray(layer.data.features)) return null;
  const feature = layer.data.features.find((candidate) => {
    if (!candidate || typeof candidate !== "object") return false;
    const properties = candidate.properties;
    if (!properties || typeof properties !== "object") return false;
    if (item.adm_code) return String(properties.adm_code) === item.adm_code;
    return properties.rank === item.rank && (!item.name || properties.name === item.name);
  });
  if (!feature?.geometry) return null;
  return { ...layer, data: { ...layer.data, features: [feature] } };
}
