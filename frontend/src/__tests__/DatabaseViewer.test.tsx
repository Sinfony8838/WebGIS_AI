import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import { DatabaseViewer } from "../components/DatabaseViewer";

type DatabaseViewerProps = ComponentProps<typeof DatabaseViewer>;

afterEach(() => {
  cleanup();
});

function createProps(overrides: Partial<DatabaseViewerProps> = {}): DatabaseViewerProps {
  return {
    open: true,
    onClose: vi.fn(),
    activeCategory: "all",
    onCategoryChange: vi.fn(),
    resourceQuery: "",
    resourceScope: "all",
    resourceLoading: false,
    resourceResults: [],
    onResourceQueryChange: vi.fn(),
    onResourceScopeChange: vi.fn(),
    onImportResource: vi.fn(),
    onOpenResource: vi.fn(),
    onResourceSearchSubmit: vi.fn(),
    onSaveResource: vi.fn(),
    questionBanks: [],
    onDownloadArtifact: vi.fn(),
    onDeleteArtifact: vi.fn(),
    onLoadArtifactLayer: vi.fn(),
    onAttachImage: vi.fn(),
    onDeleteQuestionBank: vi.fn(),
    knowledgeItems: [
      {
        id: "kb_population",
        title: "人口分布知识",
        topic: "人口",
        region: "中国",
        time: "",
        status: "knowledge_only",
        source: "builtin",
        license: "",
        grade_level: "高中",
        keywords: ["人口"],
        tags: ["课堂"],
        crs: "EPSG:4326",
        summary: "人口地理基础知识",
        canonical_answer: "",
        teaching_points: [],
        citations: [],
        dataset_refs: [],
        materials: [],
        related_templates: [],
        updated_at: "2026-06-12T10:00:00Z",
      },
    ],
    layers: [
      {
        layer_id: "layer_population",
        name: "人口图层",
        kind: "vector",
        source: "upload",
        geometry_type: "Polygon",
        visible: true,
        opacity: 1,
        z_index: 10,
        style: {},
        data: {},
        metadata: {},
      },
    ],
    outputs: [],
    lessonResourceSets: [],
    teachingMaps: [],
    datasetCatalogItems: [],
    activeTeachingMapIds: new Set(),
    activeLessonResourceSetId: "",
    onOpenKnowledgeItem: vi.fn(),
    onOpenMaterial: vi.fn(),
    onToggleLayer: vi.fn(),
    onFocusLayer: vi.fn(),
    onOpenArtifact: vi.fn(),
    onActivateLessonSet: vi.fn(),
    onToggleTeachingMap: vi.fn(),
    onLoadDataset: vi.fn(),
    onUseDataset: vi.fn(),
    onUpload: vi.fn(),
    ...overrides,
  };
}

describe("DatabaseViewer", () => {
  it("keeps the database page open when import is requested", () => {
    const props = createProps();
    render(<DatabaseViewer {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "导入数据" }));

    expect(props.onUpload).toHaveBeenCalledTimes(1);
    expect(props.onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "数据库" })).toBeInTheDocument();
  });

  it("renders a clean data-management heading and searchable records", () => {
    render(<DatabaseViewer {...createProps()} />);

    expect(screen.getByRole("heading", { name: "数据库" })).toBeInTheDocument();
    expect(screen.getByText("地图数据、图片、分析产物、教学资料、题库与课时资源统一管理；检索与获取负责从知识库与权威联网补入新资料。")).toBeInTheDocument();
    // 「全部」页按分区渲染：知识条目与项目图层分区都应出现。
    expect(screen.getByTestId("database-section-knowledge")).toHaveTextContent("人口分布知识");
    expect(screen.getByTestId("database-section-layer")).toHaveTextContent("人口图层");

    fireEvent.change(screen.getByLabelText("搜索"), { target: { value: "不存在的关键词xyz" } });

    expect(screen.queryByText("人口分布知识")).not.toBeInTheDocument();
    expect(screen.queryByText("人口图层")).not.toBeInTheDocument();
    expect(screen.getByText("没有匹配的数据")).toBeInTheDocument();
  });

  it("renders one-map catalog entries and supports loading or mapping", () => {
    const props = createProps({
      datasetCatalogItems: [
        {
          id: "world_population_density",
          name: "World population density",
          category: "population",
          source: "builtin:one_map/population/world_population_density.geojson",
          format: "geojson",
          fields: ["name", "population", "area", "density"],
          coverage: "World country-level",
          source_year: "2019",
          source_name: "Natural Earth",
          source_url: "https://www.naturalearthdata.com/",
          license: "public domain",
          includes_taiwan: true,
          status: "ready",
          geometry_type: "MultiPolygon",
          recommended_template: "population_choropleth",
          population_fields: ["name", "population", "area", "density"],
          tags: ["population"],
          description: "World population density dataset.",
        },
      ],
    });
    render(<DatabaseViewer {...props} />);

    expect(screen.getByText("World population density")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "加载" }));
    expect(props.onLoadDataset).toHaveBeenCalledWith(props.datasetCatalogItems[0]);

    fireEvent.click(screen.getByRole("button", { name: "制图" }));

    expect(props.onUseDataset).toHaveBeenCalledWith(props.datasetCatalogItems[0]);
  });

  it("allows joined CSV catalog entries to load as one-map layers", () => {
    const props = createProps({
      datasetCatalogItems: [
        {
          id: "world_population_by_country",
          name: "World population CSV",
          category: "population",
          source: "builtin:one_map/population/world_population_by_country.csv",
          format: "csv",
          geometry_source: "world_countries",
          join_key: "region_code",
          fields: ["name", "population", "area", "density", "region_code"],
          coverage: "World country-level",
          source_year: "2019",
          source_name: "Natural Earth",
          source_url: "https://www.naturalearthdata.com/",
          license: "public domain",
          includes_taiwan: true,
          status: "ready",
          geometry_type: "",
          recommended_template: "",
          population_fields: ["name", "population", "area", "density"],
          tags: ["population"],
          description: "World population CSV joined to countries.",
        },
      ],
    });
    render(<DatabaseViewer {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "关联加载" }));

    expect(props.onLoadDataset).toHaveBeenCalledWith(props.datasetCatalogItems[0]);
  });

  it("keeps the built-in world population CSV loadable when join metadata is missing from the response", () => {
    const props = createProps({
      datasetCatalogItems: [
        {
          id: "world_population_by_country",
          name: "World population CSV",
          category: "population",
          source: "builtin:one_map/population/world_population_by_country.csv",
          format: "csv",
          fields: ["name", "population", "area", "density", "region_code"],
          coverage: "World country-level",
          source_year: "2019",
          source_name: "Natural Earth",
          source_url: "https://www.naturalearthdata.com/",
          license: "public domain",
          includes_taiwan: true,
          status: "ready",
          geometry_type: "",
          recommended_template: "",
          population_fields: ["name", "population", "area", "density"],
          tags: ["population"],
          description: "World population CSV joined to countries.",
        },
      ],
    });
    render(<DatabaseViewer {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "关联加载" }));
    expect(props.onLoadDataset).toHaveBeenCalledWith(props.datasetCatalogItems[0]);
  });

  it("organizes content into the 7-category navigation with section grouping", () => {
    const props = createProps({
      outputs: [
        {
          artifact_id: "wf_out",
          project_id: "p1",
          job_id: "j1",
          artifact_type: "workflow_output",
          title: "胡焕庸线分析结果",
          path: "/tmp/out.geojson",
          metadata: { kind: "geojson", public_url: "/files/out.geojson" },
          created_at: "2026-06-13T08:00:00Z",
        },
      ],
      questionBanks: [
        {
          bank_id: "bank1",
          project_id: "p1",
          title: "人口专题题库",
          base_name: "人口",
          import_mode: "paired",
          answer_missing: false,
          section_count: 2,
          group_count: 3,
          question_count: 12,
          answer_complete_count: 12,
          answer_coverage: 1,
          image_count: 0,
          pairing_note_count: 0,
          stats: {},
          created_at: "2026-06-13T08:00:00Z",
          updated_at: "2026-06-13T08:00:00Z",
        },
      ],
    });
    render(<DatabaseViewer {...props} />);

    // 新 7 类导航 + 每类计数（用导航容器内精确文本匹配，避免撞分区标题）。
    const tabsNav = screen.getByLabelText("数据库分类");
    for (const label of ["全部", "地图数据", "图片", "分析产物", "教学资料", "题库", "课时资源", "检索与获取"]) {
      const tab = Array.from(tabsNav.querySelectorAll("button")).find((btn) => btn.textContent?.includes(label));
      expect(tab, label).toBeTruthy();
    }
    // 「全部」页按分区渲染（项目图层/一张图/知识条目/题库…）。
    expect(screen.getByTestId("database-section-layer")).toBeInTheDocument();
    expect(screen.getByText("人口图层")).toBeInTheDocument();
    expect(screen.getByText("胡焕庸线分析结果")).toBeInTheDocument();
    expect(screen.getByText("人口专题题库")).toBeInTheDocument();
    // 分析产物分区有工作流产物行。
    expect(screen.getByTestId("database-section-outputs")).toBeInTheDocument();
    // 旧分类词汇不再出现在导航中（分区标题里的「一张图数据」是分区名，允许存在）。
    const tabTexts = Array.from(tabsNav.querySelectorAll("button")).map((btn) => btn.textContent || "");
    expect(tabTexts.some((text) => text.includes("知识库") || text.includes("素材") || text.includes("图层"))).toBe(false);
  });

  it("shows image actions: attach to assistant, download and delete", () => {
    const props = createProps({
      activeCategory: "images",
      outputs: [
        {
          artifact_id: "img1",
          project_id: "p1",
          job_id: "j1",
          artifact_type: "generated_image",
          title: "AI示意图",
          path: "/tmp/img.png",
          metadata: { public_url: "/files/img.png" },
          created_at: "2026-06-13T08:00:00Z",
        },
      ],
    });
    render(<DatabaseViewer {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "加入助教" }));
    expect(props.onAttachImage).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "下载" }));
    expect(props.onDownloadArtifact).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(props.onDeleteArtifact).toHaveBeenCalledTimes(1);
  });

  it("offers load-as-layer for geojson outputs only", () => {
    const props = createProps({
      activeCategory: "outputs",
      outputs: [
        {
          artifact_id: "geo_out",
          project_id: "p1",
          job_id: "j1",
          artifact_type: "workflow_output",
          title: "矢量结果",
          path: "/tmp/out.geojson",
          metadata: { kind: "geojson", public_url: "/files/out.geojson" },
          created_at: "2026-06-13T08:00:00Z",
        },
        {
          artifact_id: "note_out",
          project_id: "p1",
          job_id: "j2",
          artifact_type: "assistant_note",
          title: "讲解笔记",
          path: "/tmp/note.md",
          metadata: {},
          created_at: "2026-06-13T09:00:00Z",
        },
      ],
    });
    render(<DatabaseViewer {...props} />);

    expect(screen.getByRole("button", { name: "上图" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "上图" }));
    expect(props.onLoadArtifactLayer).toHaveBeenCalledWith(
      expect.objectContaining({ artifact_id: "geo_out" })
    );
    // 非矢量产物没有上图按钮：只有 1 个。
    expect(screen.getAllByRole("button", { name: "上图" })).toHaveLength(1);
  });

  it("searches resources on submit and offers save-to-library", () => {
    const props = createProps({
      activeCategory: "resources",
      resourceQuery: "人口迁移",
      resourceResults: [
        {
          id: "web1",
          title: "世界人口迁移报告",
          source: "authoritative_web",
          type: "report",
          summary: "联合国人口署报告",
          url: "https://example.org/report",
          thumbnail_url: "",
          citations: [],
          confidence: 0.9,
        },
      ],
    });
    render(<DatabaseViewer {...props} />);

    fireEvent.submit(screen.getByRole("button", { name: "搜索" }).closest("form")!);
    expect(props.onResourceSearchSubmit).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "保存为素材" }));
    expect(props.onSaveResource).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "导入本课时" }));
    expect(props.onImportResource).toHaveBeenCalledTimes(1);
  });
});
