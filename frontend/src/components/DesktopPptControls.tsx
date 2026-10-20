import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { openDesktopPowerPoint } from "../lib/desktopPowerPoint";
import "./DesktopPptControls.css";

export function DesktopPptControls({ onNotice }: { onNotice: (message: string) => void }) {
  const pending = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async () => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try {
      const result = await openDesktopPowerPoint("preview");
      if (result.status === "shown" && result.foreground === false) {
        onNotice("课件预览已显示；Windows 未允许返回 WebGIS，请点击任务栏中的 WebGIS 窗口。");
      }
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { pending.current = false; setBusy(false); }
  };
  return <>
    <button type="button" className="desktop-switch-launcher" disabled={busy} onClick={() => void run()}
      aria-label="PPT 课件" aria-busy={busy}
      title={busy ? "正在准备课件预览…" : "PPT 课件：点击预览，放大进入 PowerPoint"}>
      <svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="29" cy="22" r="15" fill="#f5ba9d" />
        <path d="M29 7a15 15 0 0 1 15 15H29Z" fill="#d35230" />
        <rect x="5" y="12" width="24" height="27" rx="3" fill="#c43e1c" />
        <path d="M13 32V18h6a4.5 4.5 0 0 1 0 9h-3v5Zm3-8h3a1.5 1.5 0 0 0 0-3h-3Z" fill="white" /></svg>
    </button>
    {error ? createPortal(<div style={{ position: "fixed", inset: 0, zIndex: 10000,
      background: "rgba(0,0,0,.35)", display: "grid", placeItems: "center", padding: 20 }}>
      <section role="dialog" aria-modal="true" aria-labelledby="desktop-ppt-error-title"
        style={{ width: "min(480px, 100%)", padding: 24, background: "#fff", color: "#243546", borderRadius: 12 }}
        onKeyDown={event => {
          if (event.key === "Escape") setError("");
          if (event.key === "Tab") event.preventDefault(); // One focusable close button.
        }}>
        <h2 id="desktop-ppt-error-title" style={{ marginTop: 0, fontSize: 20 }}>本机 PowerPoint 提示</h2>
        <p role="alert" style={{ lineHeight: 1.7, overflowWrap: "anywhere" }}>{error}</p>
        <button type="button" className="toolbar-button" autoFocus onClick={() => setError("")}
          aria-label="关闭 PPT 连接提示">关闭</button>
      </section>
    </div>, document.body) : null}
  </>;
}
