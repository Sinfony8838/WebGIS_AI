import { describe, expect, it } from "vitest";
import { globeCompatibility } from "../lib/viewCompatibility";
import type { BasemapPreset, LayerRecord } from "../types";

const base = (id: string, layers = 1): BasemapPreset => ({
  id, title: id, description: "", provider: "test", type: "stack",
  layers: Array.from({ length: layers }, (_, index) => ({
    layer_id: `layer_${index}`, title: "layer", kind: "xyz", urls: ["https://example.test/{z}/{x}/{y}.png"],
    opacity: 1, z_index: index + 1, usable_in_3d: true
  }))
});

describe("automatic globe compatibility", () => {
  it("accepts tested single raster basemaps such as NASA nightlights", () => {
    expect(globeCompatibility(base("nasa_nightlights_2016"), []).ready).toBe(true);
    expect(globeCompatibility(base("nasa_population_2020"), []).ready).toBe(true);
  });
  it("keeps 2D for a partial basemap stack, weather tiles, or unsupported thematic layer", () => {
    expect(globeCompatibility(base("amap_imagery", 2), []).ready).toBe(false);
    const weather = base("weather"); weather.layers[0].usable_in_3d = false;
    expect(globeCompatibility(weather, []).ready).toBe(false);
    const teaching = { visible: true, kind: "raster", source: "teaching_map", name: "教学地图" } as LayerRecord;
    expect(globeCompatibility(base("nasa_nightlights_2016"), [teaching]).reason).toContain("教学地图");
  });
  it("allows vector uploads already rendered by the 3D globe", () => {
    const upload = { visible: true, kind: "vector", source: "upload" } as LayerRecord;
    expect(globeCompatibility(base("nasa_nightlights_2016"), [upload]).ready).toBe(true);
  });
});
