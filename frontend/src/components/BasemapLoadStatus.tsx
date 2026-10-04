import type { BasemapLoadPhase } from "../lib/basemapLoadStatus";

type Props = {
  phase: BasemapLoadPhase;
  title: string;
  busy: boolean;
  onRetry: () => void;
  onRestore: () => void;
};

export function BasemapLoadStatus({ phase, title, busy, onRetry, onRestore }: Props) {
  if (phase !== "error") return null;
  return <section className="map-basemap-notice" aria-label="底图加载状态" role="status">
    <span><strong>{title}暂未加载成功。</strong>可重试或选择高德标准；教学图层和笔迹保留。</span>
    <button type="button" disabled={busy} onClick={onRetry}>重试当前底图</button>
    <button type="button" disabled={busy} onClick={onRestore}>切换高德标准</button>
  </section>;
}
