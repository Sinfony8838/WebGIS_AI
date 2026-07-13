import { useRef, useEffect, useCallback, useState, forwardRef, useImperativeHandle } from "react";

export type BrushTool = "freehand" | "line" | "rectangle" | "ellipse" | "arrow" | "eraser";

export interface BrushSettings {
  tool: BrushTool;
  color: string;
  lineWidth: number;
}

export interface BrushOverlayHandle {
  clear: () => void;
  undo: () => void;
  exportImage: () => string | null;
  loadImage: (dataUrl?: string | null) => void;
}

type Props = {
  active: boolean;
  settings: BrushSettings;
  onWheelZoom?: (event: WheelEvent) => void;
  onContentChange?: (hasContent: boolean) => void;
};

const MAX_UNDO_STEPS = 30;

export const BrushOverlay = forwardRef<BrushOverlayHandle, Props>(function BrushOverlay(
  { active, settings, onWheelZoom, onContentChange },
  ref
) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawingRef = useRef(false);
  const startPosRef = useRef<{ x: number; y: number } | null>(null);
  const snapshotRef = useRef<ImageData | null>(null);
  const undoStackRef = useRef<ImageData[]>([]);
  const [hasContent, setHasContent] = useState(false);
  const hasContentRef = useRef(false);

  const setContentState = useCallback(
    (next: boolean) => {
      hasContentRef.current = next;
      setHasContent(next);
      onContentChange?.(next);
    },
    [onContentChange]
  );

  const pushUndoSnapshot = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const snapshot = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const stack = undoStackRef.current;
    if (stack.length >= MAX_UNDO_STEPS) {
      stack.shift();
    }
    stack.push(snapshot);
  }, []);

  const updateHasContent = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    for (let i = 3; i < data.length; i += 4) {
      if (data[i] > 0) {
        setContentState(true);
        return;
      }
    }
    setContentState(false);
  }, [setContentState]);

  const clearCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    pushUndoSnapshot();
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    setContentState(false);
  }, [pushUndoSnapshot, setContentState]);

  const undoCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const stack = undoStackRef.current;
    const snapshot = stack.pop();
    if (snapshot) {
      ctx.putImageData(snapshot, 0, 0);
    } else {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    updateHasContent();
  }, [updateHasContent]);

  const exportImage = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !hasContentRef.current) return null;
    return canvas.toDataURL("image/png");
  }, []);

  const loadImage = useCallback(
    (dataUrl?: string | null) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      undoStackRef.current = [];
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (!dataUrl) {
        setContentState(false);
        return;
      }

      const image = new Image();
      image.onload = () => {
        const dpr = window.devicePixelRatio || 1;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(image, 0, 0, canvas.width / dpr, canvas.height / dpr);
        setContentState(true);
      };
      image.src = dataUrl;
    },
    [setContentState]
  );

  useImperativeHandle(ref, () => ({
    clear: clearCanvas,
    undo: undoCanvas,
    exportImage,
    loadImage
  }), [clearCanvas, undoCanvas, exportImage, loadImage]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const resizeCanvas = () => {
      const parent = canvas.parentElement;
      if (!parent) return;
      const dpr = window.devicePixelRatio || 1;
      const w = parent.clientWidth;
      const h = parent.clientHeight;
      if (canvas.width === w * dpr && canvas.height === h * dpr) return;

      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const prev =
        canvas.width > 0 && canvas.height > 0
          ? ctx.getImageData(0, 0, canvas.width, canvas.height)
          : null;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (prev) {
        ctx.putImageData(prev, 0, 0);
      }
    };

    resizeCanvas();
    const observer = new ResizeObserver(resizeCanvas);
    if (canvas.parentElement) {
      observer.observe(canvas.parentElement);
    }
    return () => observer.disconnect();
  }, []);

  const getPos = useCallback((e: MouseEvent | TouchEvent): { x: number; y: number } | null => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    let clientX: number, clientY: number;
    if ("touches" in e) {
      if (e.touches.length === 0) return null;
      clientX = e.touches[0].clientX;
      clientY = e.touches[0].clientY;
    } else {
      clientX = e.clientX;
      clientY = e.clientY;
    }
    const cssWidth = canvas.clientWidth || rect.width;
    const cssHeight = canvas.clientHeight || rect.height;
    const scaleX = rect.width && cssWidth ? rect.width / cssWidth : 1;
    const scaleY = rect.height && cssHeight ? rect.height / cssHeight : 1;
    return {
      x: (clientX - rect.left) / scaleX,
      y: (clientY - rect.top) / scaleY
    };
  }, []);

  const drawShape = useCallback(
    (start: { x: number; y: number }, end: { x: number; y: number }, tool: BrushTool) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      if (snapshotRef.current) {
        ctx.putImageData(snapshotRef.current, 0, 0);
      }

      ctx.save();
      ctx.strokeStyle = settings.color;
      ctx.lineWidth = settings.lineWidth;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";

      if (tool === "eraser") {
        ctx.globalCompositeOperation = "destination-out";
      }

      if (tool === "line" || tool === "eraser") {
        ctx.beginPath();
        ctx.moveTo(start.x, start.y);
        ctx.lineTo(end.x, end.y);
        ctx.stroke();
      } else if (tool === "rectangle") {
        ctx.beginPath();
        ctx.strokeRect(start.x, start.y, end.x - start.x, end.y - start.y);
      } else if (tool === "ellipse") {
        const cx = (start.x + end.x) / 2;
        const cy = (start.y + end.y) / 2;
        const rx = Math.abs(end.x - start.x) / 2;
        const ry = Math.abs(end.y - start.y) / 2;
        ctx.beginPath();
        ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
        ctx.stroke();
      } else if (tool === "arrow") {
        const dx = end.x - start.x;
        const dy = end.y - start.y;
        const angle = Math.atan2(dy, dx);
        const headLen = Math.max(10, settings.lineWidth * 3);

        ctx.beginPath();
        ctx.moveTo(start.x, start.y);
        ctx.lineTo(end.x, end.y);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(end.x, end.y);
        ctx.lineTo(
          end.x - headLen * Math.cos(angle - Math.PI / 6),
          end.y - headLen * Math.sin(angle - Math.PI / 6)
        );
        ctx.moveTo(end.x, end.y);
        ctx.lineTo(
          end.x - headLen * Math.cos(angle + Math.PI / 6),
          end.y - headLen * Math.sin(angle + Math.PI / 6)
        );
        ctx.stroke();
      }

      ctx.restore();
    },
    [settings]
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleMouseDown = (e: MouseEvent | TouchEvent) => {
      if (!active) return;
      e.preventDefault();
      const pos = getPos(e);
      if (!pos) return;

      pushUndoSnapshot();
      drawingRef.current = true;
      startPosRef.current = pos;

      if (settings.tool === "freehand" || settings.tool === "eraser") {
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        snapshotRef.current = ctx.getImageData(0, 0, canvas.width, canvas.height);
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(pos.x, pos.y);
        ctx.strokeStyle = settings.color;
        ctx.lineWidth = settings.lineWidth;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        if (settings.tool === "eraser") {
          ctx.globalCompositeOperation = "destination-out";
        }
        ctx.restore();
      } else {
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        snapshotRef.current = ctx.getImageData(0, 0, canvas.width, canvas.height);
      }
    };

    const handleMouseMove = (e: MouseEvent | TouchEvent) => {
      if (!drawingRef.current || !active) return;
      e.preventDefault();
      const pos = getPos(e);
      if (!pos) return;

      const start = startPosRef.current;
      if (!start) return;

      if (settings.tool === "freehand" || settings.tool === "eraser") {
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.save();
        ctx.strokeStyle = settings.color;
        ctx.lineWidth = settings.lineWidth;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        if (settings.tool === "eraser") {
          ctx.globalCompositeOperation = "destination-out";
        }
        ctx.beginPath();
        ctx.moveTo(start.x, start.y);
        ctx.lineTo(pos.x, pos.y);
        ctx.stroke();
        ctx.restore();
        startPosRef.current = pos;
      } else {
        drawShape(start, pos, settings.tool);
      }
    };

    const handleMouseUp = (e: MouseEvent | TouchEvent) => {
      if (!drawingRef.current) return;
      drawingRef.current = false;
      startPosRef.current = null;
      snapshotRef.current = null;
      setContentState(true);
    };

    canvas.addEventListener("mousedown", handleMouseDown);
    canvas.addEventListener("mousemove", handleMouseMove);
    canvas.addEventListener("mouseup", handleMouseUp);
    canvas.addEventListener("mouseleave", handleMouseUp);
    canvas.addEventListener("touchstart", handleMouseDown, { passive: false });
    canvas.addEventListener("touchmove", handleMouseMove, { passive: false });
    canvas.addEventListener("touchend", handleMouseUp);

    return () => {
      canvas.removeEventListener("mousedown", handleMouseDown);
      canvas.removeEventListener("mousemove", handleMouseMove);
      canvas.removeEventListener("mouseup", handleMouseUp);
      canvas.removeEventListener("mouseleave", handleMouseUp);
      canvas.removeEventListener("touchstart", handleMouseDown);
      canvas.removeEventListener("touchmove", handleMouseMove);
      canvas.removeEventListener("touchend", handleMouseUp);
    };
  }, [active, settings, getPos, pushUndoSnapshot, drawShape, setContentState]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleWheel = (event: WheelEvent) => {
      if (!active) return;
      onWheelZoom?.(event);
    };

    canvas.addEventListener("wheel", handleWheel, { passive: false });
    return () => {
      canvas.removeEventListener("wheel", handleWheel);
    };
  }, [active, onWheelZoom]);

  const cursor =
    settings.tool === "eraser"
      ? "cell"
      : settings.tool === "freehand"
        ? "crosshair"
        : "crosshair";

  return (
    <canvas
      ref={canvasRef}
      className={`brush-overlay ${active ? "brush-overlay--active" : ""}`}
      style={active ? { cursor } : undefined}
    />
  );
});
