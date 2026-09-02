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
  const cssSize = resolveCanvasCssSize(sourceCanvas);
  const scaleX = transform?.length === 6 ? Math.hypot(transform[0], transform[1]) : 1;
  const scaleY = transform?.length === 6 ? Math.hypot(transform[2], transform[3]) : 1;
  const safeScaleX = scaleX > 0 ? scaleX : 1;
  const safeScaleY = scaleY > 0 ? scaleY : 1;
  const transformAlreadyMatchesCss =
    Math.abs(sourceCanvas.width * safeScaleX - cssSize.width) <= 1 &&
    Math.abs(sourceCanvas.height * safeScaleY - cssSize.height) <= 1;
  return transformAlreadyMatchesCss
    ? { width: sourceCanvas.width, height: sourceCanvas.height }
    : { width: cssSize.width / safeScaleX, height: cssSize.height / safeScaleY };
}
