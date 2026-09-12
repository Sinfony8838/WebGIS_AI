import { WEATHER_LEGENDS, type WeatherOverlayPhase } from "../lib/weatherOverlay";

type Props = {
  basemapId: string;
  title: string;
  phase: WeatherOverlayPhase;
  onRestoreBasemap?: () => void;
};

/**
 * 天气叠加状态卡片：显示天气类型、数据来源、加载状态与简化图例。
 * 只反映真实瓦片加载结果（loading/ready/error 由 App 的瓦片事件驱动），
 * 不包含任何模拟成功状态。
 */
export function WeatherOverlayStatus({ basemapId, title, phase, onRestoreBasemap }: Props) {
  const legend = WEATHER_LEGENDS[basemapId] ?? null;
  const statusText =
    phase === "loading"
      ? "加载中…"
      : phase === "ready"
        ? "实时瓦片已加载"
        : "加载失败";

  return (
    <section className="weather-overlay-status" aria-label="天气叠加状态" data-phase={phase}>
      <header className="weather-status-head">
        <strong>{title}</strong>
        <span className={`weather-status-chip phase-${phase}`} role="status">
          {statusText}
        </span>
      </header>
      <p className="weather-status-source">数据来源：OpenWeatherMap 实时栅格（经本课后端代理，密钥不出服务器）</p>
      {phase === "error" ? (
        <p className="weather-status-error">
          天气叠加未能加载：请检查后端 WEBGIS_AI_OPENWEATHERMAP_API_KEY 是否有效、外网是否可达。
          高德参考底图不受影响。
        </p>
      ) : null}
      {legend ? (
        <div className="weather-status-legend">
          <i className="weather-legend-scale" style={{ background: legend.gradient }} aria-hidden="true" />
          <small>
            {legend.caption}
            <a href="https://openweathermap.org/weathermap" target="_blank" rel="noreferrer">
              OpenWeatherMap 官方图例 ↗
            </a>
          </small>
        </div>
      ) : null}
      {phase === "error" && onRestoreBasemap ? (
        <button type="button" className="weather-restore-button" onClick={onRestoreBasemap}>
          恢复高德标准底图
        </button>
      ) : null}
    </section>
  );
}
