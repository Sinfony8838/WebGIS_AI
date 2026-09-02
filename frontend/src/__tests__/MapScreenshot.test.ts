import { describe, expect, it, vi } from "vitest";
import { resolveCanvasCssSize, resolveCanvasDrawSize } from "../mapScreenshot";

describe("map screenshot canvas sizing", () => {
  it("uses CSS pixels for a HiDPI OpenLayers canvas", () => {
    const canvas = document.createElement("canvas");
    canvas.width = 800;
    canvas.height = 600;
    canvas.style.width = "400px";
    canvas.style.height = "300px";
    vi.spyOn(window, "devicePixelRatio", "get").mockReturnValue(2);
    expect(resolveCanvasCssSize(canvas)).toEqual({ width: 400, height: 300 });
    expect(resolveCanvasDrawSize(canvas, null)).toEqual({ width: 400, height: 300 });
    expect(resolveCanvasDrawSize(canvas, [0.5, 0, 0, 0.5, 0, 0])).toEqual({ width: 800, height: 600 });
  });
});
