import { describe, expect, it } from "vitest";
import type { LayerRecord } from "../types";
import { visualQueryFocusRecord } from "../lib/visualQueryFocus";

const xian = { type: "Feature", properties: { rank: 8, name: "西安市", adm_code: "610100" },
  geometry: { type: "Polygon", coordinates: [[[108, 34], [109, 34], [109, 35], [108, 34]]] } };
const wuhan = { ...xian, properties: { rank: 11, name: "武汉市", adm_code: "420100" } };
const layer = { layer_id: "ranking", kind: "vector", data: { type: "FeatureCollection", features: [wuhan, xian] },
  metadata: { visualization: { items: [{ rank: 8 }, { rank: 11 }] } } } as unknown as LayerRecord;

describe("visual query city focus", () => {
  it("selects the city by administrative code rather than row position or changing rank", () => {
    const before = JSON.stringify(layer);
    const focused = visualQueryFocusRecord({ rank: 1, name: "新排序", adm_code: "610100" }, layer);
    expect(focused?.data.features).toEqual([xian]);
    expect(focused?.layer_id).toBe("ranking");
    expect(JSON.stringify(layer)).toBe(before);
    expect(layer.data.features).toHaveLength(2);
  });
  it("matches both rank and city name when older rows lack an administrative code", () => {
    expect(visualQueryFocusRecord({ rank: 8, name: "西安市" }, layer)?.data.features).toEqual([xian]);
    expect(visualQueryFocusRecord({ rank: 8, name: "武汉市" }, layer)).toBeNull();
  });
  it("does not focus an unrelated city when a code is missing or geometry is absent", () => {
    expect(visualQueryFocusRecord({ rank: 8, adm_code: "missing" }, layer)).toBeNull();
    expect(visualQueryFocusRecord({ rank: 8 }, { ...layer, data: { features: [{ ...xian, geometry: null }] } })).toBeNull();
    expect(visualQueryFocusRecord({ rank: 8 }, { ...layer, kind: "raster" })).toBeNull();
  });
});
