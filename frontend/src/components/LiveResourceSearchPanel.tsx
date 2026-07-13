import type { ResourceSearchResult } from "../types";

type Props = {
  query: string;
  scope: "all" | "kb" | "web";
  loading: boolean;
  results: ResourceSearchResult[];
  onQueryChange: (value: string) => void;
  onScopeChange: (value: "all" | "kb" | "web") => void;
  onOpenResult: (item: ResourceSearchResult) => void;
  onImportResult: (item: ResourceSearchResult) => void;
};

const SCOPE_OPTIONS: Array<{ value: Props["scope"]; label: string }> = [
  { value: "all", label: "全部" },
  { value: "kb", label: "知识库" },
  { value: "web", label: "联网" }
];

function sourceLabel(item: ResourceSearchResult): string {
  if (item.source === "knowledge_base") {
    return "知识库";
  }
  if (item.source === "authoritative_web" || item.source === "web") {
    return "权威联网";
  }
  return item.source || item.type;
}

export function LiveResourceSearchPanel({
  query,
  scope,
  loading,
  results,
  onQueryChange,
  onScopeChange,
  onOpenResult,
  onImportResult
}: Props) {
  const trimmed = query.trim();
  return (
    <section className="live-resource-panel" data-testid="live-resource-search">
      <div className="live-resource-searchbar">
        <span className="live-resource-search-icon" aria-hidden="true">⌕</span>
        <input
          value={query}
          placeholder="搜索地理概念、区域或权威资料"
          onChange={(event) => onQueryChange(event.target.value)}
          aria-label="资料搜索"
        />
        {trimmed ? (
          <button
            type="button"
            className="live-resource-search-clear"
            onClick={() => onQueryChange("")}
            aria-label="清除搜索"
          >
            ×
          </button>
        ) : null}
      </div>

      <div className="live-resource-toolbar">
        <div className="live-resource-scopes" role="tablist" aria-label="搜索范围">
          {SCOPE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="tab"
              aria-selected={scope === option.value}
              className={scope === option.value ? "active" : ""}
              onClick={() => onScopeChange(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <span className="live-resource-status">
          {loading ? (
            <>
              <span className="live-resource-spinner" aria-hidden="true" />
              搜索中
            </>
          ) : (
            `${results.length} 条结果`
          )}
        </span>
      </div>

      <div className="live-resource-results">
        {results.length ? (
          results.map((item) => (
            <article key={item.id} className="live-resource-card">
              <button type="button" className="live-resource-main" onClick={() => onOpenResult(item)}>
                <span className="live-resource-source">{sourceLabel(item)}</span>
                <strong>{item.title || "未命名资料"}</strong>
                <p>{item.summary || "暂无摘要"}</p>
              </button>
              <div className="live-resource-actions">
                {item.url ? (
                  <a href={item.url} target="_blank" rel="noreferrer">
                    打开
                  </a>
                ) : null}
                <button type="button" onClick={() => onImportResult(item)}>
                  导入本课时
                </button>
              </div>
            </article>
          ))
        ) : (
          <div className="drawer-empty-state">
            {trimmed ? "暂无匹配资料" : "输入关键词后会实时搜索知识库与权威联网入口"}
          </div>
        )}
      </div>
    </section>
  );
}
