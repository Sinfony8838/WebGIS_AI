import { afterEach, describe, expect, it, vi } from "vitest";
import type ImageWrapper from "ol/Image";
import type { LayerRecord } from "../types";
import { hasPopulationOverlayStyle, loadPopulationOverlay, populationOverlayLegend, POPULATION_SOURCE_COLORS, POPULATION_OVERLAY_COLORS, POPULATION_OVERLAY_ALPHA, restylePopulationPixels } from "../lib/populationRaster";

const rgb = (hex: string) => [parseInt(hex.slice(1,3),16), parseInt(hex.slice(3,5),16), parseInt(hex.slice(5,7),16)];
const layer = { kind: "raster", metadata: { teaching_map_id: "worldpop_global_teacher", registration: "georeferenced_raster", legend: POPULATION_SOURCE_COLORS.map((color,index) => ({ label: `bin ${index}`, color })) } } as LayerRecord;
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("balanced population overlay", () => {
  it("preserves every density bin while reducing opacity by density", () => {
    const pixels = new Uint8ClampedArray(POPULATION_SOURCE_COLORS.flatMap(color => [...rgb(color),255]));
    restylePopulationPixels(pixels);
    for (let index = 0; index < 9; index++) {
      expect([...pixels.slice(index * 4,index * 4 + 3)]).toEqual(rgb(POPULATION_OVERLAY_COLORS[index]));
      expect(pixels[index * 4 + 3]).toBe(Math.round(255 * POPULATION_OVERLAY_ALPHA[index]));
    }
    expect(Math.max(...POPULATION_OVERLAY_ALPHA) * .5).toBeLessThanOrEqual(.46);
    expect(POPULATION_OVERLAY_ALPHA[0]).toBeLessThan(POPULATION_OVERLAY_ALPHA[4]);
  });

  it("keeps nodata and unrecognized pixels untouched, and respects partial source alpha", () => {
    const pixels = new Uint8ClampedArray([...rgb(POPULATION_SOURCE_COLORS[0]),0, 20,30,40,255, ...rgb(POPULATION_SOURCE_COLORS[8]),100]);
    restylePopulationPixels(pixels);
    expect([...pixels.slice(0,8)]).toEqual([...rgb(POPULATION_SOURCE_COLORS[0]),0,20,30,40,255]);
    expect(pixels[11]).toBe(92);
  });

  it("changes the matching legend colors while retaining all threshold labels and source metadata", () => {
    const before = JSON.stringify(layer.metadata);
    expect(populationOverlayLegend(layer)).toEqual(POPULATION_OVERLAY_COLORS.map((color,index) => ({ label: `bin ${index}`,color })));
    expect(JSON.stringify(layer.metadata)).toBe(before);
    const textbook = { ...layer, metadata: { ...layer.metadata, teaching_map_id: "finland_terrain" } };
    expect(populationOverlayLegend(textbook)).toEqual(layer.metadata.legend);
    expect(hasPopulationOverlayStyle(textbook)).toBe(false);
    expect(hasPopulationOverlayStyle({ ...layer, kind: "vector" })).toBe(false);
  });

  it("loads authenticated pixels and applies the display palette before delivering the image to OL", () => {
    const original = { crossOrigin: "",src: "",naturalWidth: 1,naturalHeight: 1,onload: null as (()=>void)|null,onerror: null as (()=>void)|null };
    vi.stubGlobal("Image",vi.fn(() => original));
    const pixels = new Uint8ClampedArray([...rgb(POPULATION_SOURCE_COLORS[4]),255]);
    const context = { drawImage:vi.fn(), getImageData:vi.fn(() => ({data:pixels})),putImageData:vi.fn() };
    const canvas = { width:0,height:0,getContext:vi.fn(() => context),toDataURL:vi.fn(() => "data:image/png;base64,styled") };
    vi.spyOn(document,"createElement").mockReturnValue(canvas as unknown as HTMLCanvasElement);
    const target = { src:"" };
    loadPopulationOverlay({ getImage:()=>target } as unknown as ImageWrapper,"/worldpop.png?canvas=1");
    expect(original.crossOrigin).toBe("use-credentials");
    expect(original.src).toBe("/worldpop.png?canvas=1");
    original.onload!();
    expect([...pixels.slice(0,3)]).toEqual(rgb(POPULATION_OVERLAY_COLORS[4]));
    expect(target.src).toBe("data:image/png;base64,styled");
    expect(original.onload).toBeNull();
  });

  it("propagates download and canvas failures to the OL image error path", () => {
    const original = { src:"",onload:null as (()=>void)|null,onerror:null as (()=>void)|null };
    vi.stubGlobal("Image",vi.fn(() => original));
    const target = { src:"" };
    loadPopulationOverlay({ getImage:()=>target } as unknown as ImageWrapper,"/missing.png");
    original.onerror!();
    expect(target.src).toBe("data:,");
    expect(original.onerror).toBeNull();
    vi.spyOn(document,"createElement").mockReturnValue({ getContext:()=>null } as unknown as HTMLCanvasElement);
    loadPopulationOverlay({ getImage:()=>target } as unknown as ImageWrapper,"/worldpop.png");
    original.onload!();
    expect(target.src).toBe("data:,");
  });
});
