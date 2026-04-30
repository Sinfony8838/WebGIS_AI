import type { ResourceSearchResult } from "../types";

type Props = {
  query: string;
  scope: "all" | "kb" | "web" | "materials";
  loading: boolean;
  results: ResourceSearchResult[];
  onQueryChange: (value: string) => void;
  onScopeChange: (value: "all" | "kb" | "web" | "materials") => void;
  onOpenResult: (item: ResourceSearchResult) => void;
  onImportResult: (item: ResourceSearchResult) => void;
};

const SCOPE_OPTIONS: Array<{ value: Props["scope"]; label: string }> = [
  { value: "all", label: "全部" },
  { value: "kb", label: "知识库" },
  { value: "materials", label: "素材" },
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
  return (
    <section className="live-resource-panel" data-testid="live-resource-search">
      <div className="drawer-section-header">
        <span>实时资料搜索</span>
        <small>{loading ? "搜索中" : `${results.length} 条`}</small>
      </div>
      <div className="live-resource-searchbar">
        <input
          value={query}
          placeholder="搜索地理概念、区域、课件素材或权威资料"
          onChange={(event) => onQueryChange(event.target.value)}
        />
      </div>
      <div className="live-resource-scopes">
        {SCOPE_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            className={scope === option.value ? "active" : ""}
            onClick={() => onScopeChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
      <div className="live-resource-results">
        {results.length ? (
          results.map((item) => (
            <article key={item.id} className="live-resource-card">
              <button type="button" className="live-resource-main" onClick={() => onOpenResult(item)}>
                <span>{sourceLabel(item)}</span>
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
          <div className="drawer-empty-state">{query ? "暂无匹配资料" : "输入关键词后会实时搜索知识库、素材和权威联网入口"}</div>
        )}
      </div>
    </section>
  );
}
