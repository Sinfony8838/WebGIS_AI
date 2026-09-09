import { afterEach, describe, expect, it, vi } from "vitest";
import { captureMapSnapshot, resolveCanvasCssSize, resolveCanvasDrawSize } from "../mapScreenshot";

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

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


describe("map capture readiness", () => {
  it("reports an unloaded map instead of leaving the screenshot request pending", async () => {
    vi.useFakeTimers();
    const map = { once:vi.fn(),un:vi.fn(),renderSync:vi.fn() };
    const result = captureMapSnapshot(map as never);
    await vi.advanceTimersByTimeAsync(8000);
    expect(await result).toBe(""); expect(map.un).toHaveBeenCalledWith("rendercomplete", expect.any(Function));
  });
  it("takes legend context on the rendered frame and preserves HiDPI map pixels", async () => {
    vi.spyOn(window,"devicePixelRatio","get").mockReturnValue(2);
    const viewport = document.createElement("div"); viewport.innerHTML='<div class="ol-layer"><canvas width="800" height="600" style="transform:matrix(0.5,0,0,0.5,0,0)"></canvas></div>';
    let render!:()=>void;
    const map = {once:vi.fn((_event,listener)=>{render=listener;}),un:vi.fn(),getSize:()=>[400,300],getViewport:()=>viewport,renderSync:()=>render()};
    const context = {setTransform:vi.fn(),drawImage:vi.fn()};
    vi.spyOn(HTMLCanvasElement.prototype,"getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);
    const sizes:number[][]=[];
    vi.spyOn(HTMLCanvasElement.prototype,"toDataURL").mockImplementation(function(this:HTMLCanvasElement){sizes.push([this.width,this.height]);return "data:image/png;base64,map";});
    const freeze = vi.fn();
    expect(await captureMapSnapshot(map as never,freeze)).toContain("map");
    expect(freeze).toHaveBeenCalledTimes(1); expect(sizes).toEqual([[800,600]]);
    expect(context.setTransform).toHaveBeenCalledWith(1,0,0,1,0,0);
    expect(context.drawImage).toHaveBeenCalledWith(viewport.querySelector("canvas"),0,0,800,600,0,0,800,600);
  });
});
