import { useEffect, useMemo, useRef, useState } from "react";
import { previewMapProfile } from "../api";
import type { MapProfileResult, MapProfileSample } from "../types";
import "./MapProfilePanel.css";

type Source = { id: string; name: string };
type Props = {
  projectId: string;
  coordinates: [number, number][];
  densitySources: Source[];
  onHover: (sample: MapProfileSample | null) => void;
};

export function MapProfilePanel({ projectId, coordinates, densitySources, onHover }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [sourceId, setSourceId] = useState(densitySources[0]?.id || "");
  const [result, setResult] = useState<MapProfileResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hovered, setHovered] = useState<MapProfileSample | null>(null);
  const requestNumber = useRef(0);
  const svgRef = useRef<SVGSVGElement>(null);
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;

  useEffect(() => {
    if (!densitySources.some(source => source.id === sourceId)) setSourceId(densitySources[0]?.id || "");
  }, [densitySources, sourceId]);
  useEffect(() => { setResult(null); setError(""); setHovered(null); onHover(null); requestNumber.current++; }, [coordinates, projectId]);
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
      const next = await previewMapProfile(projectId, { coordinates, kind, source_id: id });
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
    const position = (event.clientX - rectangle.left) / rectangle.width * 1000;
    const distance = Math.max(0, Math.min(result.total_distance_km, (position - 55) / 890 * result.total_distance_km));
    const nearest = result.samples.reduce((best, sample) =>
      Math.abs(sample.distance_km - distance) < Math.abs(best.distance_km - distance) ? sample : best);
    setHovered(nearest);
    onHover(nearest);
  }

  return <section className={`map-profile-panel${collapsed ? " is-collapsed" : ""}`} aria-label="测线剖面">
    <button type="button" className="map-profile-heading" onClick={() => setCollapsed(value => !value)} aria-expanded={!collapsed}>
      测线剖面 <span>{collapsed ? "展开" : "收起"}</span>
    </button>
    {!collapsed && <div className="map-profile-body">
      <div className="map-profile-controls">
        {densitySources.length > 0 && <>
          {densitySources.length > 1 && <select aria-label="人口密度数据源" value={sourceId} onChange={event => setSourceId(event.target.value)}>
            {densitySources.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}
          </select>}
          <button type="button" disabled={loading} onClick={() => void run("population")}>人口密度变化</button>
        </>}
        <button type="button" disabled={loading} onClick={() => void run("terrain")}>地形剖面</button>
      </div>
      {loading && <p role="status">正在读取原始数据…</p>}
      {error && <p role="alert" className="map-profile-error">{error}</p>}
      {result && <>
        <div className="map-profile-meta"><strong>{result.kind === "terrain" ? "高程" : "人口密度"}</strong> · {result.source_name} · {result.source_year} · 测线 {result.total_distance_km.toFixed(2)} 千米</div>
        {chart ? <svg ref={svgRef} className="map-profile-chart" viewBox="0 0 1000 230" role="img" aria-label={`${result.kind === "terrain" ? "地形" : "人口密度"}沿线剖面图`} onPointerMove={move} onPointerLeave={() => { setHovered(null); onHover(null); }}>
          <line x1="55" x2="945" y1="185" y2="185" stroke="currentColor" opacity=".5" />
          <line x1="55" x2="55" y1="30" y2="185" stroke="currentColor" opacity=".5" />
          <path d={chart.path} fill="none" stroke="#087cad" strokeWidth="3" strokeLinejoin="round" />
          {hovered?.value !== null && hovered && <circle cx={chart.x(hovered)} cy={chart.y(hovered.value)} r="5" fill="#e34e4e" />}
          <text x="55" y="215">0 km</text><text x="895" y="215">{result.total_distance_km.toFixed(1)} km</text>
          <text x="60" y="25">{chart.high.toFixed(1)} {result.unit}</text><text x="60" y="180">{chart.low.toFixed(1)}</text>
        </svg> : <p>测线内没有可用数值。</p>}
        {hovered && <p className="map-profile-readout">{hovered.distance_km.toFixed(2)} 千米 · {hovered.value === null ? "无数据" : `${hovered.value.toLocaleString("zh-CN")} ${result.unit}`} {hovered.label || ""}</p>}
        <p className="map-profile-footnote">{result.sampling}{result.sample_spacing_m !== null ? `；采样间隔约 ${result.sample_spacing_m.toFixed(0)} 米` : ""}{result.resolution_m !== null ? `；${result.kind === "terrain" ? "此纬度瓦片像元约" : "原始网格约"} ${result.resolution_m.toFixed(0)} 米` : ""}。无数据 {result.no_data_count} 点，不作推断。{result.kind === "terrain" ? "原始 DEM 垂直精度因地区而异。" : ""}{result.source_url && <> <a href={result.source_url} target="_blank" rel="noreferrer">数据来源与署名</a></>}</p>
      </>}
    </div>}
  </section>;
}
