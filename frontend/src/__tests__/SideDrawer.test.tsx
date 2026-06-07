import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { SideDrawer } from "../components/SideDrawer";

const baseProps = {
  open: true,
  layerState: null,
  searchResults: [],
  searchSummary: "",
  resourceQuery: "",
  resourceScope: "all" as const,
  resourceLoading: false,
  resourceResults: [],
  onToggleOpen: vi.fn(),
  onChangeTab: vi.fn(),
  onToggleLayer: vi.fn(),
  onSelectLayer: vi.fn(),
  onFocusResult: vi.fn(),
  onResourceQueryChange: vi.fn(),
  onResourceScopeChange: vi.fn(),
  onOpenResourceResult: vi.fn(),
  onImportResourceResult: vi.fn(),
  onOpenTimeline: vi.fn()
};

describe("SideDrawer", () => {
  it("renders layers and search results across tabs", () => {
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
    render(
      <SideDrawer
        {...baseProps}
        activeTab="resource-search"
        resourceQuery="Hu line"
        resourceResults={[result]}
      />
    );

    expect(screen.getByTestId("live-resource-search")).toBeInTheDocument();
    expect(screen.getByText("Hu line")).toBeInTheDocument();
    fireEvent.click(screen.getByText("导入本课时"));
    expect(baseProps.onImportResourceResult).toHaveBeenCalledWith(result);
  });

  it("exposes the three primary tabs", () => {
    const { container } = render(<SideDrawer {...baseProps} activeTab="resource-search" />);
    const tablist = container.querySelector(".drawer-tabs");
    expect(tablist).not.toBeNull();
    const scoped = within(tablist as HTMLElement);

    expect(scoped.getByRole("tab", { name: /资料搜索/ })).toBeInTheDocument();
    expect(scoped.getByRole("tab", { name: /图层/ })).toBeInTheDocument();
    expect(scoped.getByRole("tab", { name: /检索/ })).toBeInTheDocument();
    expect(scoped.queryByRole("tab", { name: /^资料$/ })).toBeNull();
    expect(scoped.queryByRole("tab", { name: /产物/ })).toBeNull();
    expect(scoped.queryByText("当前状态")).toBeNull();
  });
});
