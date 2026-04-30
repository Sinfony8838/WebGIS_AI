import { useMemo } from "react";
import { getApiBase } from "../api";
import type { ArtifactRecord, KnowledgeTopicSummary, LayerRecord, LayersResponse, PoiSearchItem, ResourceSearchResult } from "../types";
import { LiveResourceSearchPanel } from "./LiveResourceSearchPanel";

export type DrawerTab = "resources" | "resource-search" | "layers" | "search" | "outputs";

type StatusSummary = {
  currentMode: string;
  searchScope: string;
  latest: string;
  activeBasemap: string;
  visibleLayers: number;
  totalLayers: number;
  enabledTemplates: number;
};

type Props = {
  open: boolean;
  activeTab: DrawerTab;
  topics: KnowledgeTopicSummary[];
  layerState: LayersResponse | null;
  outputs: ArtifactRecord[];
  searchResults: PoiSearchItem[];
  searchSummary: string;
  resourceQuery: string;
  resourceScope: "all" | "kb" | "web" | "materials";
  resourceLoading: boolean;
  resourceResults: ResourceSearchResult[];
  statusSummary: StatusSummary;
  onToggleOpen: () => void;
  onChangeTab: (tab: DrawerTab) => void;
  onToggleLayer: (layerId: string, visible: boolean) => void;
  onSelectLayer: (layerId: string) => void;
  onFocusResult: (item: PoiSearchItem) => void;
  onOpenKnowledgeTopic: (topic: string) => void;
  onResourceQueryChange: (value: string) => void;
  onResourceScopeChange: (value: "all" | "kb" | "web" | "materials") => void;
  onOpenResourceResult: (item: ResourceSearchResult) => void;
  onImportResourceResult: (item: ResourceSearchResult) => void;
};

function statusLabel(status?: string): string {
  if (status === "renderable_layer") {
    return "可显示";
  }
  if (status === "stored_only") {
    return "仅存档";
  }
  return "知识";
}

function renderLayerRow(
  layer: LayerRecord,
  isActive: boolean,
  onToggleLayer: Props["onToggleLayer"],
  onSelectLayer: Props["onSelectLayer"]
) {
  const status = String(layer.metadata?.kb_status || layer.metadata?.status || "");
  return (
    <label key={layer.layer_id} className={`drawer-layer-row ${isActive ? "active" : ""}`}>
      <input type="checkbox" checked={layer.visible} onChange={() => onToggleLayer(layer.layer_id, !layer.visible)} />
      <button type="button" className="drawer-layer-button" onClick={() => onSelectLayer(layer.layer_id)}>
        <span>{layer.name}</span>
        <small>
          {layer.geometry_type} · {layer.source} · {statusLabel(status)}
        </small>
      </button>
    </label>
  );
}

export function SideDrawer({
  open,
  activeTab,
  topics,
  layerState,
  outputs,
  searchResults,
  searchSummary,
  resourceQuery,
  resourceScope,
  resourceLoading,
  resourceResults,
  statusSummary,
  onToggleOpen,
  onChangeTab,
  onToggleLayer,
  onSelectLayer,
  onFocusResult,
  onOpenKnowledgeTopic,
  onResourceQueryChange,
  onResourceScopeChange,
  onOpenResourceResult,
  onImportResourceResult
}: Props) {
  const apiBase = getApiBase();
  const visibleLayers = useMemo(() => (layerState?.items || []).filter((item) => item.visible), [layerState?.items]);
  const hiddenLayers = useMemo(() => (layerState?.items || []).filter((item) => !item.visible), [layerState?.items]);

  return (
    <div className={`side-drawer ${open ? "open" : "closed"}`}>
      <button type="button" className="drawer-toggle" onClick={onToggleOpen} aria-label={open ? "收起课堂控制台" : "展开课堂控制台"}>
        {open ? "<" : ">"}
      </button>

      <aside className="drawer-panel glass-panel" aria-label="课堂控制台">
        <div className="drawer-header">
          <p className="panel-tag">Class Console</p>
          <strong>课堂控制台</strong>
          <span className="drawer-subtitle">资料专题、图层控制、检索记录与课堂产物</span>
        </div>

        <section className="drawer-status-card">
          <div className="drawer-status-topline">
            <span>当前状态</span>
            <strong>{statusSummary.currentMode}</strong>
          </div>
          <div className="drawer-status-grid">
            <div>
              <span>检索范围</span>
              <strong>{statusSummary.searchScope}</strong>
            </div>
            <div>
              <span>底图</span>
              <strong>{statusSummary.activeBasemap}</strong>
            </div>
            <div>
              <span>可见图层</span>
              <strong>
                {statusSummary.visibleLayers} / {statusSummary.totalLayers}
              </strong>
            </div>
            <div>
              <span>资料专题</span>
              <strong>{topics.length}</strong>
            </div>
          </div>
          <p>{statusSummary.latest}</p>
        </section>

        <div className="drawer-tabs">
          <button type="button" className={activeTab === "resources" ? "active" : ""} onClick={() => onChangeTab("resources")}>
            资料
          </button>
          <button type="button" className={activeTab === "resource-search" ? "active" : ""} onClick={() => onChangeTab("resource-search")}>
            资料搜索
          </button>
          <button type="button" className={activeTab === "layers" ? "active" : ""} onClick={() => onChangeTab("layers")}>
            图层
          </button>
          <button type="button" className={activeTab === "search" ? "active" : ""} onClick={() => onChangeTab("search")}>
            检索
          </button>
          <button type="button" className={activeTab === "outputs" ? "active" : ""} onClick={() => onChangeTab("outputs")}>
            产物
          </button>
        </div>

        <div className="drawer-body">
          {activeTab === "resources" ? (
            <section className="drawer-section" data-testid="drawer-resources">
              <div className="drawer-section-header">
                <span>资料专题</span>
                <small>{topics.length} 类</small>
              </div>
              <p className="drawer-summary">这里来自知识库，不再是硬编码教材目录。专题条目可以用于检索、读图讲解和后续教案设计。</p>
              <div className="resource-topic-list">
                {topics.length ? (
                  topics.map((topic) => (
                    <button key={topic.topic} type="button" className="resource-topic-card" onClick={() => onOpenKnowledgeTopic(topic.topic)}>
                      <div>
                        <strong>{topic.title}</strong>
                        <span>{topic.topic}</span>
                      </div>
                      <p>
                        共 {topic.item_count} 条，{topic.renderable_count} 条可显示，{topic.stored_only_count} 条仅存档。
                      </p>
                      {topic.sample_titles.length ? <small>{topic.sample_titles.join(" / ")}</small> : null}
                    </button>
                  ))
                ) : (
                  <div className="drawer-empty-state">暂无资料专题</div>
                )}
              </div>
            </section>
          ) : null}

          {activeTab === "resource-search" ? (
            <section className="drawer-section" data-testid="drawer-resource-search">
              <LiveResourceSearchPanel
                query={resourceQuery}
                scope={resourceScope}
                loading={resourceLoading}
                results={resourceResults}
                onQueryChange={onResourceQueryChange}
                onScopeChange={onResourceScopeChange}
                onOpenResult={onOpenResourceResult}
                onImportResult={onImportResourceResult}
              />
            </section>
          ) : null}

          {activeTab === "layers" ? (
            <section className="drawer-section" data-testid="drawer-layers">
              <div className="drawer-section-header">
                <span>可见图层</span>
                <small>{visibleLayers.length} 个</small>
              </div>
              <div className="drawer-layer-list">
                {visibleLayers.length ? (
                  visibleLayers
                    .slice()
                    .sort((left, right) => right.z_index - left.z_index)
                    .map((layer) => renderLayerRow(layer, layerState?.active_layer_id === layer.layer_id, onToggleLayer, onSelectLayer))
                ) : (
                  <div className="drawer-empty-state">当前没有可见业务图层</div>
                )}
              </div>
              <div className="drawer-section-header compact">
                <span>隐藏/可启用图层</span>
                <small>{hiddenLayers.length} 个</small>
              </div>
              <div className="drawer-layer-list">
                {hiddenLayers.length ? (
                  hiddenLayers
                    .slice()
                    .sort((left, right) => right.z_index - left.z_index)
                    .map((layer) => renderLayerRow(layer, layerState?.active_layer_id === layer.layer_id, onToggleLayer, onSelectLayer))
                ) : (
                  <div className="drawer-empty-state">暂无隐藏图层</div>
                )}
              </div>
            </section>
          ) : null}

          {activeTab === "search" ? (
            <section className="drawer-section" data-testid="drawer-search">
              <div className="drawer-section-header">
                <span>POI 检索结果</span>
                <small>{searchResults.length} 条</small>
              </div>
              <p className="drawer-summary">{searchSummary || "在顶部搜索栏输入关键词后，可按当前视域或手绘区域发起检索。"}</p>
              <div className="drawer-result-list">
                {searchResults.length ? (
                  searchResults.map((item) => (
                    <button key={item.poi_id} type="button" className="drawer-result-card" onClick={() => onFocusResult(item)}>
                      <strong>{item.name}</strong>
                      <span>{item.district || item.city || "未知区域"}</span>
                      <small>{item.address || item.type || "无详细地址"}</small>
                    </button>
                  ))
                ) : (
                  <div className="drawer-empty-state">暂无检索结果</div>
                )}
              </div>
            </section>
          ) : null}

          {activeTab === "outputs" ? (
            <section className="drawer-section" data-testid="drawer-outputs">
              <div className="drawer-section-header">
                <span>课堂产物</span>
                <small>{outputs.length} 项</small>
              </div>
              <p className="drawer-summary">只显示教师可直接使用的截图、讲解稿和查询摘要，系统内部模板 JSON 不再展示。</p>
              <div className="drawer-output-list">
                {outputs.length ? (
                  outputs.map((artifact) => {
                    const publicUrl = String(artifact.metadata?.public_url || "");
                    return (
                      <a key={artifact.artifact_id} className="drawer-output-card" href={publicUrl ? `${apiBase}${publicUrl}` : undefined} target="_blank" rel="noreferrer">
                        <strong>{artifact.title}</strong>
                        <span>{artifact.artifact_type}</span>
                      </a>
                    );
                  })
                ) : (
                  <div className="drawer-empty-state">暂无课堂产物</div>
                )}
              </div>
            </section>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
