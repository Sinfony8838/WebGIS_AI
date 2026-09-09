import { useState } from "react";
import "./UrbanStudyPanel.css";

export type UrbanSource = { url:string; credit:string; kind:"photogrammetry"|"buildings"; format?:"geojson" };
export const SHANGHAI_BUILDINGS:UrbanSource = {url:"/data/shanghai-buildings.geojson",credit:"© OpenStreetMap contributors · ODbL · 2026-09-09 数据快照",kind:"buildings",format:"geojson"};
export type UrbanStatus = "idle"|"loading"|"manifest"|"visible"|"error";
export const SHANGHAI_STOPS = [
  { name:"陆家嘴", lon:121.505, lat:31.237, range:2600, question:"观察高层建筑与交通联系：商务集聚是否等于常住人口密集？" },
  { name:"中心城区", lon:121.473, lat:31.230, range:2300, question:"比较商务、居住与公共空间。解释人口分布还需要哪些街道或栅格统计？" },
  { name:"松江新城", lon:121.225, lat:31.030, range:2600, question:"与中心城区对照建筑形态、轨道交通和用地；讨论新城如何承接居住与就业。" }
];
export type UrbanStop = typeof SHANGHAI_STOPS[number];
const STATUS:Record<UrbanStatus,string> = { idle:"选择区域，加载内置建筑模型", loading:"正在连接数据源…", manifest:"数据目录已连接，等待当前视野瓦片…", visible:"三维数据已加载，可旋转和缩放观察", error:"加载失败，请检查数据覆盖、访问权限与跨域配置" };
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
      <div className="urban-study-stops">{SHANGHAI_STOPS.map((stop,index)=><button key={stop.name} aria-pressed={active&&selected===index} onClick={()=>{setSelected(index);onVisit(stop);if(!source)onSource(SHANGHAI_BUILDINGS);}}>{stop.name}</button>)}</div>
      <p>{SHANGHAI_STOPS[selected].question}</p>
      <p className="urban-study-status" role="status">{STATUS[status]}{source ? ` · ${source.kind==="photogrammetry"?"实景网格数据源":"建筑模型（非实景）"}`:""}</p>
      <p>建筑高度不等于人口密度。区级人口均值不能解释街区差异；需配套同年份的细尺度人口数据。</p>
      {source && <p>来源：{source.credit}</p>}
      {source?.format === "geojson" && <>
        <p>青绿：OSM 标注高度；蓝色：楼层数 × 3 米的估算；灰色：高度缺失，仅显示轮廓。局部覆盖，不是全市建筑普查或实景摄影。</p>
        <p>{selected === 2 ? "松江样本的 515 个轮廓均缺高度，当前仅显示轮廓，不能据此判断住宅低矮。" : selected === 0 ? "陆家嘴样本：24 个标注高度、50 个按楼层估算、350 个高度缺失。" : "中心城区样本：10 个标注高度、67 个按楼层估算、432 个高度缺失。"}</p>
        <p>悬停建筑查看高度依据。数据快照日期不代表建筑采集日期。</p>
        <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap 数据许可</a>{" · "}<a href="/data/shanghai-buildings.geojson" download>下载源数据</a>
      </>}
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
