import { type MutableRefObject, useState, useEffect, useRef, useCallback } from "react";
import { createPortal } from "react-dom";
import type { SlideContent, PptRenderJobStatus } from "../types";
import { BrushOverlay, type BrushOverlayHandle, type BrushSettings } from "./BrushOverlay";

type Props = {
  open: boolean;
  onExpand: () => void;
  onCollapse: () => void;
  onRemove: () => void;
  slides: SlideContent[];
  fileName: string;
  /** Identity of the imported deck; page + annotations reset only on change. */
  deckKey: string;
  renderStatus: PptRenderJobStatus | "idle";
  expectedSlides: number;
  previewMode: "rendered" | "simple";
  paneWidth: number;
  fullscreen: boolean;
  onPaneWidthChange: (px: number) => void;
  onToggleFullscreen: () => void;
  brushActive?: boolean;
  brushSettings?: BrushSettings;
  brushOverlayRef?: MutableRefObject<BrushOverlayHandle | null>;
  onBrushContentChange?: (hasContent: boolean) => void;
};

const EMU_PER_PX = 914400 / 96;
const MIN_PANE_WIDTH = 360;
const MIN_MAP_WIDTH = 520;
const NARROW_QUERY = "(max-width: 1024px)";

function narrowQuery(): MediaQueryList | null {
  try {
    return window.matchMedia?.(NARROW_QUERY) ?? null;
  } catch {
    return null;
  }
}

export function PptViewer({
  open,
  onExpand,
  onCollapse,
  onRemove,
  slides,
  fileName,
  deckKey,
  renderStatus,
  expectedSlides,
  previewMode,
  paneWidth,
  fullscreen,
  onPaneWidthChange,
  onToggleFullscreen,
  brushActive = false,
  brushSettings,
  brushOverlayRef,
  onBrushContentChange
}: Props) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [scale, setScale] = useState(1);
  const [narrow, setNarrow] = useState(() => narrowQuery()?.matches ?? false);
  const [imageErrors, setImageErrors] = useState<Record<number, boolean>>({});
  const [imageRetryToken, setImageRetryToken] = useState(0);
  const stageRef = useRef<HTMLDivElement>(null);
  const paneRef = useRef<HTMLElement>(null);
  const dragRafRef = useRef(0);
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
    setScale(Math.max(0.05, Math.min(1, scaleX, scaleY)));
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
      if (slides.length === 0) return;
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

  // A new deck (not new render results) resets page and annotations.
  useEffect(() => {
    annotationImagesRef.current = {};
    setImageErrors({});
    setCurrentIndex(0);
  }, [deckKey]);

  // Rendered pages only ever append; keep the reader on its current page.
  useEffect(() => {
    if (slides.length > 0 && currentIndex > slides.length - 1) {
      setCurrentIndex(slides.length - 1);
    }
  }, [currentIndex, slides.length]);

  useEffect(() => {
    const query = narrowQuery();
    if (!query) return;
    const listener = () => setNarrow(query.matches);
    listener();
    query.addEventListener("change", listener);
    return () => query.removeEventListener("change", listener);
  }, []);

  useEffect(() => {
    if (!open) return;
    recalcScale();
    const stage = stageRef.current;
    const observer = new ResizeObserver(() => recalcScale());
    if (stage) observer.observe(stage);
    window.addEventListener("resize", recalcScale);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", recalcScale);
    };
  }, [open, recalcScale]);

  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => restoreAnnotation(currentIndex));
    return () => window.cancelAnimationFrame(frame);
  }, [currentIndex, open, restoreAnnotation, slides]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      const pane = paneRef.current;
      if (!pane || !pane.contains(document.activeElement)) return;
      if (e.key === "ArrowRight" || e.key === " ") {
        e.preventDefault();
        goToSlide(currentIndex + 1);
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        goToSlide(currentIndex - 1);
      }
      if (e.key === "Escape") {
        e.preventDefault();
        if (fullscreen) onToggleFullscreen();
        else handleCollapse();
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
  }, [currentIndex, fullscreen, goToSlide, handleCollapse, onToggleFullscreen, open, slides.length]);

  useEffect(() => () => window.cancelAnimationFrame(dragRafRef.current), []);

  const startDrag = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const target = event.currentTarget;
      try {
        target.setPointerCapture?.(event.pointerId);
      } catch {
        // jsdom and some browsers reject capture for synthetic/inactive pointers
      }
      const move = (e: PointerEvent) => {
        const requested = window.innerWidth - e.clientX;
        if (!Number.isFinite(requested)) return;
        window.cancelAnimationFrame(dragRafRef.current);
        dragRafRef.current = window.requestAnimationFrame(() => {
          const maxWidth = window.innerWidth - MIN_MAP_WIDTH;
          const width = Math.max(MIN_PANE_WIDTH, Math.min(maxWidth, requested));
          onPaneWidthChange(width);
        });
      };
      const finish = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", finish);
        window.removeEventListener("pointercancel", finish);
        try {
          target.releasePointerCapture?.(event.pointerId);
        } catch {
          // the pointer capture may already be gone
        }
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", finish);
      window.addEventListener("pointercancel", finish);
    },
    [onPaneWidthChange]
  );

  if (!open) {
    const totalPages = slides.length > 0 ? slides.length : expectedSlides;
    const statusText =
      slides.length === 0 && (renderStatus === "queued" || renderStatus === "rendering")
        ? "渲染中…"
        : renderStatus === "failed" && slides.length === 0
          ? "渲染失败"
          : "";
    return (
      <div className="ppt-viewer-dock" role="group" aria-label="已导入 PPT">
        <button type="button" className="ppt-viewer-dock-main" onClick={onExpand}>
          <span className="ppt-viewer-dock-badge">PPT</span>
          <span className="ppt-viewer-dock-title">{fileName}</span>
          <span className="ppt-viewer-dock-meta">
            {statusText || (totalPages > 0 ? `${currentIndex + 1} / ${totalPages}` : "")}
          </span>
        </button>
        <button type="button" className="ppt-viewer-dock-remove" onClick={handleRemove} aria-label="移除 PPT">
          ×
        </button>
      </div>
    );
  }

  const rendering = renderStatus === "queued" || renderStatus === "rendering";
  const totalCount = Math.max(slides.length, expectedSlides);
  const effectiveFullscreen = fullscreen || narrow;
  const paneWidthPx = narrow ? window.innerWidth : paneWidth;

  return createPortal(
    <>
      {!effectiveFullscreen ? (
        <div
          className="ppt-pane-divider"
          style={{ right: Math.max(0, paneWidthPx - 4) }}
          onPointerDown={startDrag}
          role="separator"
          aria-orientation="vertical"
          aria-label="拖动调整 PPT 面板宽度"
        />
      ) : null}
      <section
        ref={paneRef}
        className={`ppt-pane ${effectiveFullscreen ? "ppt-pane--fullscreen" : ""}`}
        style={{ width: narrow ? "100vw" : `${paneWidthPx}px` }}
        tabIndex={-1}
        aria-label="PPT 演示面板"
      >
        <div className="ppt-viewer-header">
          <span className="ppt-viewer-filename" title={fileName}>
            {fileName}
          </span>
          {previewMode === "simple" ? <span className="ppt-pane-badge ppt-pane-badge--simple">简易预览</span> : null}
          {rendering && previewMode === "rendered" ? (
            <span className="ppt-pane-badge ppt-pane-badge--progress">
              渲染中 {slides.length}
              {totalCount > 0 ? ` / ${totalCount}` : ""}
            </span>
          ) : null}
          <span className="ppt-viewer-counter">
            {slides.length > 0 ? `${currentIndex + 1} / ${totalCount || slides.length}` : ""}
          </span>
          <div className="ppt-viewer-controls">
            {!narrow ? (
              <button type="button" onClick={onToggleFullscreen}>
                {fullscreen ? "退出全屏" : "全屏"}
              </button>
            ) : null}
            {narrow ? (
              <button type="button" onClick={handleCollapse}>
                切回地图
              </button>
            ) : null}
            <button type="button" onClick={handleCollapse}>
              收起
            </button>
            <button type="button" onClick={handleRemove}>
              移除
            </button>
          </div>
        </div>

        <div className="ppt-viewer-stage" ref={stageRef}>
          {slides.length === 0 ? (
            <div className="ppt-pane-loading">
              {renderStatus === "failed" ? (
                <p>服务端渲染失败，正在使用简易解析…</p>
              ) : (
                <>
                  <span className="ppt-pane-spinner" aria-hidden="true" />
                  <p>正在渲染第 1 页…</p>
                </>
              )}
            </div>
          ) : (
            <div
              className="ppt-viewer-slide"
              style={{
                width: slideW,
                height: slideH,
                transform: `scale(${scale})`,
                background: slide?.imageUrl ? "transparent" : slide?.bgColor || "#ffffff"
              }}
            >
              {slide?.imageUrl ? (
                imageErrors[currentIndex] ? (
                  <div className="ppt-slide-error">
                    <p>第 {currentIndex + 1} 页加载失败</p>
                    <button
                      type="button"
                      onClick={() => {
                        setImageErrors((previous) => {
                          const next = { ...previous };
                          delete next[currentIndex];
                          return next;
                        });
                        setImageRetryToken((token) => token + 1);
                      }}
                    >
                      重试
                    </button>
                  </div>
                ) : (
                  <img
                    key={`slide-img-${currentIndex}-${imageRetryToken}`}
                    src={slide.imageUrl}
                    alt={`幻灯片 ${currentIndex + 1}`}
                    className="ppt-viewer-slide-image"
                    draggable={false}
                    onError={() =>
                      setImageErrors((previous) => ({ ...previous, [currentIndex]: true }))
                    }
                  />
                )
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
          )}
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
            {rendering && totalCount > slides.length ? (
              <button type="button" className="ppt-viewer-thumb-pending" disabled>
                …
              </button>
            ) : null}
          </div>
          <button
            type="button"
            disabled={slides.length === 0 || currentIndex === slides.length - 1}
            onClick={() => goToSlide(currentIndex + 1)}
          >
            下一页
          </button>
        </div>
      </section>
    </>,
    document.body
  );
}
