import { useRef, useState } from "react";
import { openDesktopPowerPoint } from "../lib/desktopPowerPoint";

export function DesktopPptControls({ onNotice }: { onNotice: (message: string) => void }) {
  const pending = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async (action: "open" | "focus") => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try {
      const result = await openDesktopPowerPoint(action);
      if (result.status !== "cancelled") {
        onNotice(result.foreground === false
          ? "PowerPoint 已就绪；Windows 未允许自动切到前台，请点击任务栏中的 PowerPoint。"
          : `${result.file_name || "课件"}已在本机 PowerPoint ${result.status === "focused" ? "切到前台" : "打开"}。`);
      }
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { pending.current = false; setBusy(false); }
  };
  return <>
    <button type="button" className="toolbar-button" disabled={busy} onClick={() => void run("open")}
      title="在教师电脑选择课件，用 PowerPoint 打开；已打开的同一课件会复用窗口">{busy ? "等待 PowerPoint…" : "打开 PPT"}</button>
    <button type="button" className="toolbar-button" disabled={busy} onClick={() => void run("focus")}
      title="将本机已打开的 PowerPoint 课件切回前台">切回 PPT</button>
    {error ? <span role="alert" style={{ maxWidth: 420, fontSize: 13 }}>
      {error} <button type="button" onClick={() => setError("")} aria-label="关闭 PPT 连接提示">关闭</button>
    </span> : null}
  </>;
}
