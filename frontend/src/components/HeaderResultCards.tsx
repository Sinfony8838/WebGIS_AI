import type { DatasetStatsResponse, PoiSearchItem } from "../types";

function formatStatNumber(value: number | null | undefined, fractionDigits = 0): string {
  if (value === null || value === undefined) {
    return "未统计";
  }
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: fractionDigits }).format(value);
}

function formatCoverage(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "未统计";
  }
  return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 }).format(value * 100)}%`;
}

type SearchCardProps = {
  open: boolean;
  summary: string;
  results: PoiSearchItem[];
  onClose: () => void;
  onFocusResult: (item: PoiSearchItem) => void;
};

/** 页头检索结果的浮动卡片：点击「检索」后直接展示，不再进课堂控制台。 */
export function SearchResultsCard({ open, summary, results, onClose, onFocusResult }: SearchCardProps) {
  if (!open) {
    return null;
  }
  return (
    <div className="header-result-card glass-panel" data-testid="search-results-card" role="dialog" aria-label="检索结果">
      <header className="header-result-header">
        <strong>POI 检索结果</strong>
        <button type="button" className="mini-control" onClick={onClose} aria-label="关闭检索结果">
          ×
        </button>
      </header>
      {summary ? <p className="drawer-summary">{summary}</p> : null}
      <div className="drawer-result-list">
        {results.length ? (
          results.map((item) => (
            <button
              key={item.poi_id}
              type="button"
              className="drawer-result-card"
              onClick={() => onFocusResult(item)}
            >
              <strong>{item.name}</strong>
              <span>{item.district || item.city || "未知区域"}</span>
              <small>{item.address || item.type || "无详细地址"}</small>
            </button>
          ))
        ) : (
          <div className="drawer-empty-state">没有匹配的地点。</div>
        )}
      </div>
    </div>
  );
}

type StatsCardProps = {
  open: boolean;
  stats: DatasetStatsResponse | null;
  onClose: () => void;
};

/** 页头区域统计的浮动卡片：点击「统计」后直接展示。 */
export function StatsResultsCard({ open, stats, onClose }: StatsCardProps) {
  if (!open) {
    return null;
  }
  return (
    <div className="header-result-card glass-panel" data-testid="stats-results-card" role="dialog" aria-label="区域统计结果">
      <header className="header-result-header">
        <strong>一张图区域统计</strong>
        <button type="button" className="mini-control" onClick={onClose} aria-label="关闭统计结果">
          ×
        </button>
      </header>
      {stats ? <p className="drawer-summary">{stats.summary}</p> : null}
      {stats ? (
        <div className="drawer-stat-strip">
          <div>
            <span>命中要素</span>
            <strong>{stats.totals.matched_count}</strong>
          </div>
          <div>
            <span>人口</span>
            <strong>{formatStatNumber(stats.totals.total_population)}</strong>
          </div>
          <div>
            <span>密度</span>
            <strong>{formatStatNumber(stats.totals.density, 2)}</strong>
          </div>
        </div>
      ) : null}
      <div className="drawer-result-list">
        {stats?.layers.length ? (
          stats.layers.map((layer) => (
            <article key={layer.layer_id} className="drawer-result-card">
              <strong>{layer.name}</strong>
              <span>
                命中 {layer.matched_count} / {layer.feature_count} 个要素
              </span>
              <small>
                人口 {formatStatNumber(layer.total_population)} · 面积 {formatStatNumber(layer.total_area, 2)} · 密度{" "}
                {formatStatNumber(layer.density, 2)}
              </small>
              <small>方法 {layer.method === "area_weighted_intersection" ? "面积比例估算" : layer.method}</small>
              {layer.rows.length ? (
                <small>
                  命中：{layer.rows.slice(0, 6).map((row) => `${row.name} ${formatCoverage(row.coverage_ratio)}`).join("、")}
                </small>
              ) : null}
            </article>
          ))
        ) : (
          <div className="drawer-empty-state">本次统计没有命中图层。</div>
        )}
      </div>
    </div>
  );
}
