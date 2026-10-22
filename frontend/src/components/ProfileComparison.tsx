import {useState} from "react";
import type {MapProfileComparison, MapProfileSample, MeasurementRecord} from "../types";
import "./ProfileComparison.css";

export function ProfileComparison({record, result, onHover, onClose}: {record: MeasurementRecord; result: MapProfileComparison; onHover: (p: MapProfileSample | null) => void; onClose: () => void}) {
  const [index, setIndex] = useState<number | null>(null);
  const series = [result.population, result.terrain];
  const colors = ["#6778f5", "#ba7239"];
  const scales = series.map(s => {
    const values = s.samples.flatMap(p => p.value === null ? [] : [p.value]);
    const low = values.length ? Math.min(...values) : 0;
    return {low, high: Math.max(low + 1, ...values)};
  });
  const x = (p: MapProfileSample) => 70 + p.distance_km / result.total_distance_km * 660;
  const y = (v: number, k: number) => 230 - (v - scales[k].low) / (scales[k].high - scales[k].low) * 190;
  const path = (samples: MapProfileSample[], k: number) => {
    let open = false;
    return samples.map(p => {
      if (p.value === null) {open = false; return "";}
      const next = `${open ? "L" : "M"}${x(p)},${y(p.value,k)}`;
      open = true; return next;
    }).join(" ");
  };
  return <section className="profile-comparison" aria-label="人口与地形叠加图">
    <header><strong>{record.name} · {result.total_distance_km.toFixed(2)} km</strong><button onClick={onClose} aria-label="关闭对比图">×</button></header>
    <div className="profile-comparison-legend"><span style={{color: colors[0]}}>● 人口密度（人/km²）</span><span style={{color: colors[1]}}>● 高程（米）</span></div>
    <svg viewBox="0 0 800 275" role="img" aria-label="以沿线距离为横轴的人口密度与高程双轴曲线"
      onPointerLeave={() => {setIndex(null); onHover(null);}}
      onPointerMove={e => {
        const box = e.currentTarget.getBoundingClientRect();
        const distance = Math.max(0, Math.min(1, (((e.clientX-box.left)/box.width)*800-70)/660)) * result.total_distance_km;
        const samples = result.population.samples;
        const i = samples.reduce((best,p,j) => Math.abs(p.distance_km-distance)<Math.abs(samples[best].distance_km-distance)?j:best,0);
        setIndex(i); onHover(samples[i]);
      }}>
      <path d="M70 40V230H730V40" fill="none" stroke="currentColor" opacity=".4"/>
      {series.map((s,k) => <g key={s.kind} fill={colors[k]}>
        <path d={path(s.samples,k)} fill="none" stroke={colors[k]} strokeWidth="2"/>
        <text x={k===0?6:735} y="38" fontSize="12">{scales[k].high.toFixed(0)}</text>
        <text x={k===0?6:735} y="230" fontSize="12">{scales[k].low.toFixed(0)}</text>
      </g>)}
      <text x="70" y="260">0 km</text><text x="650" y="260">{result.total_distance_km.toFixed(1)} km</text>
      {index !== null && <line x1={x(result.population.samples[index])} x2={x(result.population.samples[index])} y1="40" y2="230" stroke="#63758a" strokeDasharray="4 3"/>}
    </svg>
    {index !== null && <output>{result.population.samples[index].distance_km.toFixed(2)} km · {series.map(s => `${s.samples[index]?.value ?? "无数据"} ${s.unit}`).join(" / ")}</output>}
    <details><summary>数据来源与采样 · {result.paired_valid_count} 个有效对比点</summary>
      {series.map(s => <p key={s.kind}>{s.source_name} · {s.source_year} · 缺失 {s.no_data_count} 点{s.provenance ? ` · ${s.provenance.cached ? "真实数据缓存" : "本次获取"} ${s.provenance.fetched_at}` : ""}</p>)}
      <p>{result.interpretation_note}</p>
    </details>
  </section>;
}
