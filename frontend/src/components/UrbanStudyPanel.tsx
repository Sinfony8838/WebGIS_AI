import { useState } from "react";
import "./UrbanStudyPanel.css";

export type UrbanSource = { url:string; credit:string; kind:"photogrammetry"|"buildings" };
export type UrbanStatus = "idle"|"loading"|"manifest"|"visible"|"error";
export const SHANGHAI_STOPS = [
  { name:"陆家嘴", lon:121.505, lat:31.237, range:6500, question:"观察高层建筑与交通联系：商务集聚是否等于常住人口密集？" },
  { name:"中心城区", lon:121.473, lat:31.230, range:26000, question:"比较商务、居住与公共空间。解释人口分布还需要哪些街道或栅格统计？" },
  { name:"松江新城", lon:121.225, lat:31.030, range:16000, question:"与中心城区对照建筑形态、轨道交通和用地；讨论新城如何承接居住与就业。" }
];
export type UrbanStop = typeof SHANGHAI_STOPS[number];
const STATUS:Record<UrbanStatus,string> = { idle:"未接入三维数据 · 当前仅底图定位", loading:"正在连接数据源…", manifest:"数据目录已连接，等待当前视野瓦片…", visible:"当前视野已呈现三维瓦片", error:"加载失败，请检查数据覆盖、访问权限与跨域配置" };
export function UrbanStudyPanel({active,source,status,onVisit,onSource,onExit}:{active:boolean;source:UrbanSource|null;status:UrbanStatus;onVisit:(stop:UrbanStop)=>void;onSource:(source:UrbanSource|null)=>void;onExit:()=>void}) {
  const [selected,setSelected]=useState(0);
  const [url,setUrl]=useState("");
  const [credit,setCredit]=useState("");
  const [kind,setKind]=useState<UrbanSource["kind"]>("photogrammetry");
  const [error,setError]=useState("");
  return <details className="urban-study-panel">
    <summary>城市空间与人口</summary>
    <div className="urban-study-body">
      <strong>上海 · 多尺度观察</strong>
      <div className="urban-study-stops">{SHANGHAI_STOPS.map((stop,index)=><button key={stop.name} aria-pressed={active&&selected===index} onClick={()=>{setSelected(index);onVisit(stop);}}>{stop.name}</button>)}</div>
      <p>{SHANGHAI_STOPS[selected].question}</p>
      <p className="urban-study-status" role="status">{STATUS[status]}{source ? ` · ${source.kind==="photogrammetry"?"实景网格数据源":"建筑模型（非实景）"}`:""}</p>
      <p>建筑高度不等于人口密度。当前省级人口数据不能解释街区差异；需配套同年份的细尺度人口数据。</p>
      {source && <p>来源：{source.credit}</p>}
      <details><summary>接入三维数据</summary>
        <form onSubmit={event=>{event.preventDefault();try {const parsed=new URL(url);if(!["http:","https:"].includes(parsed.protocol)||parsed.username||parsed.password)throw new Error();if(!credit.trim())throw new Error();setError("");onVisit(SHANGHAI_STOPS[selected]);onSource({url:parsed.href,credit:credit.trim(),kind});} catch {setError("请填写有效的 HTTP(S) 数据地址和来源署名。");}}}>
          <label>3D Tiles 地址<input type="url" required value={url} onChange={event=>setUrl(event.target.value)} placeholder="https://…/tileset.json" autoComplete="off"/></label>
          <label>数据来源与署名<input required maxLength={160} value={credit} onChange={event=>setCredit(event.target.value)} placeholder="数据提供方 / 采集年份"/></label>
          <label>数据类型<select value={kind} onChange={event=>setKind(event.target.value as UrbanSource["kind"])}><option value="photogrammetry">倾斜摄影 / 实景网格</option><option value="buildings">建筑模型（非实景）</option></select></label>
          <p>使用可访问的地理配准数据源；地址仅保留在本次页面会话。上海覆盖须向提供方核实。</p>
          {error&&<p role="alert">{error}</p>}
          <button type="submit">连接数据</button>{source&&<button type="button" onClick={()=>onSource(null)}>移除三维数据</button>}
        </form>
      </details>
      {active&&<button onClick={onExit}>退出城市观察</button>}
    </div>
  </details>;
}
