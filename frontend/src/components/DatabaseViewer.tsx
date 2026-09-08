import { useMemo, useState } from "react";
import { buildAuthenticatedUrl, type TeachingMapItem } from "../api";
import type {
  ArtifactRecord,
  DatasetCatalogItem,
  KnowledgeBaseItem,
  LayerRecord,
  LessonResourceSet,
  QuestionBankSummary,
  ResourceSearchResult,
  TeachingMaterial
} from "../types";

/**
 * 数据库面板分类（重组后 7 内容类 + 检索工具）：
 * - 地图数据 = 项目图层 + 一张图目录 + 课本地图（都能上地图的数据）
 * - 教学资料 = 知识库条目 + KB 素材（同一 manifest，原「知识库/素材」合并）
 * - 图片 / 分析产物 / 题库 / 课时资源 / 检索与获取
 */
export type DatabaseCategory =
  | "all"
  | "map-data"
  | "images"
  | "outputs"
  | "materials"
  | "questions"
  | "lesson"
  | "resources";

export type DatabaseMapDataSection = "layer" | "one-map" | "teaching-map";

type DatabaseEntryBase = {
  id: string;
  category: Exclude<DatabaseCategory, "all">;
  section: DatabaseMapDataSection | "material" | "knowledge";
  title: string;
  subtitle: string;
  description: string;
  status: string;
  tags: string[];
  updatedAt: string;
  thumbnailUrl?: string;
};

type DatabaseEntry = DatabaseEntryBase & (
    | {
      raw: KnowledgeBaseItem;
      kind: "knowledge";
    }
  | {
      raw: TeachingMaterial;
      parentTitle: string;
      kind: "material";
    }
  | {
      raw: LayerRecord;
      kind: "layer";
    }
  | {
      raw: ArtifactRecord;
      isImage: boolean;
      kind: "output";
    }
  | {
      raw: ResourceSearchResult;
      kind: "resource";
    }
  | {
      raw: LessonResourceSet;
      kind: "lesson";
    }
  | {
      raw: TeachingMapItem;
      kind: "teaching-map";
    }
  | {
      raw: DatasetCatalogItem;
      kind: "one-map";
    }
  | {
      raw: QuestionBankSummary;
      kind: "question-bank";
    }
  );

type Props = {
  open: boolean;
  onClose: () => void;
  knowledgeItems: KnowledgeBaseItem[];
  layers: LayerRecord[];
  outputs: ArtifactRecord[];
  lessonResourceSets: LessonResourceSet[];
  teachingMaps: TeachingMapItem[];
  datasetCatalogItems: DatasetCatalogItem[];
  questionBanks: QuestionBankSummary[];
  activeTeachingMapIds: Set<string>;
  activeLessonResourceSetId: string;
  onOpenKnowledgeItem: (item: KnowledgeBaseItem) => void;
  onOpenMaterial: (title: string, materials: TeachingMaterial[]) => void;
  onToggleLayer: (layerId: string, visible: boolean) => void;
  onFocusLayer: (layerId: string) => void;
  onOpenArtifact: (artifact: ArtifactRecord) => void;
  onDownloadArtifact: (artifact: ArtifactRecord) => void;
  onDeleteArtifact: (artifact: ArtifactRecord) => void;
  onLoadArtifactLayer: (artifact: ArtifactRecord) => void;
  onAttachImage: (artifact: ArtifactRecord) => void;
  onDeleteQuestionBank: (bank: QuestionBankSummary) => void;
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
  onResourceSearchSubmit: () => void;
  onImportResource: (item: ResourceSearchResult) => void;
  onSaveResource: (item: ResourceSearchResult) => void;
  onOpenResource: (item: ResourceSearchResult) => void;
};

const CATEGORIES: Array<{ key: DatabaseCategory; label: string }> = [
  { key: "all", label: "全部" },
  { key: "map-data", label: "地图数据" },
  { key: "images", label: "图片" },
  { key: "outputs", label: "分析产物" },
  { key: "materials", label: "教学资料" },
  { key: "questions", label: "题库" },
  { key: "lesson", label: "课时资源" },
  { key: "resources", label: "检索与获取" },
];

const SECTION_LABELS: Record<string, string> = {
  layer: "项目图层",
  "one-map": "一张图",
  "teaching-map": "课本地图",
  material: "素材",
  knowledge: "知识条目",
};

const IMAGE_ARTIFACT_TYPES = new Set(["uploaded_image", "generated_image", "map_snapshot"]);
/** 产物行的「上图」只对矢量结果开放。 */
function isVectorOutput(artifact: ArtifactRecord): boolean {
  if (artifact.artifact_type === "dataset_import") return true;
  return String(artifact.metadata?.kind || "") === "geojson";
}

function artifactTypeLabel(value: string): string {
  const table: Record<string, string> = {
    dataset_import: "数据导入",
    workflow_output: "分析结果",
    assistant_note: "助教笔记",
    class_report: "课堂报告",
    class_report_data: "报告数据",
    practice_paper_student: "学生练习卷",
    practice_paper_teacher: "教师练习卷",
    lesson_plan_docx: "教案文档",
    annotation_export: "标注导出",
    query_summary: "查询摘要",
  };
  return table[value] || value || "产物";
}

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
  questionBanks,
  activeTeachingMapIds,
  activeLessonResourceSetId,
  onOpenKnowledgeItem,
  onOpenMaterial,
  onToggleLayer,
  onFocusLayer,
  onOpenArtifact,
  onDownloadArtifact,
  onDeleteArtifact,
  onLoadArtifactLayer,
  onAttachImage,
  onDeleteQuestionBank,
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
  onResourceSearchSubmit,
  onImportResource,
  onSaveResource,
  onOpenResource,
}: Props) {
  const [query, setQuery] = useState("");
  const category = activeCategory;
  const trimmedResourceQuery = resourceQuery.trim();

  const entries = useMemo<DatabaseEntry[]>(() => {
    const layerEntries: DatabaseEntry[] = layers.map((layer) => ({
      id: `layer:${layer.layer_id}`,
      category: "map-data",
      section: "layer",
      title: layer.name || layer.layer_id,
      subtitle: `${layer.geometry_type || layer.kind} / ${layer.source || "unknown"}`,
      description: String(layer.metadata?.description || layer.metadata?.summary || layer.layer_id),
      status: layer.visible ? "显示中" : "已隐藏",
      tags: compactTags([layer.kind, layer.geometry_type, String(layer.metadata?.kb_status || "")]),
      updatedAt: String(layer.metadata?.updated_at || ""),
      raw: layer,
      kind: "layer",
    }));

    const oneMapEntries: DatabaseEntry[] = datasetCatalogItems.map((item) => ({
      id: `one-map:${item.id}`,
      category: "map-data",
      section: "one-map",
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

    const teachingMapEntries: DatabaseEntry[] = teachingMaps.map((map) => ({
      id: `teaching-map:${map.id}`,
      category: "map-data",
      section: "teaching-map",
      title: map.name || map.id,
      subtitle: map.category || "课本地图",
      description: (map.keywords || []).join("、"),
      status: map.available === false ? "缺图" : activeTeachingMapIds.has(map.id) ? "显示中" : "已关闭",
      tags: compactTags([map.category, ...(map.keywords || [])]),
      updatedAt: "",
      raw: map,
      kind: "teaching-map",
    }));

    const imageEntries: DatabaseEntry[] = outputs
      .filter((output) => IMAGE_ARTIFACT_TYPES.has(output.artifact_type))
      .map((output) => ({
        id: `image:${output.artifact_id}`,
        category: "images" as const,
        section: "material" as const,
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
        isImage: true,
        kind: "output" as const,
      }));

    const outputEntries: DatabaseEntry[] = outputs
      .filter((output) => !IMAGE_ARTIFACT_TYPES.has(output.artifact_type))
      .map((output) => ({
        id: `output:${output.artifact_id}`,
        category: "outputs" as const,
        section: "material" as const,
        title: output.title || output.artifact_id,
        subtitle: artifactTypeLabel(output.artifact_type),
        description: String(output.metadata?.summary || output.path || ""),
        status: artifactTypeLabel(output.artifact_type),
        tags: compactTags([output.artifact_type, String(output.metadata?.kind || ""), output.job_id]),
        updatedAt: output.created_at,
        raw: output,
        isImage: false,
        kind: "output" as const,
      }));

    const knowledgeEntries: DatabaseEntry[] = knowledgeItems.map((item) => ({
      id: `knowledge:${item.id}`,
      category: "materials",
      section: "knowledge",
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
        category: "materials" as const,
        section: "material" as const,
        title: material.title || material.id,
        subtitle: item.title || item.id,
        description: material.description || material.url || "",
        status: material.type || "素材",
        tags: compactTags([material.source, material.region_binding?.name]),
        updatedAt: material.created_at,
        raw: material,
        parentTitle: item.title || item.id,
        kind: "material" as const,
      }))
    );

    const questionEntries: DatabaseEntry[] = questionBanks.map((bank) => ({
      id: `question-bank:${bank.bank_id}`,
      category: "questions" as const,
      section: "material" as const,
      title: bank.title || bank.base_name,
      subtitle: `${bank.question_count} 题 / 覆盖 ${Math.round((bank.answer_coverage || 0) * 100)}%`,
      description:
        bank.answer_missing
          ? "部分题目缺少答案解析，建议核对原卷后补齐"
          : "答案解析完整，可直接绑定教案或课堂投屏",
      status: bank.answer_missing ? "待补答案" : "可用",
      tags: compactTags([bank.import_mode, bank.section_count ? `${bank.section_count} 个大题` : ""]),
      updatedAt: bank.updated_at,
      raw: bank,
      kind: "question-bank" as const,
    }));

    const resourceEntries: DatabaseEntry[] = resourceResults.map((item) => ({
      id: `resource:${item.id}`,
      category: "resources" as const,
      section: "material" as const,
      title: item.title || "未命名资料",
      subtitle: resourceSourceLabel(item),
      description: item.summary || "暂无摘要",
      status: item.type || "资源",
      tags: compactTags([item.source, item.type]),
      updatedAt: "",
      raw: item,
      thumbnailUrl: String(item.thumbnail_url || ""),
      kind: "resource" as const,
    }));

    const lessonEntries: DatabaseEntry[] = lessonResourceSets.map((set) => ({
      id: `lesson:${set.id}`,
      category: "lesson",
      section: "material",
      title: set.title || set.id,
      subtitle: `${set.item_ids.length} 条知识 / ${set.material_ids.length} 个素材`,
      description: set.region_bindings.map((binding) => binding.name).filter(Boolean).join("、"),
      status: set.id === activeLessonResourceSetId || set.active ? "当前课时" : "可切换",
      tags: compactTags([set.active ? "active" : "", set.project_id]),
      updatedAt: set.updated_at,
      raw: set,
      kind: "lesson",
    }));

    return [
      ...layerEntries,
      ...oneMapEntries,
      ...teachingMapEntries,
      ...imageEntries,
      ...outputEntries,
      ...knowledgeEntries,
      ...materialEntries,
      ...questionEntries,
      ...lessonEntries,
      ...resourceEntries,
    ];
  }, [
    activeLessonResourceSetId,
    activeTeachingMapIds,
    datasetCatalogItems,
    knowledgeItems,
    layers,
    lessonResourceSets,
    outputs,
    questionBanks,
    resourceResults,
    teachingMaps,
  ]);

  const counts = useMemo(() => {
    const next = new Map<DatabaseCategory, number>();
    for (const entry of entries) {
      next.set(entry.category, (next.get(entry.category) || 0) + 1);
    }
    next.set("all", entries.length);
    // 检索与获取是工具类：以结果数参与计数，未搜索时为 0。
    next.set("resources", resourceResults.length);
    return next;
  }, [entries, resourceResults.length]);

  const filteredEntries = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    const list = entries
      .filter((entry) => category === "all" || entry.category === category)
      .filter((entry) => {
        if (!keyword) return true;
        const haystack = [entry.title, entry.subtitle, entry.description, entry.status, ...entry.tags].join(" ").toLowerCase();
        return haystack.includes(keyword);
      });
    if (category === "map-data" || category === "all") {
      // 「全部」与地图数据保持导航定义的分区顺序，时间排序会打散分区。
      return list;
    }
    return list.sort((left, right) => {
      const leftTime = Date.parse(left.updatedAt || "");
      const rightTime = Date.parse(right.updatedAt || "");
      return (Number.isNaN(rightTime) ? 0 : rightTime) - (Number.isNaN(leftTime) ? 0 : leftTime);
    });
  }, [category, entries, query]);

  const sectionGroups = useMemo(() => {
    if (category !== "map-data" && category !== "all") {
      return null;
    }
    const order: Array<DatabaseMapDataSection | "__rest__"> =
      category === "map-data" ? ["layer", "one-map", "teaching-map"] : ["__rest__"];
    if (category === "all") {
      return [
        { key: "layer" as const, label: "项目图层" },
        { key: "one-map" as const, label: "一张图数据" },
        { key: "teaching-map" as const, label: "课本地图" },
        { key: "images" as const, label: "图片" },
        { key: "outputs" as const, label: "分析产物" },
        { key: "knowledge" as const, label: "知识条目" },
        { key: "material" as const, label: "素材" },
        { key: "question-bank" as const, label: "题库" },
        { key: "lesson" as const, label: "课时资源" },
      ]
        .map((group) => ({
          key: group.key,
          label: group.label,
          entries: filteredEntries.filter((entry) => {
            if (group.key === "images" || group.key === "outputs") {
              return entry.kind === "output" && entry.category === group.key;
            }
            if (group.key === "question-bank") {
              return entry.kind === "question-bank";
            }
            if (group.key === "lesson") {
              return entry.kind === "lesson";
            }
            if (group.key === "knowledge") {
              return entry.kind === "knowledge";
            }
            if (group.key === "material") {
              return entry.kind === "material";
            }
            // layer / one-map / teaching-map
            return entry.section === group.key;
          }),
        }))
        .filter((group) => group.entries.length > 0);
    }
    return order
      .map((key) => ({
        key,
        label: SECTION_LABELS[key] || String(key),
        entries: filteredEntries.filter((entry) => entry.section === key),
      }))
      .filter((group) => group.entries.length > 0);
  }, [category, filteredEntries]);

  if (!open) return null;

  return (
    <section className="database-viewer" role="dialog" aria-modal="true" aria-label="数据库">
      <header className="database-viewer-header">
        <div className="database-viewer-heading">
          <span>DATA ASSETS</span>
          <h2>数据库</h2>
          <p>地图数据、图片、分析产物、教学资料、题库与课时资源统一管理；检索与获取负责从知识库与权威联网补入新资料。</p>
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
          <small>地图数据 {counts.get("map-data") || 0}</small>
          <small>图片 {counts.get("images") || 0}</small>
          <small>分析产物 {counts.get("outputs") || 0}</small>
          <small>教学资料 {counts.get("materials") || 0}</small>
          <small>题库 {counts.get("questions") || 0}</small>
          <small>课时资源 {counts.get("lesson") || 0}</small>
          <small>检索结果 {counts.get("resources") || 0}</small>
        </aside>

        <div className="database-viewer-list">
          {category === "resources" ? (
            <div className="database-resource-search" data-testid="database-resource-search">
              <form
                className="live-resource-searchbar"
                onSubmit={(event) => {
                  event.preventDefault();
                  onResourceSearchSubmit();
                }}
              >
                <span className="live-resource-search-icon" aria-hidden="true">⌕</span>
                <input
                  value={resourceQuery}
                  placeholder="输入关键词后回车搜索知识库与权威联网"
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
                <button type="submit" className="database-resource-search-submit" disabled={resourceLoading || !trimmedResourceQuery}>
                  搜索
                </button>
              </form>
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
            sectionGroups ? (
              sectionGroups.map((group) => (
                <div key={group.key} className="database-section" data-testid={`database-section-${group.key}`}>
                  <h3 className="database-section-title">{group.label}</h3>
                  {group.entries.map((entry) => (
                    <DatabaseRow
                      key={entry.id}
                      entry={entry}
                      props={{
                        activeLessonResourceSetId,
                        activeTeachingMapIds,
                        onOpenKnowledgeItem,
                        onOpenMaterial,
                        onToggleLayer,
                        onFocusLayer,
                        onOpenArtifact,
                        onDownloadArtifact,
                        onDeleteArtifact,
                        onLoadArtifactLayer,
                        onAttachImage,
                        onDeleteQuestionBank,
                        onActivateLessonSet,
                        onToggleTeachingMap,
                        onLoadDataset,
                        onUseDataset,
                        onImportResource,
                        onSaveResource,
                        onOpenResource,
                      }}
                    />
                  ))}
                </div>
              ))
            ) : (
              filteredEntries.map((entry) => (
                <DatabaseRow
                  key={entry.id}
                  entry={entry}
                  props={{
                    activeLessonResourceSetId,
                    activeTeachingMapIds,
                    onOpenKnowledgeItem,
                    onOpenMaterial,
                    onToggleLayer,
                    onFocusLayer,
                    onOpenArtifact,
                    onDownloadArtifact,
                    onDeleteArtifact,
                    onLoadArtifactLayer,
                    onAttachImage,
                    onDeleteQuestionBank,
                    onActivateLessonSet,
                    onToggleTeachingMap,
                    onLoadDataset,
                    onUseDataset,
                    onImportResource,
                    onSaveResource,
                    onOpenResource,
                  }}
                />
              ))
            )
          ) : (
            <div className="database-viewer-empty">
              {category === "resources" && !trimmedResourceQuery
                ? "输入关键词后回车，检索知识库与权威联网入口"
                : "没有匹配的数据"}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

type RowHandlerProps = Pick<
  Props,
  | "activeLessonResourceSetId"
  | "activeTeachingMapIds"
  | "onOpenKnowledgeItem"
  | "onOpenMaterial"
  | "onToggleLayer"
  | "onFocusLayer"
  | "onOpenArtifact"
  | "onDownloadArtifact"
  | "onDeleteArtifact"
  | "onLoadArtifactLayer"
  | "onAttachImage"
  | "onDeleteQuestionBank"
  | "onActivateLessonSet"
  | "onToggleTeachingMap"
  | "onLoadDataset"
  | "onUseDataset"
  | "onImportResource"
  | "onSaveResource"
  | "onOpenResource"
>;

function DatabaseRow({ entry, props }: { entry: DatabaseEntry; props: RowHandlerProps }) {
  const categoryLabel = CATEGORIES.find((item) => item.key === entry.category)?.label || entry.category;
  const sectionLabel = SECTION_LABELS[entry.section] || "";
  return (
    <article className="database-row">
      <div className="database-row-main">
        <div className="database-row-title">
          <span>{sectionLabel ? `${categoryLabel} · ${sectionLabel}` : categoryLabel}</span>
          <strong>{entry.title}</strong>
        </div>
        {entry.thumbnailUrl ? (
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
          <button type="button" onClick={() => props.onOpenKnowledgeItem(entry.raw)}>
            查看详情
          </button>
        ) : null}
        {entry.kind === "material" ? (
          <button type="button" onClick={() => props.onOpenMaterial(entry.title, [entry.raw])}>
            {entry.raw.type === "video" ? "播放" : entry.raw.type === "image" ? "预览" : "打开"}
          </button>
        ) : null}
        {entry.kind === "resource" ? (
          <>
            <button type="button" onClick={() => props.onOpenResource(entry.raw)}>
              打开
            </button>
            <button type="button" onClick={() => props.onSaveResource(entry.raw)}>
              保存为素材
            </button>
            <button type="button" onClick={() => props.onImportResource(entry.raw)}>
              导入本课时
            </button>
          </>
        ) : null}
        {entry.kind === "layer" ? (
          <>
            <button type="button" onClick={() => props.onFocusLayer(entry.raw.layer_id)}>
              定位
            </button>
            <button type="button" onClick={() => props.onToggleLayer(entry.raw.layer_id, !entry.raw.visible)}>
              {entry.raw.visible ? "隐藏" : "显示"}
            </button>
          </>
        ) : null}
        {entry.kind === "output" ? (
          <>
            <button type="button" onClick={() => props.onOpenArtifact(entry.raw)}>
              查看
            </button>
            {entry.isImage ? (
              <button type="button" onClick={() => props.onAttachImage(entry.raw)}>
                加入助教
              </button>
            ) : null}
            {isVectorOutput(entry.raw) ? (
              <button type="button" onClick={() => props.onLoadArtifactLayer(entry.raw)}>
                上图
              </button>
            ) : null}
            <button type="button" onClick={() => props.onDownloadArtifact(entry.raw)}>
              下载
            </button>
            <button type="button" className="database-danger-action" onClick={() => props.onDeleteArtifact(entry.raw)}>
              删除
            </button>
          </>
        ) : null}
        {entry.kind === "question-bank" ? (
          <>
            <button type="button" onClick={() => props.onDeleteQuestionBank(entry.raw)}>
              删除题库
            </button>
          </>
        ) : null}
        {entry.kind === "lesson" ? (
          <button
            type="button"
            disabled={entry.raw.id === props.activeLessonResourceSetId || entry.raw.active}
            onClick={() => props.onActivateLessonSet(entry.raw.id)}
          >
            {entry.raw.id === props.activeLessonResourceSetId || entry.raw.active ? "当前" : "启用"}
          </button>
        ) : null}
        {entry.kind === "teaching-map" ? (
          <button
            type="button"
            onClick={() => props.onToggleTeachingMap(entry.raw.id, !props.activeTeachingMapIds.has(entry.raw.id))}
          >
            {props.activeTeachingMapIds.has(entry.raw.id) ? "关闭" : "显示"}
          </button>
        ) : null}
        {entry.kind === "one-map" ? (
          <>
            <button
              type="button"
              disabled={!props.onLoadDataset || !isLoadableCatalogItem(entry.raw)}
              onClick={() => props.onLoadDataset?.(entry.raw)}
            >
              {entry.raw.format.toLowerCase() === "csv" ? "关联加载" : "加载"}
            </button>
            <button type="button" disabled={!props.onUseDataset} onClick={() => props.onUseDataset?.(entry.raw)}>
              制图
            </button>
          </>
        ) : null}
      </div>
    </article>
  );
}
