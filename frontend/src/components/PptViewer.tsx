import { type MutableRefObject, useState, useEffect, useRef, useCallback } from "react";
import type { SlideContent } from "../types";
import { BrushOverlay, type BrushOverlayHandle, type BrushSettings } from "./BrushOverlay";

type Props = {
  open: boolean;
  onExpand: () => void;
  onCollapse: () => void;
  onRemove: () => void;
  slides: SlideContent[];
  fileName: string;
  brushActive?: boolean;
  brushSettings?: BrushSettings;
  brushOverlayRef?: MutableRefObject<BrushOverlayHandle | null>;
  onBrushContentChange?: (hasContent: boolean) => void;
};

const EMU_PER_PX = 914400 / 96;

export function PptViewer({
  open,
  onExpand,
  onCollapse,
  onRemove,
  slides,
  fileName,
  brushActive = false,
  brushSettings,
  brushOverlayRef,
  onBrushContentChange
}: Props) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [scale, setScale] = useState(1);
  const stageRef = useRef<HTMLDivElement>(null);
  const annotationImagesRef = useRef<Record<number, string>>({});

  const slide = slides[currentIndex];
  const slideW = slide ? slide.width / EMU_PER_PX : 960;
  const slideH = slide ? slide.height / EMU_PER_PX : 540;

  const recalcScale = useCallback(() => {
    if (!stageRef.current || !slide) return;
    const { clientWidth, clientHeight } = stageRef.current;
    const padX = 32;
    const padY = 32;
    const scaleX = (clientWidth - padX) / slideW;
    const scaleY = (clientHeight - padY) / slideH;
    setScale(Math.min(1, scaleX, scaleY));
  }, [slideW, slideH, slide]);

  const saveCurrentAnnotation = useCallback(() => {
    const brush = brushOverlayRef?.current;
    if (!brush) return;
    const dataUrl = brush.exportImage();
    if (dataUrl) {
      annotationImagesRef.current[currentIndex] = dataUrl;
    } else {
      delete annotationImagesRef.current[currentIndex];
    }
  }, [brushOverlayRef, currentIndex]);

  const restoreAnnotation = useCallback(
    (index: number) => {
      const brush = brushOverlayRef?.current;
      if (!brush) return;
      brush.loadImage(annotationImagesRef.current[index] ?? null);
    },
    [brushOverlayRef]
  );

  const goToSlide = useCallback(
    (nextIndex: number) => {
      const clamped = Math.max(0, Math.min(nextIndex, slides.length - 1));
      if (clamped === currentIndex) return;
      saveCurrentAnnotation();
      setCurrentIndex(clamped);
    },
    [currentIndex, saveCurrentAnnotation, slides.length]
  );

  const handleCollapse = useCallback(() => {
    saveCurrentAnnotation();
    onCollapse();
  }, [onCollapse, saveCurrentAnnotation]);

  const handleRemove = useCallback(() => {
    annotationImagesRef.current = {};
    onRemove();
  }, [onRemove]);

  useEffect(() => {
    if (!open) return;
    recalcScale();
    window.addEventListener("resize", recalcScale);
    return () => window.removeEventListener("resize", recalcScale);
  }, [open, recalcScale]);

  useEffect(() => {
    annotationImagesRef.current = {};
    setCurrentIndex(0);
  }, [slides]);

  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => restoreAnnotation(currentIndex));
    return () => window.cancelAnimationFrame(frame);
  }, [currentIndex, open, restoreAnnotation, slides]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === " ") {
        e.preventDefault();
        goToSlide(currentIndex + 1);
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        goToSlide(currentIndex - 1);
      }
      if (e.key === "Escape") {
        handleCollapse();
      }
      if (e.key === "Home") {
        goToSlide(0);
      }
      if (e.key === "End") {
        goToSlide(slides.length - 1);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [currentIndex, goToSlide, handleCollapse, open, slides.length]);

  if (slides.length === 0) return null;

  if (!open) {
    return (
      <div className="ppt-viewer-dock" role="group" aria-label="已导入 PPT">
        <button type="button" className="ppt-viewer-dock-main" onClick={onExpand}>
          <span className="ppt-viewer-dock-badge">PPT</span>
          <span className="ppt-viewer-dock-title">{fileName}</span>
          <span className="ppt-viewer-dock-meta">
            {currentIndex + 1} / {slides.length}
          </span>
        </button>
        <button type="button" className="ppt-viewer-dock-remove" onClick={handleRemove} aria-label="移除 PPT">
          ×
        </button>
      </div>
    );
  }

  return (
    <div className={`ppt-viewer-backdrop ${brushActive ? "ppt-viewer-backdrop--brush" : ""}`}>
      <div className="ppt-viewer-header">
        <span className="ppt-viewer-filename">{fileName}</span>
        <span className="ppt-viewer-counter">
          {currentIndex + 1} / {slides.length}
        </span>
        <div className="ppt-viewer-controls">
          <button type="button" onClick={handleCollapse}>
            收起
          </button>
          <button type="button" onClick={handleRemove}>
            移除
          </button>
        </div>
      </div>

      <div className="ppt-viewer-stage" ref={stageRef}>
        <div
          className="ppt-viewer-slide"
          style={{
            width: slideW,
            height: slideH,
            transform: `scale(${scale})`,
            background: slide?.imageUrl ? "transparent" : slide?.bgColor || "#ffffff",
          }}
        >
          {slide?.imageUrl ? (
            <img
              src={slide.imageUrl}
              alt={`幻灯片 ${currentIndex + 1}`}
              className="ppt-viewer-slide-image"
              draggable={false}
            />
          ) : (
            <div dangerouslySetInnerHTML={{ __html: slide?.html ?? "" }} />
          )}
          {brushSettings ? (
            <BrushOverlay
              key={`ppt-brush-${currentIndex}`}
              ref={brushOverlayRef}
              active={brushActive}
              settings={brushSettings}
              onContentChange={onBrushContentChange}
            />
          ) : null}
        </div>
      </div>

      <div className="ppt-viewer-nav">
        <button
          type="button"
          disabled={currentIndex === 0}
          onClick={() => goToSlide(currentIndex - 1)}
        >
          上一页
        </button>
        <div className="ppt-viewer-thumbs">
          {slides.map((_, i) => (
            <button
              key={i}
              type="button"
              className={i === currentIndex ? "active" : ""}
              onClick={() => goToSlide(i)}
            >
              {i + 1}
            </button>
          ))}
        </div>
        <button
          type="button"
          disabled={currentIndex === slides.length - 1}
          onClick={() => goToSlide(currentIndex + 1)}
        >
          下一页
        </button>
      </div>
    </div>
  );
}
