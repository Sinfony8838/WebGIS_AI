import { type MutableRefObject, useState, useEffect, useRef, useCallback, useMemo } from "react";
import type { SlideContent } from "../types";
import { BrushOverlay, type BrushOverlayHandle, type BrushSettings } from "./BrushOverlay";
import { isEditableKeyboardTarget, isInteractiveKeyboardTarget } from "../lib/keyboard";
import { BrushHistory } from "../lib/brushHistory";
import "./PptViewer.css";

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
  onBrushUndoChange?: (canUndo: boolean) => void;
  onExitBrush?: () => void;
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
  onBrushContentChange,
  onBrushUndoChange,
  onExitBrush
}: Props) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [scale, setScale] = useState(1);
  const stageRef = useRef<HTMLDivElement>(null);
  const annotationHistory = useMemo(() => new BrushHistory(30), [slides]);

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
    // Finish a stroke if a page shortcut was used before pointer-up.
    brushOverlayRef?.current?.exportImage();
  }, [brushOverlayRef]);

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
    onRemove();
  }, [onRemove]);

  useEffect(() => {
    if (!open) return;
    recalcScale();
    window.addEventListener("resize", recalcScale);
    return () => window.removeEventListener("resize", recalcScale);
  }, [open, recalcScale]);

  useEffect(() => {
    setCurrentIndex(0);
  }, [slides]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.isComposing || e.keyCode === 229 || e.metaKey || e.ctrlKey || e.altKey
        || isEditableKeyboardTarget(e.target)) return;
      if (e.key === "Escape") {
        // A held Escape must not exit drawing and then collapse the deck on its next repeat.
        if (e.repeat) return;
        if (brushActive) {
          // Older callers can still leave brush exit to their global owner.
          if (onExitBrush) {
            e.preventDefault();
            onExitBrush();
          }
          return;
        }
        e.preventDefault();
        handleCollapse();
        return;
      }
      if (isInteractiveKeyboardTarget(e.target)) return;
      if (e.key === "ArrowRight" || e.key === " ") {
        e.preventDefault();
        goToSlide(currentIndex + 1);
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        goToSlide(currentIndex - 1);
      }
      if (e.key === "Home") {
        e.preventDefault();
        goToSlide(0);
      }
      if (e.key === "End") {
        e.preventDefault();
        goToSlide(slides.length - 1);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [brushActive, currentIndex, goToSlide, handleCollapse, onExitBrush, open, slides.length]);

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

      <div className="ppt-viewer-stage" ref={stageRef} tabIndex={-1}
        onPointerDown={event => {
          // Return keyboard ownership to the canvas after a drawing-tool button was used.
          if (!isInteractiveKeyboardTarget(event.target)) stageRef.current?.focus({ preventScroll: true });
        }}>
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
              onUndoChange={onBrushUndoChange}
              history={annotationHistory}
              pageKey={String(currentIndex)}
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
