import { describe, expect, it } from "vitest";
import { normalizeGlobeGeoJson } from "../lib/globeGeojson";

describe("historical workflow GeoJSON on the globe", () => {
  it("accepts QGIS WGS84 3D URNs without modifying the saved artifact", () => {
    const original = { type: "FeatureCollection", crs: { type: "name", properties: { name: "urn:ogc:def:crs:EPSG::4979" } },
      features: [{ type: "Feature", geometry: { type: "Point", coordinates: [137, 37, 12] }, properties: { mag: 5 } }] };
    const rendered = normalizeGlobeGeoJson(original);
    expect(rendered).not.toHaveProperty("crs");
    expect(rendered.features).toBe(original.features);
    expect(original.crs.properties.name).toBe("urn:ogc:def:crs:EPSG::4979");
  });

  it("does not discard a different CRS that requires coordinate transformation", () => {
    const projected = { type: "FeatureCollection", crs: { type: "name", properties: { name: "EPSG:3857" } }, features: [] };
    expect(normalizeGlobeGeoJson(projected)).toBe(projected);
  });
});
