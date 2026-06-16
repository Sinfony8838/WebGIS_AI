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
    expect(screen.getByText("集中管理知识库、素材、图层、产物和课时资源，快速检索并执行课堂数据操作。")).toBeInTheDocument();
    expect(screen.getByText("人口分布知识")).toBeInTheDocument();
    expect(screen.getByText("人口图层")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("搜索"), { target: { value: "人口图层" } });

    expect(screen.queryByText("人口分布知识")).not.toBeInTheDocument();
    expect(screen.getByText("人口图层")).toBeInTheDocument();
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
});
