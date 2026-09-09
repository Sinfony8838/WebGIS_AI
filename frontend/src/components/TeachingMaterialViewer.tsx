import { useEffect, useRef } from "react";
import { getApiBase } from "../api";
import type { TeachingMaterial } from "../types";

type Props = {
  open: boolean;
  title: string;
  materials: TeachingMaterial[];
  onClose: () => void;
};

function materialUrl(url: string): string {
  if (!url) {
    return "";
  }
  return url.startsWith("/files/") ? `${getApiBase()}${url}` : url;
}

function bilibiliPlayerUrl(url: string): string {
  const match = url.match(/\/video\/(BV[0-9A-Za-z]+)/);
  if (!match) {
    return "";
  }
  return `https://player.bilibili.com/player.html?bvid=${encodeURIComponent(match[1])}&page=1&autoplay=0`;
}

function renderMaterial(material: TeachingMaterial) {
  const url = materialUrl(material.url);
  if (material.type === "image" || material.type === "animation") {
    return <img src={url} alt={material.title} />;
  }
  if (material.type === "video") {
    const playerUrl = bilibiliPlayerUrl(url);
    if (playerUrl) {
      return (
        <iframe
          src={playerUrl}
          title={material.title}
          allow="fullscreen; picture-in-picture"
          allowFullScreen
          referrerPolicy="no-referrer-when-downgrade"
        />
      );
    }
    return <video src={url} controls />;
  }
  return (
    <a href={url} target="_blank" rel="noreferrer">
      打开资料
    </a>
  );
}

export function TeachingMaterialViewer({ open, title, materials, onClose }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (open && dialog && !dialog.open) dialog.showModal();
    return () => {
      if (dialog?.open) dialog.close();
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, [open]);
  if (!open) return null;

  return (
    <dialog ref={dialogRef} className="material-viewer-backdrop" aria-label={title || "教学资料预览"}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onKeyDown={(event) => { if (event.key === "Escape") event.stopPropagation(); }}
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="material-viewer glass-panel" onClick={(event) => event.stopPropagation()}>
        <div className="material-viewer-header">
          <div>
            <p className="panel-tag">Teaching Materials</p>
            <strong>{title || "地区教学资料"}</strong>
          </div>
          <button type="button" className="mini-control" onClick={onClose} aria-label="关闭资料预览">
            ×
          </button>
        </div>
        <div className="material-viewer-list">
          {materials.length ? (
            materials.map((material) => (
              <article key={material.id} className="material-viewer-card">
                <div className="material-preview">{renderMaterial(material)}</div>
                <div>
                  <strong>{material.title}</strong>
                  <p>{material.description || material.region_binding?.name || "暂无说明"}</p>
                </div>
              </article>
            ))
          ) : (
            <div className="drawer-empty-state">当前地区还没有导入课时资料。</div>
          )}
        </div>
      </section>
    </dialog>
  );
}
