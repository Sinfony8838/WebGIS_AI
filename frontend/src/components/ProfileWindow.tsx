import { useEffect, useMemo, useRef, useState } from "react";
import { previewMapProfile } from "../api";
import type { MapProfileResult, MapProfileSample, ProfileWindowKind } from "../types";
import "./ProfileWindow.css";

export type MeasureRecord = {
  id: string;
  name: string;
  coordinates: [number, number][];
  totalKm: number;
  color: string;
};

export type ProfileWindowGeometry = { left: number; top: number; width: number; height: number };

type Source = { id: string; name: string };
type Props = {
  projectId: string;
  windowId: string;
  record: MeasureRecord;
  /** 每个窗口固定一种图：人口密度变化 或 地形剖面（任务3：同线两图并存）。 */
  kind: ProfileWindowKind;
  densitySources: Source[];
  sourceId: string;
  geometry: ProfileWindowGeometry;
  hidden?: boolean;
  onGeometryChange: (windowId: string, geometry: ProfileWindowGeometry) => void;
  onSourceChange: (windowId: string, sourceId: string) => void;
  onHover: (sample: MapProfileSample | null) => void;
  onClose: (windowId: string) => void;
  zIndex?: number;
};

const MIN_W = 320;
const MIN_H = 220;
const KIND_LABELS: Record<ProfileWindowKind, string> = { population: "人口密度变化", terrain: "地形剖面" };

// 每条测线每类图一个独立剖面小窗：可拖动、可缩放、可单独关闭，同线人口/地形并存对照。
export function ProfileWindow({
  projectId,
  windowId,
  record,
  kind,
  densitySources,
  sourceId,
  geometry,
  hidden,
  onGeometryChange,
  onSourceChange,
  onHover,
  onClose,
  zIndex
}: Props) {
  const position = { left: geometry.left, top: geometry.top };
  const size = { width: geometry.width, height: geometry.height };
  const [result, setResult] = useState<MapProfileResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hovered, setHovered] = useState<MapProfileSample | null>(null);
  const requestNumber = useRef(0);
  const svgRef = useRef<SVGSVGElement>(null);
  const windowRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ startX: number; startY: number; origin: ProfileWindowGeometry } | null>(null);
  const resizeRef = useRef<{ startX: number; startY: number; origin: ProfileWindowGeometry } | null>(null);
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;

  // 视口变化时把窗口夹回可操作范围（不同屏幕尺寸可见、可拖动）。
  useEffect(() => {
    const clamp = () => {
      const width = Math.min(geometry.width, Math.max(MIN_W, window.innerWidth - 16));
      const height = Math.min(geometry.height, Math.max(MIN_H, window.innerHeight - 80));
      const left = Math.max(8, Math.min(window.innerWidth - geometry.width - 8, geometry.left));
      const top = Math.max(64, Math.min(window.innerHeight - geometry.height - 8, geometry.top));
      if (width !== geometry.width || height !== geometry.height || left !== geometry.left || top !== geometry.top) {
        onGeometryChange(windowId, { left, top, width, height });
      }
    };
    clamp();
    window.addEventListener("resize", clamp);
    return () => window.removeEventListener("resize", clamp);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geometry.left, geometry.top, geometry.width, geometry.height, windowId]);

  useEffect(() => {
    setResult(null);
    setError("");
    setHovered(null);
    onHover(null);
    requestNumber.current++;
  }, [record.coordinates, projectId]);
  useEffect(() => () => onHoverRef.current(null), []);

  // 窗口诞生即读取数据；人口窗口切换数据源后自动重读。
  useEffect(() => {
    const id = kind === "terrain" ? "mapzen_terrain" : sourceId;
    if (!id) return;
    const current = ++requestNumber.current;
    setLoading(true);
    setError("");
    setResult(null);
    setHovered(null);
    onHover(null);
    previewMapProfile(projectId, { coordinates: record.coordinates, kind, source_id: id })
      .then((next) => {
        if (requestNumber.current === current) setResult(next);
      })
      .catch((cause) => {
        if (requestNumber.current === current) setError(cause instanceof Error ? cause.message : "剖面生成失败");
      })
      .finally(() => {
        if (requestNumber.current === current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, sourceId, record.coordinates, projectId]);

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
    dragRef.current = { startX: event.clientX, startY: event.clientY, origin: geometry };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }
  function onHeaderPointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag) return;
    const maxLeft = window.innerWidth - size.width - 8;
    const maxTop = window.innerHeight - size.height - 8;
    onGeometryChange(windowId, {
      left: Math.max(8, Math.min(maxLeft, drag.origin.left + event.clientX - drag.startX)),
      top: Math.max(64, Math.min(maxTop, drag.origin.top + event.clientY - drag.startY)),
      width: size.width,
      height: size.height
    });
  }
  function onHeaderPointerUp() {
    dragRef.current = null;
  }
  function onResizePointerDown(event: React.PointerEvent<HTMLSpanElement>) {
    event.preventDefault();
    event.stopPropagation();
    resizeRef.current = { startX: event.clientX, startY: event.clientY, origin: geometry };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }
  function onResizePointerMove(event: React.PointerEvent<HTMLSpanElement>) {
    const resize = resizeRef.current;
    if (!resize) return;
    onGeometryChange(windowId, {
      left: position.left,
      top: position.top,
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
      style={{ left: position.left, top: position.top, width: size.width, height: size.height, zIndex: zIndex || undefined }}
      data-testid={`profile-window-${windowId}`}
      aria-label={`${record.name}${KIND_LABELS[kind]}窗口`}
    >
      <div
        className="profile-window-head"
        onPointerDown={onHeaderPointerDown}
        onPointerMove={onHeaderPointerMove}
        onPointerUp={onHeaderPointerUp}
        onPointerCancel={onHeaderPointerUp}
      >
        <span className="profile-window-dot" style={{ background: record.color }} />
        <strong>{record.name} · {KIND_LABELS[kind]} · {record.totalKm.toFixed(2)} 千米</strong>
        <button
          type="button"
          className="profile-window-close"
          aria-label={`关闭${record.name}${KIND_LABELS[kind]}窗口`}
          data-testid={`profile-window-close-${windowId}`}
          onClick={() => onClose(windowId)}
        >
          ×
        </button>
      </div>
      <div className="profile-window-body">
        <div className="profile-window-controls">
          {kind === "population" && densitySources.length > 0 && <>
            <select aria-label={`${record.name}人口密度数据源`} value={sourceId} onChange={event => onSourceChange(windowId, event.target.value)}>
              {densitySources.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}
            </select>
          </>}
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
        aria-label={`缩放${record.name}${KIND_LABELS[kind]}窗口`}
        data-testid={`profile-window-resize-${windowId}`}
        onPointerDown={onResizePointerDown}
        onPointerMove={onResizePointerMove}
        onPointerUp={onResizePointerUp}
        onPointerCancel={onResizePointerUp}
      />
    </div>
  );
}
