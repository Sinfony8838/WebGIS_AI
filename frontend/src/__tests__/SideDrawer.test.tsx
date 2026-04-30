import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { SideDrawer } from "../components/SideDrawer";
import type { KnowledgeTopicSummary } from "../types";

const topics: KnowledgeTopicSummary[] = [
  {
    topic: "population",
    title: "Population",
    item_count: 3,
    renderable_count: 1,
    stored_only_count: 1,
    knowledge_only_count: 1,
    sample_titles: ["Population map"]
  }
];

const baseProps = {
  open: true,
  topics,
  layerState: null,
  outputs: [],
  searchResults: [],
  searchSummary: "",
  resourceQuery: "",
  resourceScope: "all" as const,
  resourceLoading: false,
  resourceResults: [],
  statusSummary: {
    currentMode: "browse",
    searchScope: "view",
    latest: "ready",
    activeBasemap: "AMap",
    visibleLayers: 0,
    totalLayers: 0,
    enabledTemplates: 0
  },
  onToggleOpen: vi.fn(),
  onChangeTab: vi.fn(),
  onToggleLayer: vi.fn(),
  onSelectLayer: vi.fn(),
  onFocusResult: vi.fn(),
  onOpenKnowledgeTopic: vi.fn(),
  onResourceQueryChange: vi.fn(),
  onResourceScopeChange: vi.fn(),
  onOpenResourceResult: vi.fn(),
  onImportResourceResult: vi.fn()
};

describe("SideDrawer", () => {
  it("renders knowledge topics in the resources tab", () => {
    render(<SideDrawer {...baseProps} activeTab="resources" />);

    expect(screen.getByText("Population")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Population"));
    expect(baseProps.onOpenKnowledgeTopic).toHaveBeenCalledWith("population");
  });

  it("renders layers, search results, and outputs across tabs", () => {
    const props = {
      ...baseProps,
      layerState: {
        status: "success",
        active_layer_id: "layer_demo",
        view: { center: [104, 35] as [number, number], zoom: 4 },
        enabled_templates: [],
        recent_actions: [],
        base_map: {
          id: "amap_vector",
          title: "AMap",
          description: "",
          type: "stack",
          provider: "amap",
          layers: []
        },
        items: [
          {
            layer_id: "layer_demo",
            name: "Climate layer",
            kind: "raster",
            source: "upload",
            geometry_type: "Raster",
            visible: true,
            opacity: 1,
            z_index: 10,
            style: {},
            data: {},
            metadata: { status: "renderable_layer" }
          }
        ]
      },
      outputs: [
        {
          artifact_id: "artifact_1",
          project_id: "project_1",
          job_id: "job_1",
          artifact_type: "map_snapshot",
          title: "Snapshot",
          path: "C:/tmp/demo.png",
          metadata: { public_url: "/files/demo.png" },
          created_at: "1"
        }
      ],
      searchResults: [
        {
          poi_id: "poi_1",
          name: "Ningbo Port",
          address: "Zhoushan",
          type: "port",
          district: "Zhejiang",
          city: "Ningbo",
          location: [121.8, 29.9] as [number, number]
        }
      ],
      searchSummary: "1 result"
    };

    const { rerender } = render(<SideDrawer {...props} activeTab="layers" />);
    expect(within(screen.getByTestId("drawer-layers")).getAllByText("Climate layer").length).toBeGreaterThan(0);

    rerender(<SideDrawer {...props} activeTab="search" />);
    expect(screen.getByText("Ningbo Port")).toBeInTheDocument();

    rerender(<SideDrawer {...props} activeTab="outputs" />);
    expect(screen.getByText("Snapshot")).toBeInTheDocument();
  });

  it("renders live resource search results and import action", () => {
    const result = {
      id: "kb:demo",
      title: "Hu line",
      source: "knowledge_base",
      type: "knowledge",
      summary: "population geography boundary",
      url: "",
      thumbnail_url: "",
      citations: [],
      confidence: 0.9
    };
    render(<SideDrawer {...baseProps} activeTab="resource-search" resourceQuery="Hu line" resourceResults={[result]} />);

    expect(screen.getByTestId("live-resource-search")).toBeInTheDocument();
    expect(screen.getByText("Hu line")).toBeInTheDocument();
    fireEvent.click(screen.getByText("导入本课时"));
    expect(baseProps.onImportResourceResult).toHaveBeenCalledWith(result);
  });
});
