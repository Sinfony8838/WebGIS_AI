import type Map from "ol/Map";
import { drawSnapshotInk } from "./lib/snapshotDocument";

export function resolveCanvasCssSize(sourceCanvas: HTMLCanvasElement): { width: number; height: number } {
  const computed = window.getComputedStyle(sourceCanvas);
  const computedWidth = Number.parseFloat(computed.width);
  const computedHeight = Number.parseFloat(computed.height);
  const pixelRatio = window.devicePixelRatio || 1;
  return {
    width: computedWidth > 0 ? computedWidth : sourceCanvas.clientWidth || sourceCanvas.width / pixelRatio,
    height: computedHeight > 0 ? computedHeight : sourceCanvas.clientHeight || sourceCanvas.height / pixelRatio
  };
}

export function resolveCanvasDrawSize(
  sourceCanvas: HTMLCanvasElement,
  transform: number[] | null
): { width: number; height: number } {
  // OpenLayers' matrix already maps native canvas pixels to viewport pixels.
  // Computed width without an explicit CSS width is the native width, not the
  // post-transform width; dividing it by the matrix scale would scale twice.
  return transform?.length === 6
    ? { width: sourceCanvas.width, height: sourceCanvas.height }
    : resolveCanvasCssSize(sourceCanvas);
}


export function captureMapSnapshot(map: Map, freezeDetails?: () => void): Promise<string> {
  return new Promise((resolve) => {
    let finished = false, timer = 0;
    const finish = (value: string) => {
      if (finished) return;
      finished = true; clearTimeout(timer); map.un("rendercomplete", render); resolve(value);
    };
    const render = () => {
      try {
        const size = map.getSize();
        if (!size) { finish(""); return; }
        freezeDetails?.();
        const ratio = window.devicePixelRatio || 1;
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(size[0] * ratio); canvas.height = Math.round(size[1] * ratio);
        const context = canvas.getContext("2d");
        if (!context) { finish(""); return; }
        const canvases = Array.from(map.getViewport().querySelectorAll<HTMLCanvasElement>(".ol-layer canvas, canvas.ol-layer"));
        for (const sourceCanvas of canvases) {
          if (!sourceCanvas.width || !sourceCanvas.height) continue;
          const opacity = Number(sourceCanvas.parentElement?.style.opacity || "1");
          context.globalAlpha = Number.isFinite(opacity) ? opacity : 1;
          const values = sourceCanvas.style.transform.replace("matrix(", "").replace(")", "").split(",").map(Number);
          const matrix = values.length === 6 && values.every(Number.isFinite) ? values : null;
          if (matrix) context.setTransform(ratio * matrix[0], ratio * matrix[1], ratio * matrix[2], ratio * matrix[3], ratio * matrix[4], ratio * matrix[5]);
          else context.setTransform(ratio, 0, 0, ratio, 0, 0);
          const drawSize = resolveCanvasDrawSize(sourceCanvas, matrix);
          context.drawImage(sourceCanvas, 0, 0, sourceCanvas.width, sourceCanvas.height, 0, 0, drawSize.width, drawSize.height);
        }
        context.setTransform(ratio, 0, 0, ratio, 0, 0); context.globalAlpha = 1;
        drawSnapshotInk(context, document.querySelector<HTMLCanvasElement>('[data-testid="map-brush-overlay"]'), map.getViewport().getBoundingClientRect());
        finish(canvas.toDataURL("image/png"));
      } catch { finish(""); }
    };
    map.once("rendercomplete", render);
    timer = window.setTimeout(() => finish(""), 8000);
    map.renderSync();
  });
}
