import { useEffect, useMemo, useState } from "react";
import type { KnowledgeBaseItem, KnowledgeTopicSummary, RegionBinding, TeachingMaterial } from "../types";
import { TeachingMaterialEditor } from "./TeachingMaterialEditor";

export type KnowledgeQuery = {
  query: string;
  topic: string;
  region: string;
  tag: string;
};

type Props = {
  mode?: "dock" | "page";
  collapsed: boolean;
  loading: boolean;
  total: number;
  items: KnowledgeBaseItem[];
  topics: KnowledgeTopicSummary[];
  query: KnowledgeQuery;
  editingItem: KnowledgeBaseItem | null;
  activeLayerId: string;
  availableLayerIds: string[];
  canRegister: boolean;
  onToggleCollapse: () => void;
  onQueryChange: (patch: Partial<KnowledgeQuery>) => void;
  onSearch: (patch?: Partial<KnowledgeQuery>) => void;
  onSelectItem: (item: KnowledgeBaseItem) => void;
  onEditingItemChange: (item: KnowledgeBaseItem) => void;
  onSaveItem: () => void;
  onRegisterActiveLayer: () => void;
  onFocusLayer: (layerId: string) => void;
  onUploadMaterial: (item: KnowledgeBaseItem, file: File, metadata: { title: string; description: string; material_type: string; region_binding: RegionBinding }) => void;
  onAddMaterialLink: (item: KnowledgeBaseItem, payload: { url: string; title: string; description: string; material_type: string; region_binding: RegionBinding }) => void;
  onImportToLesson: (item: KnowledgeBaseItem, material?: TeachingMaterial) => void;
};

const EMPTY_ITEM: KnowledgeBaseItem = {
  id: "",
  title: "",
  topic: "",
  region: "",
  time: "",
  status: "knowledge_only",
  source: "",
  license: "",
  grade_level: "",
  keywords: [],
  tags: [],
  crs: "",
  summary: "",
  canonical_answer: "",
  teaching_points: [],
  citations: [],
  dataset_refs: [],
  materials: [],
  related_templates: [],
  updated_at: ""
};

const PRESET_FILTERS: Array<{ label: string; patch: Partial<KnowledgeQuery> }> = [
  { label: "人口普查", patch: { topic: "population_census" } },
  { label: "气候分区", patch: { topic: "climate_zoning" } },
  { label: "课堂图层", patch: { tag: "课堂图层" } },
  { label: "读图讲解", patch: { tag: "读图" } }
];

function parseCommaList(value: string): string[] {
  return value
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseLineList(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatDate(value: string): string {
  if (!value) {
    return "未更新";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString("zh-CN");
}

function statusLabel(status?: string): string {
  if (status === "renderable_layer") {
    return "可视图层";
  }
  if (status === "stored_only") {
    return "仅存档";
  }
  return "知识条目";
}

function summaryPreview(value: string): string {
  const text = String(value || "").trim();
  if (!text) {
    return "暂无摘要。";
  }
  return text.split(/\r?\n/).slice(0, 2).join(" ");
}

export function KnowledgePanel({
  mode = "dock",
  collapsed,
  loading,
  total,
  items,
  topics,
  query,
  editingItem,
  activeLayerId,
  availableLayerIds,
  canRegister,
  onToggleCollapse,
  onQueryChange,
  onSearch,
  onSelectItem,
  onEditingItemChange,
  onSaveItem,
  onRegisterActiveLayer,
  onFocusLayer,
  onUploadMaterial,
  onAddMaterialLink,
  onImportToLesson
}: Props) {
  const [editOpen, setEditOpen] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  const currentItem = editingItem || EMPTY_ITEM;
  const availableLayerIdSet = useMemo(() => new Set(availableLayerIds), [availableLayerIds]);
  const totalLabel = loading ? "加载中" : `${total} 条`;

  useEffect(() => {
    if (collapsed) {
      setZoomed(false);
    }
  }, [collapsed]);

  const handleSelectItem = (item: KnowledgeBaseItem) => {
    onSelectItem(item);
    setEditOpen(false);
  };

  return (
    <section
      className={`tool-group glass-panel knowledge-panel ${mode === "page" ? "page-mode" : "dock-mode"} ${collapsed ? "collapsed" : "expanded"} ${
        !collapsed && zoomed ? "zoomed" : ""
      }`}
      data-testid="knowledge-panel"
    >
      <div className={`knowledge-panel-header ${collapsed ? "compact" : ""}`}>
        <div className={`knowledge-panel-title ${collapsed ? "compact" : ""}`}>
          <span className="knowledge-panel-eyebrow">知识库</span>
          {collapsed ? null : (
            <>
              <strong>课堂知识检索</strong>
              <small>检索、筛选并管理课堂知识条目</small>
            </>
          )}
        </div>
        <div className="knowledge-header-actions">
          <span className="knowledge-total">{totalLabel}</span>
          {collapsed || mode === "page" ? null : (
            <button
              type="button"
              className="mini-control knowledge-zoom"
              onClick={() => setZoomed((value) => !value)}
              aria-label={zoomed ? "还原知识库面板" : "放大知识库面板"}
            >
              {zoomed ? "还原" : "放大"}
            </button>
          )}
          {mode === "page" ? null : (
            <button
              type="button"
              className="mini-control knowledge-toggle"
              onClick={onToggleCollapse}
              aria-label="折叠或展开知识库"
            >
              {collapsed ? "+" : "-"}
            </button>
          )}
        </div>
      </div>

      {collapsed ? null : (
        <div className="knowledge-panel-body">
          <section className="kb-card kb-search">
            <div className="kb-section-header">
              <div className="kb-section-header-search">
                <strong>知识检索</strong>
                <span>按关键词、主题、区域和标签筛选</span>
              </div>
            </div>

            <div className="kb-topic-chips">
              {PRESET_FILTERS.map((preset) => (
                <button
                  key={preset.label}
                  type="button"
                  onClick={() => {
                    onQueryChange(preset.patch);
                    onSearch(preset.patch);
                  }}
                >
                  {preset.label}
                </button>
              ))}
            </div>

            <div className="kb-search-row">
              <input
                value={query.query}
                placeholder="输入人口、气候、交通等关键词"
                onChange={(event) => onQueryChange({ query: event.target.value })}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    onSearch();
                  }
                }}
              />
              <button
                type="button"
                className="tool-button"
                onClick={() => onSearch()}
                disabled={loading}
                data-testid="kb-search-button"
              >
                检索
              </button>
            </div>

            <div className="kb-search-filters">
              <label className="kb-filter-field">
                <span>主题</span>
                <input
                  value={query.topic}
                  placeholder="如：population_census"
                  onChange={(event) => onQueryChange({ topic: event.target.value })}
                />
              </label>
              <label className="kb-filter-field">
                <span>区域</span>
                <input
                  value={query.region}
                  placeholder="如：china / global"
                  onChange={(event) => onQueryChange({ region: event.target.value })}
                />
              </label>
              <label className="kb-filter-field">
                <span>标签</span>
                <input
                  value={query.tag}
                  placeholder="如：课堂图层"
                  onChange={(event) => onQueryChange({ tag: event.target.value })}
                />
              </label>
            </div>

            {topics.length ? (
              <div className="kb-topic-summary">
                {topics.map((topic) => (
                  <span key={topic.topic}>
                    {topic.title} {topic.item_count}
                  </span>
                ))}
              </div>
            ) : null}
          </section>

          <section className="kb-card kb-results" data-testid="kb-results">
            <div className="kb-section-header">
              <strong>检索结果</strong>
              <span>{loading ? "加载中..." : `${items.length} 条结果`}</span>
            </div>
            <div className="kb-result-surface">
              <div className="kb-result-state">
                当前结果：
                <strong>{editingItem?.title || "未选中条目"}</strong>
              </div>
              <div className="kb-result-list">
                {items.length ? (
                  items.map((item) => {
                    const firstLayerId = String(item.dataset_refs?.[0]?.layer_id || "");
                    const canFocus = Boolean(firstLayerId && availableLayerIdSet.has(firstLayerId));
                    return (
                      <article
                        key={item.id || `${item.title}_${item.updated_at}`}
                        className={`kb-result-card ${editingItem?.id === item.id ? "active" : ""}`}
                      >
                        <button type="button" className="kb-result-select" onClick={() => handleSelectItem(item)}>
                          <div className="kb-result-main">
                            <strong>{item.title || "未命名条目"}</strong>
                            <small>
                              {item.topic || "未分类"} · {item.region || "未标注区域"} · {formatDate(item.updated_at)}
                            </small>
                            <p>{summaryPreview(item.summary)}</p>
                          </div>
                        </button>
                        <div className="kb-result-footer">
                          <div className="kb-result-meta">
                            <span>{statusLabel(item.status)}</span>
                            {item.keywords.slice(0, 3).map((keyword) => (
                              <span key={`${item.id}_${keyword}`}>{keyword}</span>
                            ))}
                          </div>
                          <button
                            type="button"
                            className="kb-focus-link"
                            disabled={!canFocus}
                            onClick={() => canFocus && onFocusLayer(firstLayerId)}
                          >
                            {firstLayerId ? (canFocus ? "定位关联图层" : "仅知识资料") : "无关联图层"}
                          </button>
                        </div>
                      </article>
                    );
                  })
                ) : (
                  <div className="kb-empty">暂无知识库结果</div>
                )}
              </div>
            </div>
          </section>

          <section className="kb-card kb-editor" data-testid="kb-editor">
            <div className="kb-section-header">
              <strong>条目编辑</strong>
              <div className="kb-detail-actions">
                <button type="button" className="mini-control" onClick={() => onEditingItemChange({ ...EMPTY_ITEM })}>
                  新建
                </button>
                <button type="button" className="mini-control" onClick={() => setEditOpen((value) => !value)}>
                  {editOpen ? "收起编辑" : "展开编辑"}
                </button>
              </div>
            </div>

            <div className="kb-detail-summary">
              <strong>{currentItem.title || "待整理条目"}</strong>
              <span>
                {currentItem.topic || "未分类"} · {statusLabel(currentItem.status)}
              </span>
              <p>{summaryPreview(currentItem.summary)}</p>
            </div>

            {editOpen ? (
              <div className="kb-editor-form">
                <div className="kb-editor-grid">
                  <label>
                    <span>ID</span>
                    <input
                      value={currentItem.id}
                      onChange={(event) => onEditingItemChange({ ...currentItem, id: event.target.value })}
                    />
                  </label>
                  <label>
                    <span>标题</span>
                    <input
                      value={currentItem.title}
                      placeholder="输入条目标题"
                      onChange={(event) => onEditingItemChange({ ...currentItem, title: event.target.value })}
                    />
                  </label>
                  <label>
                    <span>主题</span>
                    <input
                      value={currentItem.topic}
                      onChange={(event) => onEditingItemChange({ ...currentItem, topic: event.target.value })}
                    />
                  </label>
                  <label>
                    <span>区域</span>
                    <input
                      value={currentItem.region}
                      onChange={(event) => onEditingItemChange({ ...currentItem, region: event.target.value })}
                    />
                  </label>
                  <label>
                    <span>时间</span>
                    <input
                      value={currentItem.time}
                      onChange={(event) => onEditingItemChange({ ...currentItem, time: event.target.value })}
                    />
                  </label>
                  <label>
                    <span>关键词</span>
                    <input
                      value={currentItem.keywords.join(", ")}
                      placeholder="逗号分隔"
                      onChange={(event) =>
                        onEditingItemChange({
                          ...currentItem,
                          keywords: parseCommaList(event.target.value)
                        })
                      }
                    />
                  </label>
                </div>

                <label>
                  <span>摘要</span>
                  <textarea
                    rows={3}
                    value={currentItem.summary}
                    onChange={(event) => onEditingItemChange({ ...currentItem, summary: event.target.value })}
                  />
                </label>
                <label>
                  <span>标准讲解</span>
                  <textarea
                    rows={3}
                    value={currentItem.canonical_answer}
                    onChange={(event) =>
                      onEditingItemChange({ ...currentItem, canonical_answer: event.target.value })
                    }
                  />
                </label>
                <label>
                  <span>教学要点</span>
                  <textarea
                    rows={3}
                    value={currentItem.teaching_points.join("\n")}
                    onChange={(event) =>
                      onEditingItemChange({
                        ...currentItem,
                        teaching_points: parseLineList(event.target.value)
                      })
                    }
                  />
                </label>

                <div className="kb-editor-actions">
                  <button type="button" className="tool-button" onClick={onSaveItem} disabled={loading}>
                    保存条目
                  </button>
                  <button
                    type="button"
                    className="tool-button"
                    onClick={onRegisterActiveLayer}
                    disabled={!canRegister || loading}
                    data-testid="kb-register-layer"
                  >
                    关联当前图层
                  </button>
                </div>
                <TeachingMaterialEditor
                  item={currentItem}
                  loading={loading}
                  onUpload={(file, metadata) => onUploadMaterial(currentItem, file, metadata)}
                  onAddLink={(payload) => onAddMaterialLink(currentItem, payload)}
                  onImportToLesson={onImportToLesson}
                />
              </div>
            ) : (
              <>
                <button
                  type="button"
                  className="tool-button kb-register-compact"
                  onClick={onRegisterActiveLayer}
                  disabled={!canRegister || loading}
                  data-testid="kb-register-layer"
                >
                  关联当前图层：{activeLayerId || "未选择"}
                </button>
                <p className="kb-layer-hint">点击后会把当前课堂图层写入所选知识条目。</p>
              </>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
