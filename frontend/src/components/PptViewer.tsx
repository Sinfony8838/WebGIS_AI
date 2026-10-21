import { type MutableRefObject, useState, useEffect, useLayoutEffect, useRef, useCallback, useMemo } from "react";
import type { SlideContent } from "../types";
import { BrushOverlay, type BrushOverlayHandle, type BrushSettings } from "./BrushOverlay";
import { isEditableKeyboardTarget, isInteractiveKeyboardTarget } from "../lib/keyboard";
import { BrushHistory } from "../lib/brushHistory";
import { cachedPptImage, preloadPptImage, type PptSession } from "../lib/pptSession";
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
  initialSession?: PptSession;
  onSessionChange?: (session: PptSession) => void;
  hideDock?: boolean;
  staticOnly?: boolean;
  imageScope?: string;
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
  onSplitWidthChange,
  initialSession,
  onSessionChange,
  hideDock = false,
  staticOnly = false,
  imageScope = ""
}: Props) {
  const [currentIndex, setCurrentIndex] = useState(initialSession?.currentIndex || 0);
  const [scale, setScale] = useState(1);
  const [fullscreen, setFullscreen] = useState(initialSession?.fullscreen || false);
  const [widthPercent, setWidthPercent] = useState(initialSession?.widthPercent || 46);
  const [imageError, setImageError] = useState(false);
  const [pageLoading, setPageLoading] = useState(false);
  const pageRequest = useRef<AbortController>();
  const failedPage = useRef<number | null>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const annotationHistory = useMemo(() => initialSession?.history || new BrushHistory(30), [slides, initialSession]);
  const sessionRef = useRef<PptSession>({ currentIndex, fullscreen, widthPercent, history: annotationHistory });
  sessionRef.current = { currentIndex, fullscreen, widthPercent, history: annotationHistory };
  const persistSession = useCallback(() => onSessionChange?.(sessionRef.current), [onSessionChange]);
  useEffect(persistSession, [currentIndex, fullscreen, widthPercent, persistSession]);
  useEffect(() => () => pageRequest.current?.abort(), []);
  useEffect(() => {
    const control = new AbortController();
    for (const index of [currentIndex - 1, currentIndex + 1]) {
      const url = slides[index]?.imageUrl;
      if (url && staticOnly) void preloadPptImage(url, control.signal, imageScope).catch(() => {});
    }
    return () => control.abort();
  }, [currentIndex, imageScope, slides, staticOnly]);

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
      if (clamped === currentIndex && !imageError) return;
      saveCurrentAnnotation();
      pageRequest.current?.abort();
      const url = slides[clamped]?.imageUrl;
      if (!url || !staticOnly) { setCurrentIndex(clamped); return; }
      const request = new AbortController(); pageRequest.current = request;
      setPageLoading(true); setImageError(false);
      void preloadPptImage(url, request.signal, imageScope).then(() => {
        if (!request.signal.aborted) { setCurrentIndex(clamped); failedPage.current = null; }
      }).catch(() => {
        if (!request.signal.aborted) { failedPage.current = clamped; setImageError(true); }
      }).finally(() => { if (!request.signal.aborted) setPageLoading(false); });
    },
    [currentIndex, imageError, imageScope, saveCurrentAnnotation, slides, staticOnly]
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
    if (!initialSession) { setCurrentIndex(0); setFullscreen(false); }
  }, [slides, initialSession]);

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
    if (hideDock) return null;
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
          {!staticOnly ? <button type="button" onClick={handleRemove}>
            移除
          </button> : null}
        </div>
      </div>

      {!staticOnly ? <div className={`ppt-viewer-source ${slide?.imageUrl ? "" : "ppt-viewer-source--simple"}`} role="status">
        {slide?.imageUrl ? (slide.renderer?.startsWith("powerpoint") ? "PowerPoint 原版渲染" : "LibreOffice 兼容渲染，请核对字体和版式") : "简易预览：字体、母版和复杂图形可能与原稿不同"}
      </div> : null}
      {pageLoading ? <div className="ppt-page-loading" role="status">正在加载页面…</div> : null}
      {imageError ? <div className="ppt-viewer-image-error" role="alert">页面图像加载失败，当前页面已保留。
        <button type="button" onClick={() => goToSlide(failedPage.current ?? currentIndex)}>重试页面</button></div> : null}

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
              src={staticOnly ? cachedPptImage(slide.imageUrl, imageScope) : slide.imageUrl}
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
              onContentChange={hasContent => { onBrushContentChange?.(hasContent); persistSession(); }}
              onUndoChange={canUndo => { onBrushUndoChange?.(canUndo); persistSession(); }}
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
