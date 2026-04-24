import { useEffect, useMemo, useState } from "react";
import { getApiBase } from "../api";
import type { ArtifactRecord, LayerRecord, LayersResponse, PoiSearchItem, TemplateItem } from "../types";

export type DrawerTab = "units" | "layers" | "search" | "outputs";

type StatusSummary = {
  currentMode: string;
  searchScope: string;
  latest: string;
  activeBasemap: string;
  visibleLayers: number;
  totalLayers: number;
  enabledTemplates: number;
};

type TemplateUnitGroup = {
  unitId: string;
  unitTitle: string;
  unitOrder: number;
  templates: TemplateItem[];
};

type TemplateChapterGroup = {
  chapterId: string;
  chapterTitle: string;
  chapterOrder: number;
  units: TemplateUnitGroup[];
};

type Props = {
  open: boolean;
  activeTab: DrawerTab;
  templates: TemplateItem[];
  layerState: LayersResponse | null;
  outputs: ArtifactRecord[];
  searchResults: PoiSearchItem[];
  searchSummary: string;
  statusSummary: StatusSummary;
  onToggleOpen: () => void;
  onChangeTab: (tab: DrawerTab) => void;
  onToggleLayer: (layerId: string, visible: boolean) => void;
  onSelectLayer: (layerId: string) => void;
  onFocusResult: (item: PoiSearchItem) => void;
  onRunTemplate: (templateId: string) => void;
};

export function groupTemplatesByChapter(templates: TemplateItem[]): TemplateChapterGroup[] {
  const chapterMap = new Map<string, TemplateChapterGroup>();

  templates.forEach((template) => {
    const chapterId = template.chapter_id || "default_chapter";
    const unitId = template.unit_id || "default_unit";
    const chapterTitle = template.chapter_title || "课堂模板";
    const unitTitle = template.unit_title || "默认单元";

    if (!chapterMap.has(chapterId)) {
      chapterMap.set(chapterId, {
        chapterId,
        chapterTitle,
        chapterOrder: template.chapter_order ?? 999,
        units: []
      });
    }

    const chapter = chapterMap.get(chapterId)!;
    let unit = chapter.units.find((item) => item.unitId === unitId);
    if (!unit) {
      unit = {
        unitId,
        unitTitle,
        unitOrder: template.unit_order ?? 999,
        templates: []
      };
      chapter.units.push(unit);
    }

    unit.templates.push(template);
  });

  return Array.from(chapterMap.values())
    .sort((left, right) => left.chapterOrder - right.chapterOrder || left.chapterTitle.localeCompare(right.chapterTitle))
    .map((chapter) => ({
      ...chapter,
      units: chapter.units
        .map((unit) => ({
          ...unit,
          templates: unit.templates
            .slice()
            .sort(
              (left, right) =>
                (left.template_order ?? 999) - (right.template_order ?? 999) || left.title.localeCompare(right.title)
            )
        }))
        .sort((left, right) => left.unitOrder - right.unitOrder || left.unitTitle.localeCompare(right.unitTitle))
    }));
}

function renderLayerRow(
  layer: LayerRecord,
  isActive: boolean,
  onToggleLayer: Props["onToggleLayer"],
  onSelectLayer: Props["onSelectLayer"]
) {
  return (
    <label key={layer.layer_id} className={`drawer-layer-row ${isActive ? "active" : ""}`}>
      <input type="checkbox" checked={layer.visible} onChange={() => onToggleLayer(layer.layer_id, !layer.visible)} />
      <button type="button" className="drawer-layer-button" onClick={() => onSelectLayer(layer.layer_id)}>
        <span>{layer.name}</span>
        <small>
          {layer.geometry_type} · {layer.source}
        </small>
      </button>
    </label>
  );
}

export function SideDrawer({
  open,
  activeTab,
  templates,
  layerState,
  outputs,
  searchResults,
  searchSummary,
  statusSummary,
  onToggleOpen,
  onChangeTab,
  onToggleLayer,
  onSelectLayer,
  onFocusResult,
  onRunTemplate
}: Props) {
  const apiBase = getApiBase();
  const templateGroups = useMemo(() => groupTemplatesByChapter(templates), [templates]);
  const enabledTemplateSet = useMemo(() => new Set(layerState?.enabled_templates || []), [layerState?.enabled_templates]);
  const [openChapters, setOpenChapters] = useState<Record<string, boolean>>({});
  const [openUnits, setOpenUnits] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!templateGroups.length) {
      return;
    }
    setOpenChapters((previous) => {
      if (Object.keys(previous).length) {
        return previous;
      }
      return { [templateGroups[0].chapterId]: true };
    });
    setOpenUnits((previous) => {
      if (Object.keys(previous).length) {
        return previous;
      }
      const firstUnit = templateGroups[0].units[0];
      return firstUnit ? { [firstUnit.unitId]: true } : previous;
    });
  }, [templateGroups]);

  const enabledTemplateTitles = templates
    .filter((item) => enabledTemplateSet.has(item.template_id))
    .map((item) => item.title);

  return (
    <div className={`side-drawer ${open ? "open" : "closed"}`}>
      <button
        type="button"
        className="drawer-toggle"
        onClick={onToggleOpen}
        aria-label={open ? "收起课堂控制台" : "展开课堂控制台"}
      >
        {open ? "<" : ">"}
      </button>

      <aside className="drawer-panel glass-panel" aria-label="课堂控制台">
        <div className="drawer-header">
          <p className="panel-tag">Class Console</p>
          <strong>课堂控制台</strong>
          <span className="drawer-subtitle">章节导航、图层控制、检索记录与课堂产物</span>
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
              <span>已启用模板</span>
              <strong>{statusSummary.enabledTemplates}</strong>
            </div>
          </div>
          <p>{statusSummary.latest}</p>
        </section>

        <div className="drawer-tabs">
          <button type="button" className={activeTab === "units" ? "active" : ""} onClick={() => onChangeTab("units")}>
            单元
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
          {activeTab === "units" ? (
            <section className="drawer-section" data-testid="drawer-units">
              <div className="drawer-section-header">
                <span>课堂单元</span>
                <small>{templates.length} 个模板</small>
              </div>
              <p className="drawer-summary">按章节展开单元后加载对应课堂包或专题模板。</p>

              <div className="drawer-book-card">
                <div className="drawer-book-cover">
                  <span>地理</span>
                </div>
                <div className="drawer-book-meta">
                  <strong>课堂包目录</strong>
                  <span>{enabledTemplateTitles[0] || "请选择单元模板"}</span>
                  <small>目录结构参照教材章节，点击条目后加载对应课堂内容。</small>
                </div>
              </div>

              <div className="unit-tree">
                {templateGroups.map((chapter, chapterIndex) => {
                  const chapterOpen = openChapters[chapter.chapterId] ?? false;
                  return (
                    <div key={chapter.chapterId} className={`chapter-card ${chapterOpen ? "open" : ""}`}>
                      <button
                        type="button"
                        className={`chapter-toggle ${chapterOpen ? "open" : ""}`}
                        onClick={() =>
                          setOpenChapters((previous) => ({
                            ...previous,
                            [chapter.chapterId]: !chapterOpen
                          }))
                        }
                      >
                        <span className="chapter-index">{String(chapterIndex + 1).padStart(2, "0")}</span>
                        <div className="chapter-copy">
                          <strong>{chapter.chapterTitle}</strong>
                          <small>{chapter.units.length} 个单元</small>
                        </div>
                        <span className="chapter-arrow">{chapterOpen ? "收起" : "展开"}</span>
                      </button>

                      {chapterOpen ? (
                        <div className="chapter-units">
                          {chapter.units.map((unit) => {
                            const unitOpen = openUnits[unit.unitId] ?? false;
                            return (
                              <div key={unit.unitId} className={`unit-card ${unitOpen ? "open" : ""}`}>
                                <button
                                  type="button"
                                  className="unit-toggle"
                                  onClick={() =>
                                    setOpenUnits((previous) => ({
                                      ...previous,
                                      [unit.unitId]: !unitOpen
                                    }))
                                  }
                                >
                                  <div className="unit-toggle-main">
                                    <span className="unit-dot" />
                                    <div>
                                      <strong>{unit.unitTitle}</strong>
                                      <small>{unit.templates.length} 个模板</small>
                                    </div>
                                  </div>
                                  <span className="unit-state">{unitOpen ? "收起" : "展开"}</span>
                                </button>

                                {unitOpen ? (
                                  <div className="unit-template-list">
                                    {unit.templates.map((template) => {
                                      const enabled = enabledTemplateSet.has(template.template_id);
                                      return (
                                        <button
                                          key={template.template_id}
                                          type="button"
                                          className={`template-card ${enabled ? "active" : ""}`}
                                          onClick={() => onRunTemplate(template.template_id)}
                                        >
                                          <span className="template-card-marker" />
                                          <div className="template-card-copy">
                                            <div className="template-card-header">
                                              <strong>{template.title}</strong>
                                              <span>{enabled ? "当前" : "加载"}</span>
                                            </div>
                                            <p>{template.description}</p>
                                          </div>
                                        </button>
                                      );
                                    })}
                                  </div>
                                ) : null}
                              </div>
                            );
                          })}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </section>
          ) : null}

          {activeTab === "layers" ? (
            <section className="drawer-section" data-testid="drawer-layers">
              <div className="drawer-section-header">
                <span>课堂图层</span>
                <small>{layerState?.items.length || 0} 个</small>
              </div>
              <div className="drawer-layer-list">
                {(layerState?.items || [])
                  .slice()
                  .sort((left, right) => right.z_index - left.z_index)
                  .map((layer) => renderLayerRow(layer, layerState?.active_layer_id === layer.layer_id, onToggleLayer, onSelectLayer))}
              </div>

              <div className="drawer-section-header compact">
                <span>已启用模板</span>
              </div>
              <div className="drawer-badges">
                {enabledTemplateTitles.length ? enabledTemplateTitles.map((item) => <span key={item}>{item}</span>) : <small>暂无</small>}
              </div>
            </section>
          ) : null}

          {activeTab === "search" ? (
            <section className="drawer-section" data-testid="drawer-search">
              <div className="drawer-section-header">
                <span>POI 检索结果</span>
                <small>{searchResults.length} 条</small>
              </div>
              <p className="drawer-summary">
                {searchSummary || "在搜索栏输入关键词后，可按当前视域或手绘区域发起检索。"}
              </p>
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
              <div className="drawer-output-list">
                {outputs.length ? (
                  outputs.map((artifact) => {
                    const publicUrl = String(artifact.metadata?.public_url || "");
                    return (
                      <a
                        key={artifact.artifact_id}
                        className="drawer-output-card"
                        href={publicUrl ? `${apiBase}${publicUrl}` : undefined}
                        target="_blank"
                        rel="noreferrer"
                      >
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
