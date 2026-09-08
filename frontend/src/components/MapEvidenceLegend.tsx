import { DENSITY_SCALE } from "../lib/populationVisual";
import { GLOBE_THEMES } from "../lib/globeThemes";
import type { LayerRecord } from "../types";
import "./MapEvidenceLegend.css";

type Props = { layers:LayerRecord[]; globe:boolean; themeIds:string[]; showFit:boolean; onShowFit:(value:boolean)=>void };
export function MapEvidenceLegend({layers,globe,themeIds,showFit,onShowFit}:Props) {
  const visible = layers.filter(layer => layer.visible);
  const hasDensity = globe ? themeIds.some(id => ["density_fill","density_3d","population_columns"].includes(id)) : visible.some(layer => ["builtin_population_regions","builtin_population_density"].includes(layer.layer_id));
  const line = visible.find(layer => layer.layer_id === "generated_hu_line");
  const hasLine = globe ? themeIds.includes("hu_line") : Boolean(line);
  const otherThemes = globe ? GLOBE_THEMES.filter(theme => themeIds.includes(theme.id) && !["density_fill","density_3d","population_columns","hu_line"].includes(theme.id)) : [];
  const ranked = !globe && visible.some(layer => Boolean(layer.metadata?.visualization));
  if (!hasDensity && !hasLine && !otherThemes.length && !ranked) return null;
  const share = line?.metadata?.classic_share;
  return <section className="map-evidence-legend" aria-label="地图图例与依据">
    {hasDensity && <>
      <strong>人口密度 <small>人/km²</small></strong>
      <div className="map-density-key">{DENSITY_SCALE.map(item => <span key={item.label}><i style={{background:item.color}}/><small>{item.label}</small></span>)}</div>
      <p>省级平均值 · 七普及港澳台配套统计（2020/2021）。灰色为缺失数据。</p>
      {!globe && visible.some(layer => layer.layer_id === "builtin_population_density") && <p>圆点表示省级密度，非城市位置；半径按 √密度 缩放，4–24 px 截断。</p>}
      {globe && themeIds.includes("density_3d") && <p>高度按 √密度 夸张，不代表真实地形。</p>}
      {globe && themeIds.includes("population_columns") && <p>柱高表示人口总量；颜色表示密度；高度为视觉缩放。</p>}
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
  </section>;
}
