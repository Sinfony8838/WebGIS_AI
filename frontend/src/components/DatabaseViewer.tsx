import { useMemo, useState } from "react";
import { buildAuthenticatedUrl, type TeachingMapItem } from "../api";
import type {
  ArtifactRecord,
  DatasetCatalogItem,
  KnowledgeBaseItem,
  LayerRecord,
  LessonResourceSet,
  ResourceSearchResult,
  TeachingMaterial
} from "../types";

export type DatabaseCategory =
  | "all"
  | "knowledge"
  | "materials"
  | "resources"
  | "layers"
  | "images"
  | "outputs"
  | "lesson"
  | "teaching-maps"
  | "one-map";

type DatabaseEntry =
  | {
      id: string;
      category: Exclude<DatabaseCategory, "all">;
      title: string;
      subtitle: string;
      description: string;
      status: string;
      tags: string[];
      updatedAt: string;
      raw: KnowledgeBaseItem;
      kind: "knowledge";
    }
  | {
      id: string;
      category: Exclude<DatabaseCategory, "all">;
      title: string;
      subtitle: string;
      description: string;
      status: string;
      tags: string[];
      updatedAt: string;
      raw: TeachingMaterial;
      parentTitle: string;
      kind: "material";
    }
  | {
      id: string;
      category: Exclude<DatabaseCategory, "all">;
      title: string;
      subtitle: string;
      description: string;
      status: string;
      tags: string[];
      updatedAt: string;
      raw: LayerRecord;
      kind: "layer";
    }
  | {
      id: string;
      category: Exclude<DatabaseCategory, "all">;
      title: string;
      subtitle: string;
      description: string;
      status: string;
      tags: string[];
      updatedAt: string;
      raw: ArtifactRecord;
      thumbnailUrl?: string;
      kind: "output";
    }
  | {
      id: string;
      category: Exclude<DatabaseCategory, "all">;
      title: string;
      subtitle: string;
      description: string;
      status: string;
      tags: string[];
      updatedAt: string;
      raw: ResourceSearchResult;
      kind: "resource";
    }
  | {
      id: string;
      category: Exclude<DatabaseCategory, "all">;
      title: string;
      subtitle: string;
      description: string;
      status: string;
      tags: string[];
      updatedAt: string;
      raw: LessonResourceSet;
      kind: "lesson";
    }
  | {
      id: string;
      category: Exclude<DatabaseCategory, "all">;
      title: string;
      subtitle: string;
      description: string;
      status: string;
      tags: string[];
      updatedAt: string;
      raw: TeachingMapItem;
      kind: "teaching-map";
    }
  | {
      id: string;
      category: Exclude<DatabaseCategory, "all">;
      title: string;
      subtitle: string;
      description: string;
      status: string;
      tags: string[];
      updatedAt: string;
      raw: DatasetCatalogItem;
      kind: "one-map";
    };

type Props = {
  open: boolean;
  onClose: () => void;
  knowledgeItems: KnowledgeBaseItem[];
  layers: LayerRecord[];
  outputs: ArtifactRecord[];
  lessonResourceSets: LessonResourceSet[];
  teachingMaps: TeachingMapItem[];
  datasetCatalogItems: DatasetCatalogItem[];
  activeTeachingMapIds: Set<string>;
  activeLessonResourceSetId: string;
  onOpenKnowledgeItem: (item: KnowledgeBaseItem) => void;
  onOpenMaterial: (title: string, materials: TeachingMaterial[]) => void;
  onToggleLayer: (layerId: string, visible: boolean) => void;
  onFocusLayer: (layerId: string) => void;
  onOpenArtifact: (artifact: ArtifactRecord) => void;
  onActivateLessonSet: (setId: string) => void;
  onToggleTeachingMap: (mapId: string, visible: boolean) => void;
  onLoadDataset?: (item: DatasetCatalogItem) => void;
  onUseDataset?: (item: DatasetCatalogItem) => void;
  onUpload?: () => void;
  activeCategory: DatabaseCategory;
  onCategoryChange: (category: DatabaseCategory) => void;
  resourceQuery: string;
  resourceScope: "all" | "kb" | "web";
  resourceLoading: boolean;
  resourceResults: ResourceSearchResult[];
  onResourceQueryChange: (value: string) => void;
  onResourceScopeChange: (value: "all" | "kb" | "web") => void;
  onImportResource: (item: ResourceSearchResult) => void;
  onOpenResource: (item: ResourceSearchResult) => void;
};

const CATEGORIES: Array<{ key: DatabaseCategory; label: string }> = [
  { key: "all", label: "全部" },
  { key: "knowledge", label: "知识库" },
  { key: "materials", label: "素材" },
  { key: "resources", label: "资源检索" },
  { key: "layers", label: "图层" },
  { key: "images", label: "图片" },
  { key: "outputs", label: "产物" },
  { key: "lesson", label: "课时资源" },
  { key: "teaching-maps", label: "课本地图" },
  { key: "one-map", label: "一张图数据" },
];

const IMAGE_ARTIFACT_TYPES = new Set(["uploaded_image", "generated_image", "map_snapshot"]);

function resourceSourceLabel(item: ResourceSearchResult): string {
  if (item.source === "knowledge_base") return "知识库";
  if (item.source === "authoritative_web" || item.source === "web") return "权威联网";
  return item.source || item.type || "资源";
}

function formatDate(value: string): string {
  if (!value) return "未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function compactTags(values: Array<string | undefined>): string[] {
  return values.filter((value): value is string => Boolean(value && value.trim())).slice(0, 4);
}

function normalizeStatus(value: string): string {
  if (value === "knowledge_only") return "知识";
  if (value === "renderable_layer") return "可显示";
  if (value === "stored_only") return "存档";
  return value || "未分类";
}

function isLoadableCatalogItem(item: DatasetCatalogItem): boolean {
  const format = item.format.toLowerCase();
  const isKnownJoinableCsv = item.id === "world_population_by_country";
  return format === "geojson" || (format === "csv" && (isKnownJoinableCsv || Boolean(item.geometry_source && item.join_key)));
}

export function DatabaseViewer({
  open,
  onClose,
  knowledgeItems,
  layers,
  outputs,
  lessonResourceSets,
  teachingMaps,
  datasetCatalogItems,
  activeTeachingMapIds,
  activeLessonResourceSetId,
  onOpenKnowledgeItem,
  onOpenMaterial,
  onToggleLayer,
  onFocusLayer,
  onOpenArtifact,
  onActivateLessonSet,
  onToggleTeachingMap,
  onLoadDataset,
  onUseDataset,
  onUpload,
  activeCategory,
  onCategoryChange,
  resourceQuery,
  resourceScope,
  resourceLoading,
  resourceResults,
  onResourceQueryChange,
  onResourceScopeChange,
  onImportResource,
  onOpenResource,
}: Props) {
  const [query, setQuery] = useState("");
  const category = activeCategory;
  const trimmedResourceQuery = resourceQuery.trim();

  const entries = useMemo<DatabaseEntry[]>(() => {
    const knowledgeEntries: DatabaseEntry[] = knowledgeItems.map((item) => ({
      id: `knowledge:${item.id}`,
      category: "knowledge",
      title: item.title || item.id,
      subtitle: `${item.topic || "未分类"} / ${item.region || "未标注区域"}`,
      description: item.summary || item.canonical_answer || "",
      status: normalizeStatus(item.status || "knowledge_only"),
      tags: compactTags([item.source, item.grade_level, ...(item.tags || []), ...(item.keywords || [])]),
      updatedAt: item.updated_at,
      raw: item,
      kind: "knowledge",
    }));

    const materialEntries: DatabaseEntry[] = knowledgeItems.flatMap((item) =>
      (item.materials || []).map((material) => ({
        id: `material:${material.id}`,
        category: "materials",
        title: material.title || material.id,
        subtitle: item.title || item.id,
        description: material.description || material.url || "",
        status: material.type || "素材",
        tags: compactTags([material.source, material.region_binding?.name]),
        updatedAt: material.created_at,
        raw: material,
        parentTitle: item.title || item.id,
        kind: "material",
      }))
    );

    const layerEntries: DatabaseEntry[] = layers.map((layer) => ({
      id: `layer:${layer.layer_id}`,
      category: "layers",
      title: layer.name || layer.layer_id,
      subtitle: `${layer.geometry_type || layer.kind} / ${layer.source || "unknown"}`,
      description: String(layer.metadata?.description || layer.metadata?.summary || layer.layer_id),
      status: layer.visible ? "显示中" : "已隐藏",
      tags: compactTags([layer.kind, layer.geometry_type, String(layer.metadata?.kb_status || "")]),
      updatedAt: String(layer.metadata?.updated_at || ""),
      raw: layer,
      kind: "layer",
    }));

    const imageEntries: DatabaseEntry[] = outputs
      .filter((output) => IMAGE_ARTIFACT_TYPES.has(output.artifact_type))
      .map((output) => ({
        id: `image:${output.artifact_id}`,
        category: "images" as const,
        title: output.title || output.artifact_id,
        subtitle:
          output.artifact_type === "generated_image"
            ? "AI 生成示意图"
            : output.artifact_type === "map_snapshot"
              ? "地图截图"
              : "本地上传图片",
        description: String(output.metadata?.summary || output.path || ""),
        status: "已入库",
        tags: compactTags([output.artifact_type, output.job_id]),
        updatedAt: output.created_at,
        raw: output,
        thumbnailUrl: String(output.metadata?.public_url || ""),
        kind: "output" as const,
      }));

    const outputEntries: DatabaseEntry[] = outputs
      .filter((output) => !IMAGE_ARTIFACT_TYPES.has(output.artifact_type))
      .map((output) => ({
        id: `output:${output.artifact_id}`,
        category: "outputs" as const,
        title: output.title || output.artifact_id,
        subtitle: output.artifact_type || "产物",
        description: String(output.metadata?.summary || output.path || ""),
        status: output.artifact_type || "产物",
        tags: compactTags([output.artifact_type, output.job_id]),
        updatedAt: output.created_at,
        raw: output,
        kind: "output" as const,
      }));

    const resourceEntries: DatabaseEntry[] = resourceResults.map((item) => ({
      id: `resource:${item.id}`,
      category: "resources" as const,
      title: item.title || "未命名资料",
      subtitle: resourceSourceLabel(item),
      description: item.summary || "暂无摘要",
      status: item.type || "资源",
      tags: compactTags([item.source, item.type]),
      updatedAt: "",
      raw: item,
      kind: "resource" as const,
    }));

    const lessonEntries: DatabaseEntry[] = lessonResourceSets.map((set) => ({
      id: `lesson:${set.id}`,
      category: "lesson",
      title: set.title || set.id,
      subtitle: `${set.item_ids.length} 条知识 / ${set.material_ids.length} 个素材`,
      description: set.region_bindings.map((binding) => binding.name).filter(Boolean).join("、"),
      status: set.id === activeLessonResourceSetId || set.active ? "当前课时" : "可切换",
      tags: compactTags([set.active ? "active" : "", set.project_id]),
      updatedAt: set.updated_at,
      raw: set,
      kind: "lesson",
    }));

    const teachingMapEntries: DatabaseEntry[] = teachingMaps.map((map) => ({
      id: `teaching-map:${map.id}`,
      category: "teaching-maps",
      title: map.name || map.id,
      subtitle: map.category || "课本地图",
      description: (map.keywords || []).join("、"),
      status: activeTeachingMapIds.has(map.id) ? "显示中" : "已关闭",
      tags: compactTags([map.category, ...(map.keywords || [])]),
      updatedAt: "",
      raw: map,
      kind: "teaching-map",
    }));

    const oneMapEntries: DatabaseEntry[] = datasetCatalogItems.map((item) => ({
      id: `one-map:${item.id}`,
      category: "one-map",
      title: item.name || item.id,
      subtitle: `${item.category || "one_map"} / ${item.coverage || item.format}`,
      description: item.description || item.source_name || item.source,
      status: item.status || "ready",
      tags: compactTags([
        item.format,
        item.geometry_type,
        item.source_year,
        item.includes_taiwan ? "includes Taiwan" : "",
        ...(item.tags || []),
      ]),
      updatedAt: "",
      raw: item,
      kind: "one-map",
    }));

    return [...oneMapEntries, ...knowledgeEntries, ...materialEntries, ...resourceEntries, ...layerEntries, ...imageEntries, ...outputEntries, ...lessonEntries, ...teachingMapEntries];
  }, [
    activeLessonResourceSetId,
    activeTeachingMapIds,
    datasetCatalogItems,
    knowledgeItems,
    layers,
    lessonResourceSets,
    outputs,
    resourceResults,
    teachingMaps,
  ]);

  const counts = useMemo(() => {
    const next = new Map<DatabaseCategory, number>();
    next.set("all", entries.length);
    for (const entry of entries) {
      next.set(entry.category, (next.get(entry.category) || 0) + 1);
    }
    return next;
  }, [entries]);

  const filteredEntries = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return entries
      .filter((entry) => category === "all" || entry.category === category)
      .filter((entry) => {
        if (!keyword) return true;
        const haystack = [entry.title, entry.subtitle, entry.description, entry.status, ...entry.tags].join(" ").toLowerCase();
        return haystack.includes(keyword);
      })
      .sort((left, right) => {
        const leftTime = Date.parse(left.updatedAt || "");
        const rightTime = Date.parse(right.updatedAt || "");
        return (Number.isNaN(rightTime) ? 0 : rightTime) - (Number.isNaN(leftTime) ? 0 : leftTime);
      });
  }, [category, entries, query]);

  if (!open) return null;

  return (
    <section className="database-viewer" role="dialog" aria-modal="true" aria-label="数据库">
      <header className="database-viewer-header">
        <div className="database-viewer-heading">
          <span>DATA ASSETS</span>
          <h2>数据库</h2>
          <p>集中管理知识库、素材、资源检索、图层、图片、产物和课时数据，课内外资源统一在此存储与检索。</p>
        </div>
        <div className="database-viewer-actions">
          <label className="database-viewer-search">
            <span>搜索</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索名称、分类、来源、关键词"
            />
          </label>
          {onUpload && (
            <button type="button" className="database-primary-action" onClick={onUpload}>
              导入数据
            </button>
          )}
          <button type="button" className="database-secondary-action" onClick={onClose}>
            关闭
          </button>
        </div>
      </header>

      <nav className="database-viewer-tabs" aria-label="数据库分类">
        {CATEGORIES.map((item) => (
          <button
            key={item.key}
            type="button"
            className={category === item.key ? "active" : ""}
            onClick={() => onCategoryChange(item.key)}
          >
            <span>{item.label}</span>
            <em>{counts.get(item.key) || 0}</em>
          </button>
        ))}
      </nav>

      <div className="database-viewer-body">
        <aside className="database-viewer-summary">
          <strong>{filteredEntries.length}</strong>
          <span>当前结果</span>
          <small>总记录 {entries.length}</small>
          <small>知识库 {counts.get("knowledge") || 0}</small>
          <small>素材 {counts.get("materials") || 0}</small>
          <small>资源 {counts.get("resources") || 0}</small>
          <small>图层 {counts.get("layers") || 0}</small>
          <small>图片 {counts.get("images") || 0}</small>
          <small>产物 {counts.get("outputs") || 0}</small>
          <small>一张图 {counts.get("one-map") || 0}</small>
        </aside>

        <div className="database-viewer-list">
          {category === "resources" ? (
            <div className="database-resource-search" data-testid="database-resource-search">
              <div className="live-resource-searchbar">
                <span className="live-resource-search-icon" aria-hidden="true">⌕</span>
                <input
                  value={resourceQuery}
                  placeholder="搜索地理概念、区域或权威资料"
                  onChange={(event) => onResourceQueryChange(event.target.value)}
                  aria-label="资源检索"
                />
                {trimmedResourceQuery ? (
                  <button
                    type="button"
                    className="live-resource-search-clear"
                    onClick={() => onResourceQueryChange("")}
                    aria-label="清除资源检索"
                  >
                    ×
                  </button>
                ) : null}
              </div>
              <div className="live-resource-toolbar">
                <div className="live-resource-scopes" role="tablist" aria-label="资源检索范围">
                  {([["all", "全部"], ["kb", "知识库"], ["web", "联网"]] as const).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      role="tab"
                      aria-selected={resourceScope === value}
                      className={resourceScope === value ? "active" : ""}
                      onClick={() => onResourceScopeChange(value)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <span className="live-resource-status">
                  {resourceLoading ? (
                    <>
                      <span className="live-resource-spinner" aria-hidden="true" />
                      搜索中
                    </>
                  ) : (
                    `${resourceResults.length} 条结果`
                  )}
                </span>
              </div>
            </div>
          ) : null}
          {filteredEntries.length ? (
            filteredEntries.map((entry) => (
              <article key={entry.id} className="database-row">
                <div className="database-row-main">
                  <div className="database-row-title">
                    <span>{CATEGORIES.find((item) => item.key === entry.category)?.label || entry.category}</span>
                    <strong>{entry.title}</strong>
                  </div>
                  {entry.kind === "output" && entry.thumbnailUrl ? (
                    <img
                      className="database-row-thumb"
                      src={buildAuthenticatedUrl(entry.thumbnailUrl)}
                      alt={entry.title}
                      loading="lazy"
                    />
                  ) : null}
                  <p>{entry.description || entry.subtitle}</p>
                  <div className="database-row-meta">
                    <span>{entry.subtitle}</span>
                    <span>{entry.status}</span>
                    <span>{formatDate(entry.updatedAt)}</span>
                  </div>
                  {entry.tags.length ? (
                    <div className="database-row-tags">
                      {entry.tags.map((tag) => (
                        <span key={tag}>{tag}</span>
                      ))}
                    </div>
                  ) : null}
                </div>
                <div className="database-row-actions">
                  {entry.kind === "knowledge" ? (
                    <button type="button" onClick={() => onOpenKnowledgeItem(entry.raw)}>
                      编辑
                    </button>
                  ) : null}
                  {entry.kind === "material" ? (
                    <button type="button" onClick={() => onOpenMaterial(entry.title, [entry.raw])}>
                      {entry.raw.type === "video" ? "播放" : "打开"}
                    </button>
                  ) : null}
                  {entry.kind === "resource" ? (
                    <>
                      <button type="button" onClick={() => onOpenResource(entry.raw)}>
                        打开
                      </button>
                      <button type="button" onClick={() => onImportResource(entry.raw)}>
                        导入本课时
                      </button>
                    </>
                  ) : null}
                  {entry.kind === "layer" ? (
                    <>
                      <button type="button" onClick={() => onFocusLayer(entry.raw.layer_id)}>
                        定位
                      </button>
                      <button type="button" onClick={() => onToggleLayer(entry.raw.layer_id, !entry.raw.visible)}>
                        {entry.raw.visible ? "隐藏" : "显示"}
                      </button>
                    </>
                  ) : null}
                  {entry.kind === "output" ? (
                    <button type="button" onClick={() => onOpenArtifact(entry.raw)}>
                      查看
                    </button>
                  ) : null}
                  {entry.kind === "lesson" ? (
                    <button
                      type="button"
                      disabled={entry.raw.id === activeLessonResourceSetId || entry.raw.active}
                      onClick={() => onActivateLessonSet(entry.raw.id)}
                    >
                      {entry.raw.id === activeLessonResourceSetId || entry.raw.active ? "当前" : "启用"}
                    </button>
                  ) : null}
                  {entry.kind === "teaching-map" ? (
                    <button
                      type="button"
                      onClick={() => onToggleTeachingMap(entry.raw.id, !activeTeachingMapIds.has(entry.raw.id))}
                    >
                      {activeTeachingMapIds.has(entry.raw.id) ? "关闭" : "显示"}
                    </button>
                  ) : null}
                  {entry.kind === "one-map" ? (
                    <>
                      <button
                        type="button"
                        disabled={!onLoadDataset || !isLoadableCatalogItem(entry.raw)}
                        onClick={() => onLoadDataset?.(entry.raw)}
                      >
                        {entry.raw.format.toLowerCase() === "csv" ? "关联加载" : "加载"}
                      </button>
                      <button type="button" disabled={!onUseDataset} onClick={() => onUseDataset?.(entry.raw)}>
                        制图
                      </button>
                    </>
                  ) : null}
                </div>
              </article>
            ))
          ) : (
            <div className="database-viewer-empty">
              {category === "resources" && !trimmedResourceQuery
                ? "输入关键词后会实时搜索知识库与权威联网入口"
                : "没有匹配的数据"}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
