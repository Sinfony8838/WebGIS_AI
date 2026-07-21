import { useMemo, useState } from "react";
import {
  GLOBE_SCENE_PRESETS,
  GLOBE_THEMES,
  type GlobeScenePreset,
  type GlobeThemeId
} from "../lib/globeThemes";

export type GlobeThemePanelProps = {
  activeThemeIds: string[];
  onChangeThemes: (ids: string[]) => void;
  onApplyScene: (preset: GlobeScenePreset) => void;
};

/**
 * Floating control panel shown in 3D globe mode: one-click teaching scene
 * presets, individual theme toggles, and a dynamic legend for whatever is
 * currently on the globe.
 */
export function GlobeThemePanel({
  activeThemeIds,
  onChangeThemes,
  onApplyScene
}: GlobeThemePanelProps): JSX.Element {
  const [collapsed, setCollapsed] = useState(true);
  const active = useMemo(() => new Set(activeThemeIds), [activeThemeIds]);

  const toggleTheme = (id: GlobeThemeId) => {
    const next = new Set(active);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
      // 密度设色与密度高度映射是同一数据的两种表达，互斥切换。
      if (id === "density_fill") next.delete("density_3d");
      if (id === "density_3d") next.delete("density_fill");
    }
    onChangeThemes([...next]);
  };

  const sceneIsActive = (preset: GlobeScenePreset) =>
    preset.themes.length === active.size && preset.themes.every((id) => active.has(id));

  const legends = GLOBE_THEMES.filter(
    (theme) => active.has(theme.id) && (theme.legend?.length || theme.legendNote)
  );

  return (
    <section
      className={`globe-theme-panel glass-panel ${collapsed ? "is-collapsed" : ""}`}
      data-testid="globe-theme-panel"
    >
      <header className="globe-theme-panel__header">
        <h4>
          <span aria-hidden>🌏</span> 三维专题教学
        </h4>
        <div className="globe-theme-panel__header-actions">
          {active.size > 0 ? (
            <button
              type="button"
              className="globe-theme-panel__clear"
              data-testid="globe-theme-clear"
              onClick={() => onChangeThemes([])}
            >
              清空
            </button>
          ) : null}
          <button
            type="button"
            className="globe-theme-panel__collapse"
            aria-label={collapsed ? "展开三维专题面板" : "收起三维专题面板"}
            onClick={() => setCollapsed((value) => !value)}
          >
            {collapsed ? "▸" : "▾"}
          </button>
        </div>
      </header>

      {!collapsed ? (
        <div className="globe-theme-panel__body">
          <p className="globe-theme-panel__section-label">一键教学场景</p>
          <div className="globe-theme-panel__scenes">
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

          <p className="globe-theme-panel__section-label">专题图层</p>
          <div className="globe-theme-panel__toggles">
            {GLOBE_THEMES.map((theme) => {
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
                  <span className="globe-theme-toggle__dot" aria-hidden />
                  {theme.name}
                </button>
              );
            })}
          </div>

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
      ) : null}
    </section>
  );
}
