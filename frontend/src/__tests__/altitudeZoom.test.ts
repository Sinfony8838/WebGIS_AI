import { describe, expect, it } from "vitest";
import {
  altitudeToZoom,
  zoomToAltitude,
  GLOBE_TO_PLANE_ALTITUDE_THRESHOLD,
  PLANE_TO_GLOBE_ZOOM_THRESHOLD
} from "../lib/altitudeZoom";

describe("altitudeToZoom / zoomToAltitude", () => {
  it("returns 0 for non-finite or non-positive altitudes", () => {
    expect(altitudeToZoom(0)).toBe(0);
    expect(altitudeToZoom(-1)).toBe(0);
    expect(altitudeToZoom(Number.NaN)).toBe(0);
  });

  it("is monotonic — higher altitude → lower zoom", () => {
    const lowAlt = altitudeToZoom(100_000);
    const midAlt = altitudeToZoom(1_000_000);
    const highAlt = altitudeToZoom(10_000_000);
    expect(lowAlt).toBeGreaterThan(midAlt);
    expect(midAlt).toBeGreaterThan(highAlt);
  });

  it("round-trips within 0.01 zoom for typical altitudes", () => {
    for (const altitude of [200_000, 800_000, 3_000_000, 12_000_000]) {
      const zoom = altitudeToZoom(altitude);
      const back = zoomToAltitude(zoom);
      const relativeError = Math.abs(back - altitude) / altitude;
      expect(relativeError).toBeLessThan(0.001);
    }
  });

  it("clamps zoom into OpenLayers usable range [0, 22]", () => {
    expect(altitudeToZoom(1)).toBeLessThanOrEqual(22);
    expect(altitudeToZoom(1e15)).toBeGreaterThanOrEqual(0);
  });

  it("places the globe→plane threshold roughly at OL zoom 7-9", () => {
    const zoom = altitudeToZoom(GLOBE_TO_PLANE_ALTITUDE_THRESHOLD);
    expect(zoom).toBeGreaterThan(7);
    expect(zoom).toBeLessThan(9);
  });

  it("places the plane→globe threshold roughly at altitude > 8000km", () => {
    const altitude = zoomToAltitude(PLANE_TO_GLOBE_ZOOM_THRESHOLD);
    expect(altitude).toBeGreaterThan(8_000_000);
    expect(altitude).toBeLessThan(20_000_000);
  });

  it("handles edge zooms gracefully", () => {
    expect(zoomToAltitude(0)).toBeGreaterThan(0);
    expect(zoomToAltitude(22)).toBeGreaterThan(0);
    expect(zoomToAltitude(Number.NaN)).toBeGreaterThan(0);
  });
});
