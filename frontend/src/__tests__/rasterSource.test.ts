import { describe, expect, it } from "vitest";
import ImageStatic from "ol/source/ImageStatic";
import { transformExtent } from "ol/proj";
import { rasterSourceKey, rasterSourceOptions } from "../lib/rasterSource";

const worldPopBounds: [number, number, number, number] = [-180, -59.999999424, 179.99999856, 84];

describe("raster source projection", () => {
  it("keeps WorldPop pixels in their geographic CRS so OpenLayers reprojects them", () => {
    const source = new ImageStatic(rasterSourceOptions("/worldpop.png", worldPopBounds, "EPSG:4326"));
    expect(source.getProjection()?.getCode()).toBe("EPSG:4326");
    expect(source.getImageExtent()).toEqual(worldPopBounds);
  });

  it("preserves Mercator-registered textbook images and legacy records", () => {
    for (const crs of ["EPSG:3857", undefined]) {
      const source = new ImageStatic(rasterSourceOptions("/textbook.png", worldPopBounds, crs));
      expect(source.getProjection()?.getCode()).toBe("EPSG:3857");
      expect(source.getImageExtent()).toEqual(transformExtent(worldPopBounds, "EPSG:4326", "EPSG:3857"));
    }
  });

  it("invalidates the layer cache when only the image CRS is corrected", () => {
    const key = rasterSourceKey("/worldpop.png", worldPopBounds, undefined);
    expect(rasterSourceKey("/worldpop.png", worldPopBounds, "EPSG:4326")).not.toBe(key);
    expect(rasterSourceKey("/worldpop.png", worldPopBounds, "EPSG:3857")).toBe(key);
    expect(rasterSourceKey("/worldpop.png", [...worldPopBounds], "EPSG:4326"))
      .toBe(rasterSourceKey("/worldpop.png", worldPopBounds, "EPSG:4326"));
  });

  it("keeps authenticated canvas image loading and existing query parameters", () => {
    expect(rasterSourceOptions("/worldpop.png?version=2", worldPopBounds, "EPSG:4326"))
      .toMatchObject({ url: "/worldpop.png?version=2&canvas=1", crossOrigin: "use-credentials" });
    expect(rasterSourceOptions("/worldpop.png", worldPopBounds, "EPSG:4326").url).toBe("/worldpop.png?canvas=1");
  });
});
