import { transformExtent } from "ol/proj";
import { loadPopulationOverlay } from "./populationRaster";
import type { Options } from "ol/source/ImageStatic";

type Bounds = [number, number, number, number];
const projectionFor = (imageCrs: unknown) => imageCrs === "EPSG:4326" ? "EPSG:4326" : "EPSG:3857";

/** Bounds are geographic; image pixels may be geographic or already warped to Mercator. */
export function rasterSourceOptions(url: string, bounds: Bounds, imageCrs: unknown, populationOverlay = false): Options {
  const projection = projectionFor(imageCrs);
  return {
    url: `${url}${url.includes("?") ? "&" : "?"}canvas=1`,
    crossOrigin: "use-credentials",
    projection,
    ...(populationOverlay ? { imageLoadFunction: loadPopulationOverlay } : {}),
    imageExtent: projection === "EPSG:4326" ? bounds : transformExtent(bounds, "EPSG:4326", "EPSG:3857")
  };
}

// A CRS correction must replace the cached source even if its URL and bounds are unchanged.
export function rasterSourceKey(url: string, bounds: Bounds, imageCrs: unknown, populationOverlay = false): string {
  return `raster|${JSON.stringify([url, bounds, projectionFor(imageCrs), populationOverlay ? "population-terrain-balanced-v1" : "original"])}`;
}
