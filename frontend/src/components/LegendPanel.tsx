import type { WorkflowLayerStyle } from "../types";

export type LegendPanelProps = {
  style: WorkflowLayerStyle | null;
  /** Items at/after this index are dimmed while a replay has not reached
   * them yet; leave undefined to show every item fully revealed. */
  revealedItems?: number;
};

export function LegendPanel({ style, revealedItems }: LegendPanelProps): JSX.Element | null {
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
        {items.map((item, index) => {
          const pending = revealedItems != null && index >= revealedItems;
          return (
            <li
              key={`${item.label}-${index}`}
              className={`legend-panel__item${pending ? " legend-panel__item--pending" : ""}`}
              data-pending={pending || undefined}
            >
              <span
                className="legend-panel__swatch"
                style={{ backgroundColor: item.color }}
                aria-hidden
              />
              <span className="legend-panel__label">{item.label}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
