import { useEffect, useMemo, useRef, useState } from "react";
import type { BasemapPreset } from "../types";

type Props = {
  items: BasemapPreset[];
  activeId: string;
  disabled?: boolean;
  /** 后端是否配置了 WEBGIS_AI_OPENWEATHERMAP_API_KEY；false 时天气选项仅提示、不切换。 */
  weatherEnabled?: boolean;
  /** 点击未配置的天气选项时触发，由宿主展示可操作提示。 */
  onWeatherBlocked?: (title: string, message: string) => void;
  onSelect: (basemapId: string) => void | Promise<void>;
};

const WEATHER_BLOCKED_MESSAGE =
  "天气底图未配置：请在后端设置 WEBGIS_AI_OPENWEATHERMAP_API_KEY 环境变量并重启服务。当前底图保持不变。";

type BasemapGroup = {
  id: "basic" | "thematic";
  title: string;
  description: string;
  items: BasemapPreset[];
};

type ThematicGroup = {
  id: "weather" | "population";
  title: string;
  description: string;
  items: BasemapPreset[];
};

function isWeatherBasemap(item: BasemapPreset): boolean {
  const normalizedId = item.id.toLowerCase();
  const normalizedTitle = item.title.toLowerCase();
  return (
    normalizedId.includes("weather") ||
    normalizedId.includes("openweather") ||
    normalizedTitle.includes("天气")
  );
}

function isPopulationBasemap(item: BasemapPreset): boolean {
  return ["nasa_nightlights_2016", "nasa_population_2020"].includes(item.id);
}

function displayTitle(item: BasemapPreset): string {
  if (item.id === "nasa_population_2020") return "人口热力图 · 2020";
  return item.title;
}

export function BasemapMenu({ items, activeId, disabled = false, weatherEnabled = true, onWeatherBlocked, onSelect }: Props) {
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [expandedGroup, setExpandedGroup] = useState<BasemapGroup["id"] | null>(null);
  const [expandedThematicGroup, setExpandedThematicGroup] = useState<ThematicGroup["id"] | null>(null);
  const [weatherBlockedHint, setWeatherBlockedHint] = useState(false);

  const activeItem = useMemo(
    () => items.find((item) => item.id === activeId) || items[0] || null,
    [activeId, items]
  );

  const groups = useMemo<BasemapGroup[]>(() => {
    const basicItems = items.filter((item) => !isWeatherBasemap(item) && !isPopulationBasemap(item));
    const thematicItems = items.filter((item) => isWeatherBasemap(item) || isPopulationBasemap(item));
    const nextGroups: BasemapGroup[] = [];

    if (basicItems.length > 0) {
      nextGroups.push({
        id: "basic",
        title: "基础底图",
        description: "标准、影像、浅灰与兼容底图",
        items: basicItems
      });
    }

    if (thematicItems.length > 0) {
      nextGroups.push({
        id: "thematic",
        title: "专题底图",
        description: "天气与人口专题可视化",
        items: thematicItems
      });
    }

    return nextGroups;
  }, [items]);

  const thematicGroups = useMemo<ThematicGroup[]>(() => {
    const nextGroups: ThematicGroup[] = [{
      id: "weather",
      title: "天气",
      description: "降水、云图、温度、风速与气压叠加",
      items: items.filter(isWeatherBasemap)
    },
    {
      id: "population",
      title: "人口",
      description: "夜间灯光与人口热力图",
      items: items.filter(isPopulationBasemap)
    }];
    return nextGroups.filter((group) => group.items.length > 0);
  }, [items]);

  const closeMenu = () => {
    setOpen(false);
    setExpandedGroup(null);
    setExpandedThematicGroup(null);
    setWeatherBlockedHint(false);
  };

  const handleSelect = (item: BasemapPreset) => {
    if (isWeatherBasemap(item) && !weatherEnabled) {
      setWeatherBlockedHint(true);
      onWeatherBlocked?.(item.title, WEATHER_BLOCKED_MESSAGE);
      return;
    }
    setWeatherBlockedHint(false);
    void onSelect(item.id);
    closeMenu();
  };

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        closeMenu();
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeMenu();
      }
    };

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  const handleTriggerClick = () => {
    setOpen((current) => !current);
    setExpandedGroup(null);
    setExpandedThematicGroup(null);
  };

  return (
    <div className="basemap-menu" ref={menuRef}>
      <button
        type="button"
        className={`toolbar-button basemap-trigger ${open ? "active" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled || !items.length}
        onClick={handleTriggerClick}
      >
        {`底图 · ${activeItem ? displayTitle(activeItem) : "未连接"}`}
      </button>

      {open ? (
        <div className="basemap-menu-panel glass-panel" role="menu" aria-label="底图选择">
          {groups.map((group) => {
            const activeChild = group.items.find((item) => item.id === activeId) || null;
            const expanded = expandedGroup === group.id;

            return (
              <div key={group.id} className={`basemap-group ${expanded ? "expanded" : ""}`}>
                <button
                  type="button"
                  className={`basemap-group-toggle ${expanded ? "active" : ""}`}
                  aria-expanded={expanded}
                  aria-controls={`basemap-group-${group.id}`}
                  onClick={() =>
                    setExpandedGroup((current) => (current === group.id ? null : group.id))
                  }
                >
                  <span className="basemap-group-copy">
                    <strong>
                      {group.title}
                    </strong>
                    <small>{activeChild ? displayTitle(activeChild) : group.description}</small>
                  </span>
                  <span className="basemap-group-arrow" aria-hidden="true">
                    {expanded ? "−" : "+"}
                  </span>
                </button>

                {expanded && group.id === "basic" ? (
                  <div
                    id={`basemap-group-${group.id}`}
                    className="basemap-group-options"
                    role="group"
                    aria-label={group.title}
                  >
                    {group.items.map((item) => {
                      const selected = item.id === activeId;
                      const blocked = false;

                      return (
                        <button
                          key={item.id}
                          type="button"
                          role="menuitemradio"
                          aria-checked={selected}
                          aria-disabled={blocked || undefined}
                          className={`basemap-option ${selected ? "active" : ""}`}
                          onClick={() => handleSelect(item)}
                        >
                          <strong>
                            {displayTitle(item)}
                          </strong>
                          <span>{item.description}</span>
                        </button>
                      );
                    })}
                  </div>
                ) : null}
                {expanded && group.id === "thematic" ? (
                  <div className="basemap-thematic-groups" role="group" aria-label="专题底图">
                    {thematicGroups.map((thematicGroup) => {
                      const thematicExpanded = expandedThematicGroup === thematicGroup.id;
                      const thematicActive = thematicGroup.items.find((item) => item.id === activeId) || null;
                      return (
                        <div key={thematicGroup.id} className={`basemap-subgroup ${thematicExpanded ? "expanded" : ""}`}>
                          <button
                            type="button"
                            className={`basemap-subgroup-toggle ${thematicExpanded ? "active" : ""}`}
                            aria-expanded={thematicExpanded}
                            aria-controls={`basemap-subgroup-${thematicGroup.id}`}
                            onClick={() => setExpandedThematicGroup((current) => current === thematicGroup.id ? null : thematicGroup.id)}
                          >
                            <span className="basemap-group-copy">
                              <strong>
                                {thematicGroup.title}
                                {thematicGroup.id === "weather" && !weatherEnabled ? <em className="basemap-weather-badge">未配置</em> : null}
                              </strong>
                              <small>{thematicActive ? displayTitle(thematicActive) : thematicGroup.description}</small>
                            </span>
                            <span className="basemap-group-arrow" aria-hidden="true">{thematicExpanded ? "−" : "+"}</span>
                          </button>
                          {thematicExpanded ? (
                            <div id={`basemap-subgroup-${thematicGroup.id}`} className="basemap-group-options" role="group" aria-label={thematicGroup.title}>
                              {thematicGroup.items.map((item) => {
                                const selected = item.id === activeId;
                                const blocked = thematicGroup.id === "weather" && !weatherEnabled;
                                return (
                                  <button
                                    key={item.id}
                                    type="button"
                                    role="menuitemradio"
                                    aria-checked={selected}
                                    aria-disabled={blocked || undefined}
                                    className={`basemap-option ${selected ? "active" : ""}`}
                                    onClick={() => handleSelect(item)}
                                  >
                                    <strong>{displayTitle(item)}{blocked ? <em className="basemap-weather-badge">未配置</em> : null}</strong>
                                    <span>{item.description}</span>
                                  </button>
                                );
                              })}
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            );
          })}
          {weatherBlockedHint ? (
            <p className="basemap-menu-hint" role="status">
              {WEATHER_BLOCKED_MESSAGE}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
