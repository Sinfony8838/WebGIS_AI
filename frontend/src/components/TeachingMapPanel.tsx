import { useCallback, useMemo, useState } from "react";
import type { TeachingMapItem } from "../api";

interface Props {
  items: TeachingMapItem[];
  activeIds: Set<string>;
  busy: boolean;
  onToggle: (mapId: string, visible: boolean) => void;
}

interface CategoryGroup {
  category: string;
  order: number;
  items: TeachingMapItem[];
}

export function TeachingMapPanel({ items, activeIds, busy, onToggle }: Props) {
  const [collapsed, setCollapsed] = useState(false);

  const groups = useMemo<CategoryGroup[]>(() => {
    const map = new Map<string, CategoryGroup>();
    for (const item of items) {
      const key = item.category || "其他";
      if (!map.has(key)) {
        map.set(key, { category: key, order: item.category_order, items: [] });
      }
      map.get(key)!.items.push(item);
    }
    return Array.from(map.values()).sort((a, b) => a.order - b.order);
  }, [items]);

  const handleToggle = useCallback(
    (mapId: string) => {
      const isActive = activeIds.has(mapId);
      onToggle(mapId, !isActive);
    },
    [activeIds, onToggle]
  );

  if (items.length === 0) {
    return null;
  }

  return (
    <section className={`tool-group glass-panel teaching-map-panel ${collapsed ? "collapsed" : "expanded"}`}>
      <div
        className="tool-group-header teaching-map-header"
        onClick={() => setCollapsed((prev) => !prev)}
        role="button"
        tabIndex={0}
        aria-expanded={!collapsed}
      >
        <span>📚 课本地图</span>
        <span className="teaching-map-toggle-icon">{collapsed ? "▸" : "▾"}</span>
      </div>
      {!collapsed && (
        <div className="teaching-map-body">
          {groups.map((group) => (
            <div key={group.category} className="teaching-map-category">
              <div className="teaching-map-category-title">{group.category}</div>
              {group.items.map((item) => {
                const isActive = activeIds.has(item.id);
                return (
                  <label
                    key={item.id}
                    className={`teaching-map-item ${isActive ? "active" : ""} ${busy ? "busy" : ""}`}
                    title={item.name}
                  >
                    <input
                      type="checkbox"
                      checked={isActive}
                      disabled={busy}
                      onChange={() => handleToggle(item.id)}
                    />
                    <span className="teaching-map-item-name">{item.name}</span>
                  </label>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
