import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { SideDrawer } from "../components/SideDrawer";

describe("SideDrawer", () => {
  it("renders chapter and unit driven templates in the units tab", () => {
    render(
      <SideDrawer
        open
        activeTab="units"
        templates={[
          {
            template_id: "generic_classroom_pack",
            title: "通用课堂包",
            description: "区域认知基础模板。",
            chapter_id: "general_classroom",
            chapter_title: "通用课堂",
            chapter_order: 10,
            unit_id: "regional_cognition",
            unit_title: "区域认知基础",
            unit_order: 10,
            template_order: 10
          }
        ]}
        layerState={null}
        outputs={[]}
        searchResults={[]}
        searchSummary=""
        statusSummary={{
          currentMode: "选择",
          searchScope: "当前视域",
          latest: "可在左侧单元页加载课堂模板。",
          activeBasemap: "高德标准",
          visibleLayers: 0,
          totalLayers: 0,
          enabledTemplates: 0
        }}
        onToggleOpen={vi.fn()}
        onChangeTab={vi.fn()}
        onToggleLayer={vi.fn()}
        onSelectLayer={vi.fn()}
        onFocusResult={vi.fn()}
        onRunTemplate={vi.fn()}
      />
    );

    expect(screen.getByText("通用课堂")).toBeInTheDocument();
    expect(screen.getByText("区域认知基础")).toBeInTheDocument();
    expect(screen.getByText("通用课堂包")).toBeInTheDocument();
  });

  it("renders layers, search results, and outputs across tabs", () => {
    const props = {
      open: true,
      activeTab: "layers" as const,
      templates: [
        {
          template_id: "population_distribution",
          title: "人口分布",
          description: "人口分布模板。",
          chapter_id: "population_topic",
          chapter_title: "人口专题",
          chapter_order: 20,
          unit_id: "population_pattern",
          unit_title: "人口空间格局",
          unit_order: 10,
          template_order: 20
        }
      ],
      layerState: {
        status: "success",
        active_layer_id: "layer_demo",
        view: { center: [104, 35], zoom: 4 },
        enabled_templates: ["population_distribution"],
        recent_actions: [],
        base_map: {
          id: "amap_vector",
          title: "高德标准",
          description: "",
          type: "stack",
          provider: "amap",
          layers: []
        },
        items: [
          {
            layer_id: "layer_demo",
            name: "人口分布",
            kind: "vector",
            source: "builtin",
            geometry_type: "Polygon",
            visible: true,
            opacity: 1,
            z_index: 10,
            style: {},
            data: {},
            metadata: {}
          }
        ]
      },
      outputs: [
        {
          artifact_id: "artifact_1",
          project_id: "project_1",
          job_id: "job_1",
          artifact_type: "map_snapshot",
          title: "课堂截图",
          path: "C:/tmp/demo.png",
          metadata: { public_url: "/files/demo.png" },
          created_at: "1"
        }
      ],
      searchResults: [
        {
          poi_id: "poi_1",
          name: "宁波港",
          address: "舟山港域",
          type: "港口",
          district: "浙江",
          city: "宁波",
          location: [121.8, 29.9] as [number, number]
        }
      ],
      searchSummary: "已检索到 1 条港口结果。",
      statusSummary: {
        currentMode: "选择",
        searchScope: "当前视域",
        latest: "已加载示例数据。",
        activeBasemap: "高德标准",
        visibleLayers: 1,
        totalLayers: 1,
        enabledTemplates: 1
      },
      onToggleOpen: vi.fn(),
      onChangeTab: vi.fn(),
      onToggleLayer: vi.fn(),
      onSelectLayer: vi.fn(),
      onFocusResult: vi.fn(),
      onRunTemplate: vi.fn()
    };

    const { rerender } = render(<SideDrawer {...props} />);
    expect(within(screen.getByTestId("drawer-layers")).getAllByText("人口分布").length).toBeGreaterThan(0);

    rerender(<SideDrawer {...props} activeTab="search" />);
    expect(screen.getByText("宁波港")).toBeInTheDocument();

    rerender(<SideDrawer {...props} activeTab="outputs" />);
    expect(screen.getByText("课堂截图")).toBeInTheDocument();
  });
});
