import { rankColor } from "../lib/populationVisual";
import { useEffect, useMemo, useState } from "react";
import type { LayerRecord } from "../types";

export type VisualizationItem = {
  rank: number;
  name?: string;
  province?: string;
  value?: number;
  unit?: string;
  share?: number;
  fill_color?: string;
};

type Visualization = {
  type: string;
  x?: string;
  y?: string;
  unit?: string;
  title?: string;
  items?: VisualizationItem[];
  palette?: string[];
  maximum?: number;
};

type Props = {
  layer: LayerRecord | null;
  /** 课中面板展开时右移，避免与左侧面板互相压盖。 */
  shifted?: boolean;
  onClose: () => void;
  onFocusItem: (item: VisualizationItem, layer: LayerRecord) => void;
};

const MIN_DISPLAY_VALUE = 1;

function formatPopulation(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "—";
  }
  const wan = value / 10000;
  if (wan >= 100) {
    return `${wan.toFixed(0)} 万人`;
  }
  if (wan >= 1) {
    return `${wan.toFixed(1)} 万人`;
  }
  return `${value.toLocaleString()} 人`;
}

function resolveItems(layer: LayerRecord | null): VisualizationItem[] {
  if (!layer) {
    return [];
  }
  const visualization = (layer.metadata || {}).visualization as Visualization | undefined;
  if (visualization && Array.isArray(visualization.items) && visualization.items.length > 0) {
    return visualization.items.slice().sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0)).map((item,index) => ({...item, fill_color:rankColor(index+1,visualization.items!.length)}));
  }
  const features = Array.isArray((layer.data as { features?: unknown[] }).features)
    ? ((layer.data as { features: Array<Record<string, unknown>> }).features)
    : [];
  return features
    .map((feature, index) => {
      const properties = (feature.properties as Record<string, unknown>) || {};
      return {
        rank: Number(properties.rank ?? index + 1),
        name: String(properties.name ?? ""),
        province: String(properties.province ?? ""),
        value: Number(properties.value ?? properties.population_2020 ?? 0),
        unit: String(properties.unit ?? "人"),
        fill_color: rankColor(Number(properties.rank ?? index + 1), features.length),
      } satisfies VisualizationItem;
    })
    .sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0));
}

function resolveTitle(layer: LayerRecord | null): string {
  if (!layer) {
    return "指标查询";
  }
  const visualization = (layer.metadata || {}).visualization as Visualization | undefined;
  if (visualization?.title) {
    return visualization.title;
  }
  return layer.name || "指标查询";
}

function resolveUnit(layer: LayerRecord | null, visualization: Visualization | null): string {
  if (visualization?.unit) {
    return visualization.unit;
  }
  if (layer?.metadata?.unit) {
    return String(layer.metadata.unit);
  }
  return "人";
}

function resolveMaximum(items: VisualizationItem[], fallback: number): number {
  if (items.length === 0) {
    return Math.max(fallback, MIN_DISPLAY_VALUE);
  }
  const maximum = items.reduce(
    (current, item) => Math.max(current, typeof item.value === "number" ? item.value : 0),
    0,
  );
  return Math.max(maximum, MIN_DISPLAY_VALUE);
}

export function VisualQueryPopup({ layer, shifted = false, onClose, onFocusItem }: Props) {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    if (layer) {
      setIsVisible(true);
      return;
    }
    setIsVisible(false);
    return;
  }, [layer]);

  const items = useMemo(() => resolveItems(layer), [layer]);
  const visualization = useMemo(
    () => (layer ? ((layer.metadata || {}).visualization as Visualization | undefined) ?? null : null),
    [layer],
  );
  const title = useMemo(() => resolveTitle(layer), [layer]);
  const unit = useMemo(() => resolveUnit(layer, visualization), [layer, visualization]);
  const maximum = useMemo(
    () => resolveMaximum(items, visualization?.maximum ?? 0),
    [items, visualization],
  );

  if (!layer || !isVisible) {
    return null;
  }

  return (
    <aside
      className={`visual-query-popup${shifted ? " shifted" : ""}`}
      data-testid="visual-query-popup"
      role="dialog"
      aria-label="指标查询柱状图"
    >
      <header className="visual-query-header">
        <div>
          <p className="panel-tag">Visual Query</p>
          <h3 data-testid="visual-query-title">{title}</h3>
        </div>
        <button
          type="button"
          className="visual-query-close"
          aria-label="关闭指标查询弹窗"
          data-testid="visual-query-close"
          onClick={() => {
            setIsVisible(false);
            onClose();
          }}
        >
          ×
        </button>
      </header>
      <div className="visual-query-meta">
        <span>共 {items.length} 个 {unit === "人" ? "城市" : "对象"}</span>
        <span>最高 {formatPopulation(maximum)}</span>
      </div>
      <ul className="visual-query-bars" data-testid="visual-query-bars">
        {items.map((item) => {
          const value = typeof item.value === "number" ? item.value : 0;
          const ratio = Math.max(0, Math.min(1, value / maximum));
          const widthPct = Math.max(ratio * 100, ratio > 0 ? 4 : 0);
          const barColor = item.fill_color || "#f97316";
          return (
            <li
              key={`${item.rank}-${item.name}`}
              className="visual-query-bar-row"
              data-testid={`visual-query-bar-${item.rank}`}
            >
              <button
                type="button"
                className="visual-query-bar-button"
                onClick={() => onFocusItem(item, layer)}
                aria-label={`定位到 ${item.name ?? `第${item.rank}名`}`}
              >
                <span className="visual-query-bar-label">
                  <span className="visual-query-bar-rank">{item.rank}</span>
                  <span className="visual-query-bar-name">
                    {item.name ?? "未命名"}
                    {item.province && item.province !== item.name ? (
                      <small>{item.province}</small>
                    ) : null}
                  </span>
                </span>
                <span className="visual-query-bar-track">
                  <span
                    className="visual-query-bar-fill"
                    style={{ width: `${widthPct}%`, background: barColor }}
                  />
                </span>
                <span className="visual-query-value" data-testid={`visual-query-value-${item.rank}`}>
                  {formatPopulation(value)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
