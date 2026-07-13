import type { StatsPayload, StatsRow } from "../types";

export type StatsPanelProps = {
  stats: StatsPayload | null;
};

function formatCell(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      return "—";
    }
    if (Math.abs(value) >= 1000 || (Math.abs(value) > 0 && Math.abs(value) < 0.01)) {
      return value.toExponential(2);
    }
    return Number.isInteger(value) ? value.toString() : value.toFixed(2);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return String(value);
}

export function StatsPanel({ stats }: StatsPanelProps): JSX.Element | null {
  if (!stats) {
    return null;
  }
  const rows: StatsRow[] = stats.rows || [];
  const fields = stats.fields || (rows.length > 0 ? Object.keys(rows[0]) : []);
  const summary = stats.summary || {};

  return (
    <section className="stats-panel" data-testid="stats-panel">
      <h4 className="stats-panel__title">{stats.title || "统计结果"}</h4>
      {Object.keys(summary).length > 0 ? (
        <ul className="stats-panel__summary">
          {Object.entries(summary).map(([key, value]) => (
            <li key={key} className="stats-panel__summary-item">
              <span className="stats-panel__summary-key">{key}</span>
              <span className="stats-panel__summary-value">{formatCell(value)}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {rows.length > 0 ? (
        <div className="stats-panel__table-wrapper">
          <table className="stats-panel__table">
            <thead>
              <tr>
                {fields.map((field) => (
                  <th key={field}>{field}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => (
                <tr key={idx}>
                  {fields.map((field) => (
                    <td key={field}>{formatCell(row[field])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="stats-panel__empty">暂无统计数据。</p>
      )}
    </section>
  );
}
