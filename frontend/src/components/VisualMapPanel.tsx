import { useCallback, useMemo, useState } from "react";
import {
  GLOBE_SCENE_PRESETS,
  GLOBE_THEMES,
  type GlobeScenePreset,
  type GlobeThemeDef,
  type GlobeThemeId
} from "../lib/globeThemes";
import type { ViewMode } from "../lib/viewMode";

/** 二维目录图层条目（原 TeachingMapPanel 的形状，兼容一张图目录数据集）。 */
export interface TeachingMapEntry {
  id: string;
  name: string;
  category: string;
  category_order: number;
}

type TopicGroup = {
  topic: string;
  order: number;
  /** 该主题下的三维专题图层 id。 */
  themeIds: GlobeThemeId[];
  /** 对应的二维目录分类标签（如有）。 */
  category?: string;
};

/** 按地理主题重组：三维专题图层与二维目录图层归入同一主题组。 */
const TOPIC_GROUPS: TopicGroup[] = [
  { topic: "人口", order: 1, themeIds: ["density_fill", "density_3d", "population_columns"], category: "人口" },
  { topic: "气候", order: 2, themeIds: ["climate_zones"], category: "气候" },
  { topic: "胡焕庸线", order: 3, themeIds: ["hu_line"] },
  { topic: "人口迁徙", order: 4, themeIds: ["migration_flows"] },
  { topic: "行政边界", order: 5, themeIds: [], category: "行政边界" },
  { topic: "经济", order: 6, themeIds: [], category: "经济" },
  { topic: "城市与交通", order: 7, themeIds: [], category: "城市与交通" },
  { topic: "专题", order: 8, themeIds: [], category: "专题" }
];

type Props = {
  viewMode: ViewMode;
  activeThemeIds: string[];
  onChangeThemes: (ids: string[]) => void;
  onApplyScene: (preset: GlobeScenePreset) => void;
  textbookItems: TeachingMapEntry[];
  textbookActiveIds: Set<string>;
  busy: boolean;
  onToggleTextbook: (id: string, visible: boolean) => void;
};

export function VisualMapPanel({
  viewMode,
  activeThemeIds,
  onChangeThemes,
  onApplyScene,
  textbookItems,
  textbookActiveIds,
  busy,
  onToggleTextbook
}: Props) {
  const [collapsed, setCollapsed] = useState(true);

  const active = useMemo(() => new Set(activeThemeIds), [activeThemeIds]);

  const themeById = useMemo(() => {
    const map = new Map<GlobeThemeId, GlobeThemeDef>();
    for (const theme of GLOBE_THEMES) map.set(theme.id, theme);
    return map;
  }, []);

  const toggleTheme = useCallback(
    (id: GlobeThemeId) => {
      const next = new Set(activeThemeIds);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
        // 密度设色与密度高度映射是同一数据的两种表达，互斥切换。
        if (id === "density_fill") next.delete("density_3d");
        if (id === "density_3d") next.delete("density_fill");
      }
      onChangeThemes([...next]);
    },
    [activeThemeIds, onChangeThemes]
  );

  const sceneIsActive = (preset: GlobeScenePreset) =>
    preset.themes.length === active.size && preset.themes.every((id) => active.has(id));

  const legends = GLOBE_THEMES.filter(
    (theme) => active.has(theme.id) && (theme.legend?.length || theme.legendNote)
  );

  // 组装每个主题组实际可渲染的 3D/2D 条目，空组跳过。
  const renderedGroups = useMemo(() => {
    return TOPIC_GROUPS.map((group) => {
      const themes = group.themeIds.map((id) => themeById.get(id)).filter((t): t is GlobeThemeDef => Boolean(t));
      const items = group.category ? textbookItems.filter((item) => item.category === group.category) : [];
      return { ...group, themes, items };
    }).filter((group) => group.themes.length > 0 || group.items.length > 0);
  }, [themeById, textbookItems]);

  return (
    <section
      className={`tool-group glass-panel visual-map-panel ${collapsed ? "collapsed" : "expanded"}`}
      data-testid="visual-map-panel"
    >
      <div
        className="tool-group-header visual-map-header"
        onClick={() => setCollapsed((prev) => !prev)}
        role="button"
        tabIndex={0}
        aria-expanded={!collapsed}
      >
        <span aria-hidden>🗺️</span>
        <span className="visual-map-title">可视化地图</span>
        <span className="visual-map-mode-hint">{viewMode === "globe" ? "地球模式" : "平面模式"}</span>
        <span className="teaching-map-toggle-icon">{collapsed ? "▸" : "▾"}</span>
      </div>

      {!collapsed && (
        <div className="visual-map-body">
          <p className="globe-theme-panel__section-label">一键教学场景</p>
          <div className="visual-map-scenes" data-testid="visual-map-scenes">
            {GLOBE_SCENE_PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className={`globe-scene-chip ${sceneIsActive(preset) ? "is-active" : ""}`}
                title={preset.description}
                data-testid={`globe-scene-${preset.id}`}
                onClick={() => onApplyScene(preset)}
              >
                <span className="globe-scene-chip__icon" aria-hidden>
                  {preset.icon}
                </span>
                {preset.name}
              </button>
            ))}
          </div>

          {renderedGroups.map((group) => (
            <div key={group.topic} className="visual-map-topic" data-testid={`visual-map-topic-${group.topic}`}>
              <div className="visual-map-topic-title">{group.topic}</div>
              <div className="visual-map-topic-items">
                {group.themes.map((theme) => {
                  const checked = active.has(theme.id);
                  return (
                    <button
                      key={theme.id}
                      type="button"
                      role="switch"
                      aria-checked={checked}
                      className={`globe-theme-toggle ${checked ? "is-active" : ""}`}
                      title={theme.description}
                      data-testid={`globe-theme-toggle-${theme.id}`}
                      onClick={() => toggleTheme(theme.id)}
                    >
                      <span className="visual-map-badge visual-map-badge-3d" aria-hidden>3D</span>
                      <span className="globe-theme-toggle__dot" aria-hidden />
                      {theme.name}
                    </button>
                  );
                })}
                {group.items.map((item) => {
                  const isActive = textbookActiveIds.has(item.id);
                  return (
                    <label
                      key={item.id}
                      className={`teaching-map-item ${isActive ? "active" : ""} ${busy ? "busy" : ""}`}
                      title={item.name}
                    >
                      <span className="visual-map-badge visual-map-badge-2d" aria-hidden>2D</span>
                      <input
                        type="checkbox"
                        checked={isActive}
                        disabled={busy}
                        onChange={() => onToggleTextbook(item.id, !isActive)}
                      />
                      <span className="teaching-map-item-name">{item.name}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          ))}

          {legends.length > 0 ? (
            <div className="globe-theme-panel__legends" data-testid="globe-theme-legends">
              {legends.map((theme) => (
                <div key={theme.id} className="globe-theme-legend">
                  <p className="globe-theme-legend__title">{theme.legendTitle || theme.name}</p>
                  {theme.legend?.length ? (
                    <ul className="globe-theme-legend__list">
                      {theme.legend.map((item) => (
                        <li key={item.label}>
                          <span
                            className="globe-theme-legend__swatch"
                            style={{ backgroundColor: item.color }}
                            aria-hidden
                          />
                          {item.label}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {theme.legendNote ? (
                    <p className="globe-theme-legend__note">{theme.legendNote}</p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
