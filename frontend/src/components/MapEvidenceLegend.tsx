import { useId, useState } from "react";
import { DENSITY_SCALE, SHANGHAI_DENSITY_SCALE } from "../lib/populationVisual";
import { GLOBE_THEMES } from "../lib/globeThemes";
import type { LayerRecord } from "../types";
import "./MapEvidenceLegend.css";

type Props = { basemapId?:string; layers:LayerRecord[]; globe:boolean; themeIds:string[]; showFit:boolean; onShowFit:(value:boolean)=>void };
export function MapEvidenceLegend({basemapId,layers,globe,themeIds,showFit,onShowFit}:Props) {
  const contentId = useId();
  const [expanded, setExpanded] = useState(() => !window.matchMedia?.("(max-width: 960px)").matches);
  const night = !globe && basemapId === "nasa_nightlights_2016";
  const populationGrid = !globe && basemapId === "nasa_population_2020";
  const visible = layers.filter(layer => layer.visible);
  const hasDensity = globe ? themeIds.some(id => ["density_fill","density_3d","population_columns"].includes(id)) : visible.some(layer => ["builtin_population_regions","builtin_population_density"].includes(layer.layer_id));
  const shanghai = !globe && visible.find(layer => layer.metadata?.catalog_id === "shanghai_population_density");
  const line = visible.find(layer => layer.layer_id === "generated_hu_line");
  const hasLine = globe ? themeIds.includes("hu_line") : Boolean(line);
  const otherThemes = globe ? GLOBE_THEMES.filter(theme => themeIds.includes(theme.id) && !["density_fill","density_3d","population_columns","hu_line"].includes(theme.id)) : [];
  const ranked = !globe && visible.some(layer => Boolean(layer.metadata?.visualization));
  if (!night && !populationGrid && !shanghai && !hasDensity && !hasLine && !otherThemes.length && !ranked) return null;
  const share = line?.metadata?.classic_share;
  return <section className={`map-evidence-legend${expanded ? "" : " is-collapsed"}`} aria-label="地图图例与依据">
    <button className="map-legend-toggle" aria-expanded={expanded} aria-controls={contentId} onClick={() => setExpanded(value => !value)}>
      图例与数据 <span aria-hidden="true">{expanded ? "−" : "+"}</span>
    </button>
    <div id={contentId} className="map-legend-content" hidden={!expanded}>
    {night && <><strong>夜间灯光 <small>2016 · VIIRS</small></strong><p>亮度表示夜间灯光活动，受照明、产业和能源使用影响；不能直接换算人口或密度。</p><a href="https://worldview.earthdata.nasa.gov/?l=VIIRS_Black_Marble" target="_blank" rel="noreferrer">NASA Black Marble 来源 ↗</a></>}
    {populationGrid && <><strong>全球人口密度 <small>2020 · 人/km²</small></strong><img src="https://gibs.earthdata.nasa.gov/legends/GPW_Population_Density_2020_H.svg" alt="NASA GPW官方图例，浅黄低于1，深红大于等于1000人每平方千米" style={{width:"100%",height:"auto"}}/><p>GPW 人口栅格估计，非逐户测量；透明处为缺失。此图用于比较空间格局，瓦片不提供点击数值查询。</p><a href="https://gibs.earthdata.nasa.gov/colormaps/v1.3/GPW_Population_Density_2020.xml" target="_blank" rel="noreferrer">NASA 官方色标与单位 ↗</a></>}
    {hasDensity && <>
      <strong>人口密度 <small>人/km²</small></strong>
      <div className="map-density-key">{DENSITY_SCALE.map(item => <span key={item.label}><i style={{background:item.color}}/><small>{item.label}</small></span>)}</div>
      <p>省级平均值 · 七普及港澳台配套统计（2020/2021）。灰色为缺失数据。</p>
      {!globe && visible.some(layer => layer.layer_id === "builtin_population_density") && <p>圆点表示省级密度，非城市位置；半径按 √密度 缩放，4–24 px 截断。</p>}
      {globe && themeIds.includes("density_3d") && <p>高度按 √密度 夸张，不代表真实地形。</p>}
      {globe && themeIds.includes("population_columns") && <p>柱高表示人口总量；颜色表示密度；高度为视觉缩放。</p>}
    </>}
    {shanghai && <>
      <strong>上海 · 人口密度 <small>人/km²</small></strong>
      <div className="map-density-key">{SHANGHAI_DENSITY_SCALE.map(item => <span key={item.label}><i style={{background:item.color}}/><small>{item.label}</small></span>)}</div>
      <p>2020 年常住人口 ÷ 区域面积 · 区级平均值，不能代表街镇或居住用地密度。</p>
      <details><summary>数据来源与口径</summary>
        <p>人口：上海市第七次全国人口普查。面积：《上海统计年鉴2021》表2.2（2020年）。密度由七普时点人口计算，与年末人口密度不同。</p>
        <a href="https://tjj.sh.gov.cn/tjnj/2020rktjnj/fu02.pdf" target="_blank" rel="noreferrer">上海统计局 · 各区常住人口 ↗</a>
        <a href="https://tjj.sh.gov.cn/tjnj/2021tjnj/C0202.htm" target="_blank" rel="noreferrer">2020 年区划面积 ↗</a>
        <p>按 1千、5千、1万、2万人/km² 分级；灰色表示缺失。点击区县查看数值。</p>
      </details>
    </>}
    {ranked && <><strong>人口排名图层</strong><p>深蓝到浅蓝表示排名由前到后，具体数值与年份见查询结果。行政区总量不等于城区密度。</p></>}
    {hasLine && <>
      <strong><i className="map-line-key"/>胡焕庸线 <small>黑河—腾冲参考连线</small></strong>
      <details><summary>查看依据与算法</summary>
        <p>1935 年提出。连接两地参考坐标，属于人口地理概括，非测绘边界。</p>
        <p>1935 年口径：东南侧约 36% 国土、96% 人口；后来的国土与统计口径不同，不能混用年份。</p>
        <a href="https://www.geog.com.cn/CN/abstract/article/0375-5444/37311" target="_blank" rel="noreferrer">依据：《地理学报》胡焕庸线两侧人口研究 ↗</a>
        {!globe && <>
          <label><input type="checkbox" checked={showFit} onChange={event=>onShowFit(event.target.checked)}/>显示教学拟合线（非新的胡焕庸线）</label>
          <p>使用 2020 地级行政单元人口及几何中心，固定经典线方向，在经纬度平面内平移，寻找东南侧人口份额最接近预设 94% 的位置。</p>
          <p>将跨线行政区全部归到中心点一侧；不是人口栅格切分，没有误差区间，不能据此判断真实边界移动。</p>
          {typeof share === "number" && <p>本数据按中心点估计的经典线东南侧占比：{(share*100).toFixed(1)}%。</p>}
        </>}
      </details>
      {showFit && !globe && <p className="map-fit-note">橙色虚线：预设 94% 目标的教学拟合；非实测分界。</p>}
    </>}
    {otherThemes.map(theme => <div key={theme.id}><strong>{theme.legendTitle || theme.name}</strong><p>{theme.legendNote || theme.description}</p>{theme.legend?.map(item=><span className="map-other-key" key={item.label}><i style={{background:item.color}}/>{item.label}</span>)}</div>)}
    </div>
  </section>;
}
