import { useEffect, useMemo, useRef, useState } from "react";
import type { BasemapPreset } from "../types";

type Props = {
  items: BasemapPreset[];
  activeId: string;
  disabled?: boolean;
  onSelect: (basemapId: string) => void | Promise<void>;
};

type BasemapGroup = {
  id: "basic" | "weather";
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

export function BasemapMenu({ items, activeId, disabled = false, onSelect }: Props) {
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [expandedGroup, setExpandedGroup] = useState<BasemapGroup["id"] | null>(null);

  const activeItem = useMemo(
    () => items.find((item) => item.id === activeId) || items[0] || null,
    [activeId, items]
  );

  const groups = useMemo<BasemapGroup[]>(() => {
    const basicItems = items.filter((item) => !isWeatherBasemap(item));
    const weatherItems = items.filter((item) => isWeatherBasemap(item));
    const nextGroups: BasemapGroup[] = [];

    if (basicItems.length > 0) {
      nextGroups.push({
        id: "basic",
        title: "基础底图",
        description: "标准、影像、浅灰与兼容底图",
        items: basicItems
      });
    }

    if (weatherItems.length > 0) {
      nextGroups.push({
        id: "weather",
        title: "天气底图",
        description: "降水、云图、温度、风速与气压叠加",
        items: weatherItems
      });
    }

    return nextGroups;
  }, [items]);

  const closeMenu = () => {
    setOpen(false);
    setExpandedGroup(null);
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
        {`底图 · ${activeItem?.title || "未连接"}`}
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
                    <strong>{group.title}</strong>
                    <small>{activeChild?.title || group.description}</small>
                  </span>
                  <span className="basemap-group-arrow" aria-hidden="true">
                    {expanded ? "−" : "+"}
                  </span>
                </button>

                {expanded ? (
                  <div
                    id={`basemap-group-${group.id}`}
                    className="basemap-group-options"
                    role="group"
                    aria-label={group.title}
                  >
                    {group.items.map((item) => {
                      const selected = item.id === activeId;

                      return (
                        <button
                          key={item.id}
                          type="button"
                          role="menuitemradio"
                          aria-checked={selected}
                          className={`basemap-option ${selected ? "active" : ""}`}
                          onClick={async () => {
                            await onSelect(item.id);
                            closeMenu();
                          }}
                        >
                          <strong>{item.title}</strong>
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
}
