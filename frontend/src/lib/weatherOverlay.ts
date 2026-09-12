export type WeatherOverlayPhase = "idle" | "loading" | "ready" | "error";

/**
 * 各天气图层的简化图例：色带为示意（近似 OpenWeatherMap 官方色标），
 * 用于读图指引；精确数值以官方图例与数值接口为准，不在此伪造断点。
 */
export const WEATHER_LEGENDS: Record<string, { gradient: string; caption: string }> = {
  weather_precipitation: {
    gradient: "linear-gradient(90deg, #b3e5fc, #4fc3f7, #2962ff, #7c4dff)",
    caption: "降水强度：浅蓝（小雨）→ 蓝 → 深蓝紫（强降水）。",
  },
  weather_clouds: {
    gradient: "linear-gradient(90deg, #f5f5f5, #cfd8dc, #90a4ae, #546e7a)",
    caption: "云量：浅白（少云）→ 灰（多云/阴）。",
  },
  weather_temperature: {
    gradient: "linear-gradient(90deg, #4a148c, #3949ab, #43a047, #fdd835, #ef6c00, #b71c1c)",
    caption: "温度：蓝紫（冷）→ 绿 → 黄 → 红（热）。",
  },
  weather_wind: {
    gradient: "linear-gradient(90deg, #e0f7fa, #80deea, #ffb74d, #d84315)",
    caption: "风速：浅青（微风）→ 橙红（大风）。",
  },
  weather_pressure: {
    gradient: "linear-gradient(90deg, #eceff1, #b0bec5, #78909c, #37474f)",
    caption: "海平面气压：浅（低压）→ 深（高压）。",
  },
};

export const WEATHER_BASEMAP_PREFIX = "weather_";

export function isWeatherBasemapId(basemapId: string | undefined | null): boolean {
  return Boolean(basemapId && basemapId.startsWith(WEATHER_BASEMAP_PREFIX));
}
