import { type MutableRefObject, useState, useEffect, useLayoutEffect, useRef, useCallback, useMemo } from "react";
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
  onToggleBrush?: () => void;
  onSplitWidthChange?: (widthPercent: number | null) => void;
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
  onExitBrush,
  onToggleBrush,
  onSplitWidthChange
}: Props) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [scale, setScale] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);
  const [widthPercent, setWidthPercent] = useState(46);
  const [imageError, setImageError] = useState(false);
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
    setScale(Math.max(0.01, Math.min(1, scaleX, scaleY)));
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
    const observer = new ResizeObserver(recalcScale);
    if (stageRef.current) observer.observe(stageRef.current);
    window.addEventListener("resize", recalcScale);
    return () => { observer.disconnect(); window.removeEventListener("resize", recalcScale); };
  }, [open, recalcScale]);

  useLayoutEffect(() => {
    onSplitWidthChange?.(open && slides.length && !fullscreen ? widthPercent : null);
  }, [fullscreen, onSplitWidthChange, open, slides.length, widthPercent]);

  useEffect(() => { setImageError(false); }, [slide?.imageUrl]);

  useEffect(() => {
    setCurrentIndex(0);
    setFullscreen(false);
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
    <div className={`ppt-viewer-backdrop ${fullscreen ? "ppt-viewer-fullscreen" : "ppt-viewer-split"} ${brushActive ? "ppt-viewer-backdrop--brush" : ""}`}
      style={fullscreen ? undefined : { width: `clamp(320px, ${widthPercent}vw, 70vw)` }} role="region" aria-label="PPT 放映">
      {!fullscreen ? <div className="ppt-viewer-resizer" role="separator" aria-label="调整 PPT 分栏宽度"
        aria-orientation="vertical" aria-valuemin={22} aria-valuemax={70} aria-valuenow={widthPercent} tabIndex={0}
        onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); event.preventDefault(); }}
        onPointerMove={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) setWidthPercent(Math.max(22, Math.min(70, (window.innerWidth - event.clientX) / window.innerWidth * 100))); }}
        onPointerUp={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }}
        onKeyDown={event => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault(); event.stopPropagation();
          setWidthPercent(value => event.key === "Home" ? 22 : event.key === "End" ? 70 : Math.max(22, Math.min(70, value + (event.key === "ArrowLeft" ? 2 : -2))));
        }} /> : null}
      <div className="ppt-viewer-header">
        <span className="ppt-viewer-filename">{fileName}</span>
        <span className="ppt-viewer-counter">
          {currentIndex + 1} / {slides.length}
        </span>
        <div className="ppt-viewer-controls">
          {onToggleBrush ? <button type="button" aria-pressed={brushActive} onClick={onToggleBrush}>{brushActive ? "结束画笔" : "画笔"}</button> : null}
          <button type="button" onClick={() => setFullscreen(value => !value)}>{fullscreen ? "地图同屏" : "全屏"}</button>
          <button type="button" onClick={handleCollapse}>
            收起
          </button>
          <button type="button" onClick={handleRemove}>
            移除
          </button>
        </div>
      </div>

      <div className={`ppt-viewer-source ${slide?.imageUrl ? "" : "ppt-viewer-source--simple"}`} role="status">
        {slide?.imageUrl ? (slide.renderer?.startsWith("powerpoint") ? "PowerPoint 原版渲染" : "LibreOffice 兼容渲染，请核对字体和版式") : "简易预览：字体、母版和复杂图形可能与原稿不同"}
      </div>
      {imageError ? <div className="ppt-viewer-image-error" role="alert">当前页图像加载失败，请重新导入 PPT。</div> : null}

      <div className="ppt-viewer-stage" ref={stageRef} tabIndex={-1}
        onPointerDown={event => {
          // Return keyboard ownership to the canvas after a drawing-tool button was used.
          if (!isInteractiveKeyboardTarget(event.target)) stageRef.current?.focus({ preventScroll: true });
        }}>
        <div className="ppt-viewer-slide-frame" style={{ width: slideW * scale, height: slideH * scale }}><div
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
              onError={() => setImageError(true)}
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
        </div></div>
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
