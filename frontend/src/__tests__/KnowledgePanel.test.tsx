import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { KnowledgePanel } from "../components/KnowledgePanel";
import type { KnowledgeBaseItem, KnowledgeTopicSummary } from "../types";

function sampleItem(id = "kb_ports"): KnowledgeBaseItem {
  return {
    id,
    title: "港口分布示例",
    topic: "shipping",
    region: "china_east",
    time: "2024",
    status: "renderable_layer",
    source: "teacher_upload",
    license: "teaching_only",
    grade_level: "high_school",
    keywords: ["港口", "区位"],
    tags: ["港口", "交通"],
    crs: "EPSG:4326",
    summary: "沿海港口呈集聚分布。",
    canonical_answer: "港口受地形、航道和产业腹地影响。",
    teaching_points: ["先看空间分布", "再解释区位机制"],
    citations: [],
    dataset_refs: [{ layer_id: "ports_layer", layer_name: "港口点位" }],
    related_templates: [],
    updated_at: "2026-04-28T00:00:00+00:00"
  };
}

const topics: KnowledgeTopicSummary[] = [
  {
    topic: "shipping",
    title: "港口交通",
    item_count: 1,
    renderable_count: 1,
    stored_only_count: 0,
    knowledge_only_count: 0,
    sample_titles: ["港口分布示例"]
  }
];

function renderPanel(overrides: Partial<Parameters<typeof KnowledgePanel>[0]> = {}) {
  const handlers = {
    onToggleCollapse: vi.fn(),
    onQueryChange: vi.fn(),
    onSearch: vi.fn(),
    onSelectItem: vi.fn(),
    onEditingItemChange: vi.fn(),
    onSaveItem: vi.fn(),
    onRegisterActiveLayer: vi.fn(),
    onFocusLayer: vi.fn()
  };

  render(
    <KnowledgePanel
      collapsed
      loading={false}
      total={1}
      items={[sampleItem()]}
      topics={topics}
      query={{ query: "", topic: "", region: "", tag: "" }}
      editingItem={sampleItem()}
      activeLayerId="ports_layer"
      availableLayerIds={["ports_layer"]}
      canRegister
      {...handlers}
      {...overrides}
    />
  );

  return handlers;
}

describe("KnowledgePanel", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders in collapsed mode and toggles by header button", () => {
    const handlers = renderPanel({ collapsed: true });
    expect(screen.queryByTestId("kb-results")).toBeNull();
    expect(screen.getByText("知识库")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("折叠或展开知识库"));
    expect(handlers.onToggleCollapse).toHaveBeenCalledTimes(1);
  });

  it("renders search, results and detail when expanded", () => {
    renderPanel({ collapsed: false, total: 6 });
    expect(screen.getByText("课堂知识检索")).toBeInTheDocument();
    expect(screen.getByText("6 条")).toBeInTheDocument();
    expect(screen.getByText("港口交通 1")).toBeInTheDocument();
  });

  it("updates query fields and triggers search", () => {
    const handlers = renderPanel({ collapsed: false });
    fireEvent.change(screen.getByPlaceholderText("输入人口、气候、交通等关键词"), {
      target: { value: "港口" }
    });
    fireEvent.click(screen.getByTestId("kb-search-button"));
    expect(handlers.onQueryChange).toHaveBeenCalled();
    expect(handlers.onSearch).toHaveBeenCalledTimes(1);
  });

  it("selects result card and supports focusing linked layers", () => {
    const handlers = renderPanel({ collapsed: false });
    const resultsPanel = screen.getByTestId("kb-results");
    fireEvent.click(within(resultsPanel).getAllByText("港口分布示例")[1]);
    fireEvent.click(within(resultsPanel).getByText("定位关联图层"));
    expect(handlers.onSelectItem).toHaveBeenCalled();
    expect(handlers.onFocusLayer).toHaveBeenCalledWith("ports_layer");
  });

  it("opens editor and saves edited item", () => {
    const handlers = renderPanel({ collapsed: false });
    fireEvent.click(screen.getByText("展开编辑"));
    fireEvent.change(screen.getByPlaceholderText("输入条目标题"), {
      target: { value: "更新标题" }
    });
    fireEvent.click(screen.getByText("保存条目"));
    expect(handlers.onEditingItemChange).toHaveBeenCalled();
    expect(handlers.onSaveItem).toHaveBeenCalledTimes(1);
  });

  it("disables register button when no active layer", () => {
    renderPanel({ collapsed: false, activeLayerId: "", canRegister: false });
    expect(screen.getByTestId("kb-register-layer")).toBeDisabled();
  });

  it("marks missing linked layer as knowledge-only for classroom map", () => {
    renderPanel({ collapsed: false, availableLayerIds: [] });
    expect(screen.getByText("仅知识资料")).toBeDisabled();
  });
});
