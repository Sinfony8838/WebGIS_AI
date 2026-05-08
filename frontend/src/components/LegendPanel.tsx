import type { GraduatedStyle } from "../types";

export type LegendPanelProps = {
  style: GraduatedStyle | null;
};

export function LegendPanel({ style }: LegendPanelProps): JSX.Element | null {
  if (!style) {
    return null;
  }
  const items = style.legend?.items || [];
  if (items.length === 0) {
    return null;
  }
  return (
    <section className="legend-panel" data-testid="legend-panel">
      <h4 className="legend-panel__title">{style.legend?.title || style.title || "图例"}</h4>
      <ul className="legend-panel__list">
        {items.map((item, index) => (
          <li key={`${item.label}-${index}`} className="legend-panel__item">
            <span
              className="legend-panel__swatch"
              style={{ backgroundColor: item.color }}
              aria-hidden
            />
            <span className="legend-panel__label">{item.label}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
