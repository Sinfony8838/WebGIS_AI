import { useState, useEffect, useRef, useCallback } from "react";
import type { SlideContent } from "../types";

type Props = {
  open: boolean;
  onClose: () => void;
  slides: SlideContent[];
  fileName: string;
};

const EMU_PER_PX = 914400 / 96;

export function PptViewer({ open, onClose, slides, fileName }: Props) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [scale, setScale] = useState(1);
  const stageRef = useRef<HTMLDivElement>(null);

  const slide = slides[currentIndex];
  const slideW = slide ? slide.width / EMU_PER_PX : 960;
  const slideH = slide ? slide.height / EMU_PER_PX : 540;

  // Compute scale to fit slide in viewport
  const recalcScale = useCallback(() => {
    if (!stageRef.current || !slide) return;
    const { clientWidth, clientHeight } = stageRef.current;
    const padX = 32;
    const padY = 32;
    const scaleX = (clientWidth - padX) / slideW;
    const scaleY = (clientHeight - padY) / slideH;
    setScale(Math.min(1, scaleX, scaleY));
  }, [slideW, slideH, slide]);

  useEffect(() => {
    if (!open) return;
    recalcScale();
    window.addEventListener("resize", recalcScale);
    return () => window.removeEventListener("resize", recalcScale);
  }, [open, recalcScale]);

  // Reset index when slides change
  useEffect(() => {
    setCurrentIndex(0);
  }, [slides]);

  // Keyboard navigation
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === " ") {
        e.preventDefault();
        setCurrentIndex((i) => Math.min(i + 1, slides.length - 1));
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        setCurrentIndex((i) => Math.max(i - 1, 0));
      }
      if (e.key === "Escape") {
        onClose();
      }
      if (e.key === "Home") {
        setCurrentIndex(0);
      }
      if (e.key === "End") {
        setCurrentIndex(slides.length - 1);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, slides.length, onClose]);

  if (!open || slides.length === 0) return null;

  return (
    <div className="ppt-viewer-backdrop">
      {/* Header */}
      <div className="ppt-viewer-header">
        <span className="ppt-viewer-filename">{fileName}</span>
        <span className="ppt-viewer-counter">
          {currentIndex + 1} / {slides.length}
        </span>
        <div className="ppt-viewer-controls">
          <button type="button" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>

      {/* Stage */}
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
        </div>
      </div>

      {/* Navigation */}
      <div className="ppt-viewer-nav">
        <button
          type="button"
          disabled={currentIndex === 0}
          onClick={() => setCurrentIndex((i) => i - 1)}
        >
          上一页
        </button>
        <div className="ppt-viewer-thumbs">
          {slides.map((_, i) => (
            <button
              key={i}
              type="button"
              className={i === currentIndex ? "active" : ""}
              onClick={() => setCurrentIndex(i)}
            >
              {i + 1}
            </button>
          ))}
        </div>
        <button
          type="button"
          disabled={currentIndex === slides.length - 1}
          onClick={() => setCurrentIndex((i) => i + 1)}
        >
          下一页
        </button>
      </div>
    </div>
  );
}
