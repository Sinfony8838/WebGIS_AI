import { useId, useMemo, useRef, useState } from "react";
import type { ArtifactRecord, DatasetStatsResponse, ImageAttachment, LayerRecord, LayersResponse, PoiSearchItem, ResourceSearchResult } from "../types";
import { buildPublicFileUrl } from "../api";
import { LiveResourceSearchPanel } from "./LiveResourceSearchPanel";

export type DrawerTab = "resource-search" | "images" | "layers" | "search" | "stats";

type Props = {
  open: boolean;
  activeTab: DrawerTab;
  layerState: LayersResponse | null;
  searchResults: PoiSearchItem[];
  searchSummary: string;
  oneMapStats: DatasetStatsResponse | null;
  resourceQuery: string;
  resourceScope: "all" | "kb" | "web";
  resourceLoading: boolean;
  resourceResults: ResourceSearchResult[];
  outputs?: ArtifactRecord[];
  onToggleOpen: () => void;
  onChangeTab: (tab: DrawerTab) => void;
  onToggleLayer: (layerId: string, visible: boolean) => void;
  onSelectLayer: (layerId: string) => void;
  onFocusResult: (item: PoiSearchItem) => void;
  onResourceQueryChange: (value: string) => void;
  onResourceScopeChange: (value: "all" | "kb" | "web") => void;
  onOpenResourceResult: (item: ResourceSearchResult) => void;
  onImportResourceResult: (item: ResourceSearchResult) => void;
  onAttachImage?: (image: ImageAttachment) => void;
  onUploadImage?: (file: File) => void;
  onGenerateImage?: (request: { prompt: string; model: string; aspectRatio: string }) => Promise<void> | void;
  imageGenerationLoading?: boolean;
  imageGenerationConfigured?: boolean;
  imageGenerationModel?: string;
  /** 打开课堂工作流（课中面板；无进行中课堂时打开课前备课面板）。 */
  onOpenLessonWorkflow: () => void;
};

const TABS: Array<{ key: DrawerTab; label: string }> = [
  { key: "resource-search", label: "资料搜索" },
  { key: "images", label: "图片库" },
  { key: "layers", label: "图层" },
  { key: "search", label: "检索" },
  { key: "stats", label: "区域统计" }
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
  oneMapStats,
  resourceQuery,
  resourceScope,
  resourceLoading,
  resourceResults,
  outputs = [],
  onToggleOpen,
  onChangeTab,
  onToggleLayer,
  onSelectLayer,
  onFocusResult,
  onResourceQueryChange,
  onResourceScopeChange,
  onOpenResourceResult,
  onImportResourceResult,
  onAttachImage = () => undefined,
  onUploadImage = () => undefined,
  onGenerateImage = () => undefined,
  imageGenerationLoading = false,
  imageGenerationConfigured = false,
  imageGenerationModel = "image-01",
  onOpenLessonWorkflow
}: Props) {
  const generationPromptId = useId();
  const [generationPrompt, setGenerationPrompt] = useState("");
  const [generationModel, setGenerationModel] = useState(imageGenerationModel || "image-01");
  const [generationRatio, setGenerationRatio] = useState("16:9");
  const [generationSubmitting, setGenerationSubmitting] = useState(false);
  const generationSubmittingRef = useRef(false);
  const generationBusy = imageGenerationLoading || generationSubmitting;
  const visibleLayers = useMemo(() => (layerState?.items || []).filter((item) => item.visible), [layerState?.items]);
  const hiddenLayers = useMemo(() => (layerState?.items || []).filter((item) => !item.visible), [layerState?.items]);
  const totalLayers = visibleLayers.length + hiddenLayers.length;
  const imageItems = useMemo(
    () => outputs.filter((item) => ["map_snapshot", "uploaded_image", "generated_image"].includes(item.artifact_type)),
    [outputs]
  );

  const tabCount: Record<DrawerTab, number> = {
    "resource-search": resourceResults.length,
    images: imageItems.length,
    layers: totalLayers,
    search: searchResults.length,
    stats: oneMapStats?.layers.length || 0
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

          {activeTab === "images" ? (
            <section className="drawer-section image-library" data-testid="drawer-images">
              <div className="drawer-section-header">
                <span>项目图片</span>
                <label className="image-library-upload">
                  上传图片
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp,image/gif"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) {
                        onUploadImage(file);
                      }
                      event.currentTarget.value = "";
                    }}
                  />
                </label>
              </div>
              <form
                className="image-generation-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  const prompt = generationPrompt.trim();
                  if (!prompt || generationSubmittingRef.current || imageGenerationLoading || !imageGenerationConfigured) return;
                  if (!window.confirm("图片生成会调用 MiniMax 按量计费 API。确认生成并产生本次费用吗？")) return;
                  generationSubmittingRef.current = true;
                  setGenerationSubmitting(true);
                  let submission: Promise<void> | void;
                  try {
                    submission = onGenerateImage({ prompt, model: generationModel, aspectRatio: generationRatio });
                  } catch {
                    generationSubmittingRef.current = false;
                    setGenerationSubmitting(false);
                    return;
                  }
                  void Promise.resolve(submission)
                    .then(() => setGenerationPrompt(""))
                    .catch(() => undefined)
                    .finally(() => {
                      generationSubmittingRef.current = false;
                      setGenerationSubmitting(false);
                    });
                }}
              >
                <label htmlFor={generationPromptId}>MiniMax AI 生成</label>
                <textarea
                  id={generationPromptId}
                  value={generationPrompt}
                  maxLength={1500}
                  rows={3}
                  placeholder="例如：高中地理水循环过程示意图，蓝绿色教学插画，结构清晰"
                  onChange={(event) => setGenerationPrompt(event.target.value)}
                />
                <div>
                  <select
                    aria-label="图片模型"
                    value={generationModel}
                    onChange={(event) => {
                      const nextModel = event.target.value;
                      setGenerationModel(nextModel);
                      if (nextModel === "image-01-live" && generationRatio === "21:9") {
                        setGenerationRatio("16:9");
                      }
                    }}
                  >
                    <option value="image-01">image-01</option>
                    <option value="image-01-live">image-01-live</option>
                  </select>
                  <select
                    aria-label="图片比例"
                    value={generationRatio}
                    onChange={(event) => setGenerationRatio(event.target.value)}
                  >
                    {["16:9", "4:3", "1:1", "3:2", "2:3", "3:4", "9:16", "21:9"]
                      .filter((ratio) => generationModel === "image-01" || ratio !== "21:9")
                      .map((ratio) => (
                        <option key={ratio} value={ratio}>{ratio}</option>
                      ))}
                  </select>
                  <button type="submit" disabled={!generationPrompt.trim() || generationBusy || !imageGenerationConfigured}>
                    {generationBusy ? "生成中…" : "生成并保存"}
                  </button>
                </div>
                <small>
                  {imageGenerationConfigured
                    ? "生成结果会标记为 AI 生成示意图，并保存到当前项目图片库。"
                    : "图片生成尚未配置，请先配置普通余额 MiniMax API Key。"}
                </small>
              </form>
              {imageItems.length ? (
                <div className="image-library-grid">
                  {imageItems.map((artifact) => {
                    const publicUrl = buildPublicFileUrl(String(artifact.metadata?.public_url || ""));
                    const attachment: ImageAttachment = {
                      artifact_id: artifact.artifact_id,
                      title: artifact.title,
                      public_url: publicUrl,
                      mime_type: String(artifact.metadata?.mime_type || "image/png")
                    };
                    return (
                      <article
                        key={artifact.artifact_id}
                        className="image-library-card"
                        draggable
                        onDragStart={(event) => {
                          event.dataTransfer.effectAllowed = "copy";
                          event.dataTransfer.setData("application/x-webgis-image", JSON.stringify(attachment));
                        }}
                      >
                        <img src={publicUrl} alt={artifact.title} draggable={false} />
                        <div>
                          <strong>{artifact.title}</strong>
                          <small>
                            {artifact.artifact_type === "map_snapshot"
                              ? "地图截图"
                              : artifact.artifact_type === "generated_image"
                                ? "AI生成示意图"
                                : "本地上传"}
                            {artifact.created_at ? ` · ${new Date(artifact.created_at).toLocaleString("zh-CN")}` : ""}
                          </small>
                        </div>
                        <button type="button" onClick={() => onAttachImage(attachment)}>
                          加入助教
                        </button>
                      </article>
                    );
                  })}
                </div>
              ) : (
                <div className="drawer-empty-state">还没有图片，可先截图或上传一张地理图片。</div>
              )}
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

          {activeTab === "stats" ? (
            <section className="drawer-section" data-testid="drawer-stats">
              <div className="drawer-section-header">
                <span>一张图区域统计</span>
                <small>{oneMapStats?.layers.length || 0}</small>
              </div>
              {oneMapStats ? <p className="drawer-summary">{oneMapStats.summary}</p> : null}
              {oneMapStats ? (
                <div className="drawer-stat-strip">
                  <div>
                    <span>命中要素</span>
                    <strong>{oneMapStats.totals.matched_count}</strong>
                  </div>
                  <div>
                    <span>人口</span>
                    <strong>{formatStatNumber(oneMapStats.totals.total_population)}</strong>
                  </div>
                  <div>
                    <span>密度</span>
                    <strong>{formatStatNumber(oneMapStats.totals.density, 2)}</strong>
                  </div>
                </div>
              ) : null}
              <div className="drawer-result-list">
                {oneMapStats?.layers.length ? (
                  oneMapStats.layers.map((layer) => (
                    <article key={layer.layer_id} className="drawer-result-card">
                      <strong>{layer.name}</strong>
                      <span>
                        命中 {layer.matched_count} / {layer.feature_count} 个要素
                      </span>
                      <small>
                        人口 {formatStatNumber(layer.total_population)} · 面积 {formatStatNumber(layer.total_area, 2)} ·
                        密度 {formatStatNumber(layer.density, 2)}
                      </small>
                      <small>
                        方法 {layer.method === "area_weighted_intersection" ? "面积比例估算" : layer.method}
                      </small>
                      {layer.rows.length ? (
                        <small>
                          命中：{layer.rows.slice(0, 6).map((row) => `${row.name} ${formatCoverage(row.coverage_ratio)}`).join("、")}
                        </small>
                      ) : null}
                    </article>
                  ))
                ) : (
                  <div className="drawer-empty-state">
                    先从数据库加载一张图数据或可关联 CSV 数据，再用右侧“绘区”工具框选区域并点击“统计框选区”。
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
            onClick={onOpenLessonWorkflow}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="8" cy="3" r="2.5" fill="currentColor" opacity="0.6" />
              <line x1="8" y1="5.5" x2="8" y2="10.5" stroke="currentColor" strokeWidth="1.5" opacity="0.4" />
              <circle cx="8" cy="13" r="2.5" fill="currentColor" opacity="0.6" />
            </svg>
            上课模式
          </button>
        </div>
      </aside>
    </div>
  );
}
