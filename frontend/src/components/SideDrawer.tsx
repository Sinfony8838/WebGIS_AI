import { useMemo } from "react";
import type { LayerRecord, LayersResponse, PoiSearchItem, ResourceSearchResult } from "../types";
import { LiveResourceSearchPanel } from "./LiveResourceSearchPanel";

export type DrawerTab = "resource-search" | "layers" | "search";

type Props = {
  open: boolean;
  activeTab: DrawerTab;
  layerState: LayersResponse | null;
  searchResults: PoiSearchItem[];
  searchSummary: string;
  resourceQuery: string;
  resourceScope: "all" | "kb" | "web";
  resourceLoading: boolean;
  resourceResults: ResourceSearchResult[];
  onToggleOpen: () => void;
  onChangeTab: (tab: DrawerTab) => void;
  onToggleLayer: (layerId: string, visible: boolean) => void;
  onSelectLayer: (layerId: string) => void;
  onFocusResult: (item: PoiSearchItem) => void;
  onResourceQueryChange: (value: string) => void;
  onResourceScopeChange: (value: "all" | "kb" | "web") => void;
  onOpenResourceResult: (item: ResourceSearchResult) => void;
  onImportResourceResult: (item: ResourceSearchResult) => void;
  onOpenTimeline: () => void;
};

const TABS: Array<{ key: DrawerTab; label: string }> = [
  { key: "resource-search", label: "资料搜索" },
  { key: "layers", label: "图层" },
  { key: "search", label: "检索" }
];

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
  layerState,
  searchResults,
  searchSummary,
  resourceQuery,
  resourceScope,
  resourceLoading,
  resourceResults,
  onToggleOpen,
  onChangeTab,
  onToggleLayer,
  onSelectLayer,
  onFocusResult,
  onResourceQueryChange,
  onResourceScopeChange,
  onOpenResourceResult,
  onImportResourceResult,
  onOpenTimeline
}: Props) {
  const visibleLayers = useMemo(() => (layerState?.items || []).filter((item) => item.visible), [layerState?.items]);
  const hiddenLayers = useMemo(() => (layerState?.items || []).filter((item) => !item.visible), [layerState?.items]);
  const totalLayers = visibleLayers.length + hiddenLayers.length;

  const tabCount: Record<DrawerTab, number> = {
    "resource-search": resourceResults.length,
    layers: totalLayers,
    search: searchResults.length
  };

  return (
    <div className={`side-drawer ${open ? "open" : "closed"}`}>
      <button
        type="button"
        className="drawer-toggle"
        onClick={onToggleOpen}
        aria-label={open ? "收起课堂控制台" : "展开课堂控制台"}
      >
        <span aria-hidden="true">{open ? "‹" : "›"}</span>
      </button>

      <aside className="drawer-panel glass-panel" aria-label="课堂控制台">
        <header className="drawer-header">
          <div className="drawer-header-text">
            <p className="panel-tag">Class Console</p>
            <strong>课堂控制台</strong>
          </div>
          <span className="drawer-header-pulse" aria-hidden="true" />
        </header>

        <nav className="drawer-tabs" role="tablist" aria-label="课堂控制台分区">
          {TABS.map((tab) => {
            const isActive = tab.key === activeTab;
            const count = tabCount[tab.key];
            return (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={isActive}
                className={isActive ? "active" : ""}
                onClick={() => onChangeTab(tab.key)}
              >
                <span>{tab.label}</span>
                {count > 0 ? <em>{count > 99 ? "99+" : count}</em> : null}
              </button>
            );
          })}
        </nav>

        <div className="drawer-body">
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
              <div className="drawer-stat-strip">
                <div>
                  <span>可见</span>
                  <strong>{visibleLayers.length}</strong>
                </div>
                <div>
                  <span>隐藏</span>
                  <strong>{hiddenLayers.length}</strong>
                </div>
                <div>
                  <span>总计</span>
                  <strong>{totalLayers}</strong>
                </div>
              </div>

              <div className="drawer-section-header">
                <span>可见图层</span>
                <small>{visibleLayers.length}</small>
              </div>
              <div className="drawer-layer-list">
                {visibleLayers.length ? (
                  visibleLayers
                    .slice()
                    .sort((left, right) => right.z_index - left.z_index)
                    .map((layer) =>
                      renderLayerRow(layer, layerState?.active_layer_id === layer.layer_id, onToggleLayer, onSelectLayer)
                    )
                ) : (
                  <div className="drawer-empty-state">当前没有可见业务图层</div>
                )}
              </div>

              <div className="drawer-section-header compact">
                <span>隐藏图层</span>
                <small>{hiddenLayers.length}</small>
              </div>
              <div className="drawer-layer-list">
                {hiddenLayers.length ? (
                  hiddenLayers
                    .slice()
                    .sort((left, right) => right.z_index - left.z_index)
                    .map((layer) =>
                      renderLayerRow(layer, layerState?.active_layer_id === layer.layer_id, onToggleLayer, onSelectLayer)
                    )
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
                <small>{searchResults.length}</small>
              </div>
              {searchSummary ? <p className="drawer-summary">{searchSummary}</p> : null}
              <div className="drawer-result-list">
                {searchResults.length ? (
                  searchResults.map((item) => (
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
                  <div className="drawer-empty-state">
                    在顶部搜索栏输入关键词后，可按当前视域或手绘区域发起检索。
                  </div>
                )}
              </div>
            </section>
          ) : null}
        </div>

        <div className="drawer-footer">
          <button
            type="button"
            className="drawer-timeline-launch-btn"
            onClick={onOpenTimeline}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="8" cy="3" r="2.5" fill="currentColor" opacity="0.6" />
              <line x1="8" y1="5.5" x2="8" y2="10.5" stroke="currentColor" strokeWidth="1.5" opacity="0.4" />
              <circle cx="8" cy="13" r="2.5" fill="currentColor" opacity="0.6" />
            </svg>
            教学流程
          </button>
        </div>
      </aside>
    </div>
  );
}
