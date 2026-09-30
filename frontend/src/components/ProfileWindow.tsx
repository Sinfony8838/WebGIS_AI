import { useEffect, useMemo, useRef, useState } from "react";
import { previewMapProfile } from "../api";
import type { MapProfileResult, MapProfileSample } from "../types";
import "./ProfileWindow.css";

export type MeasureRecord = {
  id: string;
  name: string;
  coordinates: [number, number][];
  totalKm: number;
  color: string;
};

type Source = { id: string; name: string };
type Props = {
  projectId: string;
  record: MeasureRecord;
  densitySources: Source[];
  hidden?: boolean;
  onHover: (sample: MapProfileSample | null) => void;
  onClose: (recordId: string) => void;
};

const MIN_W = 320;
const MIN_H = 220;

// 每条测线一个独立剖面小窗：可拖动、可放大缩小、可单独关闭，多窗并存对照。
export function ProfileWindow({ projectId, record, densitySources, hidden, onHover, onClose }: Props) {
  const [position, setPosition] = useState(() => ({
    // 按记录序号轻微错位，避免多窗完全重叠。
    left: 96 + ((record.id.charCodeAt(record.id.length - 1) * 7) % 160),
    top: 120 + ((record.id.charCodeAt(record.id.length - 1) * 11) % 140)
  }));
  const [size, setSize] = useState({ width: 560, height: 330 });
  useEffect(() => {
    const fitViewport = () => {
      const width = Math.min(size.width, Math.max(1, window.innerWidth - 16));
      const height = Math.min(size.height, Math.max(1, window.innerHeight - 80));
      setSize(previous => previous.width === width && previous.height === height ? previous : { width, height });
      setPosition(previous => ({
        left: Math.max(8, Math.min(window.innerWidth - width - 8, previous.left)),
        top: Math.max(64, Math.min(window.innerHeight - height - 8, previous.top))
      }));
    };
    fitViewport();
    window.addEventListener("resize", fitViewport);
    return () => window.removeEventListener("resize", fitViewport);
  }, [size.width, size.height]);
  const [sourceId, setSourceId] = useState(densitySources[0]?.id || "");
  const [result, setResult] = useState<MapProfileResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hovered, setHovered] = useState<MapProfileSample | null>(null);
  const requestNumber = useRef(0);
  const svgRef = useRef<SVGSVGElement>(null);
  const windowRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ startX: number; startY: number; origin: { left: number; top: number } } | null>(null);
  const resizeRef = useRef<{ startX: number; startY: number; origin: { width: number; height: number } } | null>(null);
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;

  useEffect(() => {
    if (!densitySources.some(source => source.id === sourceId)) setSourceId(densitySources[0]?.id || "");
  }, [densitySources, sourceId]);
  useEffect(() => {
    setResult(null);
    setError("");
    setHovered(null);
    onHover(null);
    requestNumber.current++;
  }, [record.coordinates, projectId]);
  useEffect(() => () => onHoverRef.current(null), []);

  const chart = useMemo(() => {
    if (!result) return null;
    const valid = result.samples.filter(sample => sample.value !== null).map(sample => sample.value as number);
    if (!valid.length) return null;
    const min = Math.min(...valid);
    const max = Math.max(...valid);
    const low = min === max ? min - 1 : min;
    const high = min === max ? max + 1 : max;
    const x = (sample: MapProfileSample) => 55 + sample.distance_km / result.total_distance_km * 890;
    const y = (value: number) => 185 - (value - low) / (high - low) * 155;
    let path = "";
    let open = false;
    for (const sample of result.samples) {
      if (sample.value === null) { open = false; continue; }
      path += `${open ? "L" : "M"}${x(sample).toFixed(2)},${y(sample.value).toFixed(2)} `;
      open = true;
    }
    return { path, low, high, x, y };
  }, [result]);

  async function run(kind: "population" | "terrain") {
    const id = kind === "terrain" ? "mapzen_terrain" : sourceId;
    if (!id) return;
    const current = ++requestNumber.current;
    setLoading(true);
    setError("");
    setResult(null);
    setHovered(null);
    onHover(null);
    try {
      const next = await previewMapProfile(projectId, { coordinates: record.coordinates, kind, source_id: id });
      if (requestNumber.current === current) setResult(next);
    } catch (cause) {
      if (requestNumber.current === current) setError(cause instanceof Error ? cause.message : "剖面生成失败");
    } finally {
      if (requestNumber.current === current) setLoading(false);
    }
  }

  function move(event: React.PointerEvent<SVGSVGElement>) {
    if (!result || !svgRef.current) return;
    const rectangle = svgRef.current.getBoundingClientRect();
    const position_ = (event.clientX - rectangle.left) / rectangle.width * 1000;
    const distance = Math.max(0, Math.min(result.total_distance_km, (position_ - 55) / 890 * result.total_distance_km));
    const nearest = result.samples.reduce((best, sample) =>
      Math.abs(sample.distance_km - distance) < Math.abs(best.distance_km - distance) ? sample : best);
    setHovered(nearest);
    onHover(nearest);
  }

  function onHeaderPointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest("button")) return;
    event.preventDefault();
    dragRef.current = { startX: event.clientX, startY: event.clientY, origin: position };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }
  function onHeaderPointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag) return;
    const maxLeft = window.innerWidth - size.width - 8;
    const maxTop = window.innerHeight - size.height - 8;
    setPosition({
      left: Math.max(8, Math.min(maxLeft, drag.origin.left + event.clientX - drag.startX)),
      top: Math.max(64, Math.min(maxTop, drag.origin.top + event.clientY - drag.startY))
    });
  }
  function onHeaderPointerUp() {
    dragRef.current = null;
  }
  function onResizePointerDown(event: React.PointerEvent<HTMLSpanElement>) {
    event.preventDefault();
    event.stopPropagation();
    resizeRef.current = { startX: event.clientX, startY: event.clientY, origin: size };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }
  function onResizePointerMove(event: React.PointerEvent<HTMLSpanElement>) {
    const resize = resizeRef.current;
    if (!resize) return;
    setSize({
      width: Math.min(window.innerWidth - position.left - 8, Math.max(MIN_W, resize.origin.width + event.clientX - resize.startX)),
      height: Math.min(window.innerHeight - position.top - 8, Math.max(MIN_H, resize.origin.height + event.clientY - resize.startY))
    });
  }
  function onResizePointerUp() {
    resizeRef.current = null;
  }

  const rasterCaveats = result?.source_caveats?.length ? result.source_caveats : null;

  return (
    <div
      ref={windowRef}
      className={`profile-window${hidden ? " is-hidden" : ""}`}
      style={{ left: position.left, top: position.top, width: size.width, height: size.height }}
      data-testid={`profile-window-${record.id}`}
      aria-label={`${record.name}剖面`}
    >
      <div
        className="profile-window-head"
        onPointerDown={onHeaderPointerDown}
        onPointerMove={onHeaderPointerMove}
        onPointerUp={onHeaderPointerUp}
        onPointerCancel={onHeaderPointerUp}
      >
        <span className="profile-window-dot" style={{ background: record.color }} />
        <strong>{record.name} · {record.totalKm.toFixed(2)} 千米</strong>
        <button
          type="button"
          className="profile-window-close"
          aria-label={`关闭${record.name}及其剖面窗口`}
          data-testid={`profile-window-close-${record.id}`}
          onClick={() => onClose(record.id)}
        >
          ×
        </button>
      </div>
      <div className="profile-window-body">
        <div className="profile-window-controls">
          {densitySources.length > 0 && <>
            <select aria-label={`${record.name}人口密度数据源`} value={sourceId} onChange={event => setSourceId(event.target.value)}>
              {densitySources.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}
            </select>
            <button type="button" disabled={loading} onClick={() => void run("population")}>人口密度变化</button>
          </>}
          <button type="button" disabled={loading} onClick={() => void run("terrain")}>地形剖面</button>
        </div>
        {loading && <p role="status">正在读取原始数据…</p>}
        {error && <p role="alert" className="profile-window-error">{error}</p>}
        {result && <>
          <div className="profile-window-meta"><strong>{result.kind === "terrain" ? "高程" : "人口密度"}</strong> · {result.source_name} · {result.source_year} · 测线 {result.total_distance_km.toFixed(2)} 千米</div>
          {chart ? <svg ref={svgRef} className="profile-window-chart" viewBox="0 0 1000 230" role="img" aria-label={`${record.name}${result.kind === "terrain" ? "地形" : "人口密度"}沿线剖面图`} onPointerMove={move} onPointerLeave={() => { setHovered(null); onHover(null); }}>
            <line x1="55" x2="945" y1="185" y2="185" stroke="currentColor" opacity=".5" />
            <line x1="55" x2="55" y1="30" y2="185" stroke="currentColor" opacity=".5" />
            <path d={chart.path} fill="none" stroke={record.color} strokeWidth="3" strokeLinejoin="round" />
            {hovered?.value !== null && hovered && <circle cx={chart.x(hovered)} cy={chart.y(hovered.value)} r="5" fill="#e34e4e" />}
            <text x="55" y="215">0 km</text><text x="895" y="215">{result.total_distance_km.toFixed(1)} km</text>
            <text x="60" y="25">{chart.high.toFixed(1)} {result.unit}</text><text x="60" y="180">{chart.low.toFixed(1)}</text>
          </svg> : <p>测线内没有可用数值。</p>}
          {hovered && <p className="profile-window-readout">{hovered.distance_km.toFixed(2)} 千米 · {hovered.value === null ? "无数据" : `${hovered.value.toLocaleString("zh-CN")} ${result.unit}`} {hovered.label || ""}</p>}
          <p className="profile-window-footnote">
            {result.sampling}{result.sample_spacing_m !== null ? `；采样间隔约 ${result.sample_spacing_m.toFixed(0)} 米` : ""}
            {result.resolution_m !== null ? `；${result.kind === "terrain" ? "此纬度瓦片像元约" : "原始网格约"} ${result.resolution_m.toFixed(0)} 米` : ""}
            。无数据 {result.no_data_count} 点，不作推断。
            {result.kind === "terrain" ? "原始 DEM 垂直精度因地区而异。" : ""}
            {result.value_note ? ` ${result.value_note}` : ""}
            {rasterCaveats ? ` ${rasterCaveats.join(" ")}` : ""}
            {result.source_attribution ? ` ${result.source_attribution}` : ""}
            {result.source_url && <> <a href={result.source_url} target="_blank" rel="noreferrer">数据来源与署名</a></>}
          </p>
        </>}
      </div>
      <span
        className="profile-window-resize"
        aria-label={`缩放${record.name}剖面窗口`}
        data-testid={`profile-window-resize-${record.id}`}
        onPointerDown={onResizePointerDown}
        onPointerMove={onResizePointerMove}
        onPointerUp={onResizePointerUp}
        onPointerCancel={onResizePointerUp}
      />
    </div>
  );
}
