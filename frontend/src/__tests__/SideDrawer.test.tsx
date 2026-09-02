import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { SideDrawer } from "../components/SideDrawer";

const baseProps = {
  open: true,
  layerState: null,
  searchResults: [],
  searchSummary: "",
  oneMapStats: null,
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
  onOpenLessonWorkflow: vi.fn()
};

afterEach(() => {
  vi.restoreAllMocks();
});

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

  it("exposes the primary tabs", () => {
    const { container } = render(<SideDrawer {...baseProps} activeTab="resource-search" />);
    const tablist = container.querySelector(".drawer-tabs");
    expect(tablist).not.toBeNull();
    const scoped = within(tablist as HTMLElement);

    expect(scoped.getByRole("tab", { name: /资料搜索/ })).toBeInTheDocument();
    expect(scoped.getByRole("tab", { name: /图片库/ })).toBeInTheDocument();
    expect(scoped.getByRole("tab", { name: /图层/ })).toBeInTheDocument();
    expect(scoped.getByRole("tab", { name: /检索/ })).toBeInTheDocument();
    expect(scoped.getByRole("tab", { name: /区域统计/ })).toBeInTheDocument();
    expect(scoped.queryByRole("tab", { name: /^资料$/ })).toBeNull();
    expect(scoped.queryByRole("tab", { name: /产物/ })).toBeNull();
    expect(scoped.queryByText("当前状态")).toBeNull();
  });

  it("shows only project images and supports button and upload attachment paths", () => {
    const onAttachImage = vi.fn();
    const onUploadImage = vi.fn();
    render(
      <SideDrawer
        {...baseProps}
        activeTab="images"
        outputs={[
          {
            artifact_id: "snapshot_1",
            project_id: "project_1",
            job_id: "job_1",
            artifact_type: "map_snapshot",
            title: "长江流域截图",
            path: "outputs/map.png",
            metadata: { public_url: "/files/map.png", mime_type: "image/png" },
            created_at: "2026-08-11T09:00:00+08:00"
          },
          {
            artifact_id: "report_1",
            project_id: "project_1",
            job_id: "job_2",
            artifact_type: "report",
            title: "不应展示的报告",
            path: "outputs/report.md",
            metadata: {},
            created_at: "2026-08-11T09:00:00+08:00"
          }
        ]}
        onAttachImage={onAttachImage}
        onUploadImage={onUploadImage}
      />
    );

    expect(screen.getByText("长江流域截图")).toBeInTheDocument();
    expect(screen.queryByText("不应展示的报告")).toBeNull();
    fireEvent.click(screen.getByText("加入助教"));
    expect(onAttachImage).toHaveBeenCalledWith(expect.objectContaining({ artifact_id: "snapshot_1" }));

    const file = new File(["image"], "terrain.jpg", { type: "image/jpeg" });
    const input = document.querySelector(".image-library-upload input") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    expect(onUploadImage).toHaveBeenCalledWith(file);
  });

  it("generates a MiniMax image and shows generated artifacts", () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const onGenerateImage = vi.fn();
    const { container } = render(
      <SideDrawer
        {...baseProps}
        activeTab="images"
        imageGenerationConfigured
        imageGenerationModel="image-01"
        onGenerateImage={onGenerateImage}
        outputs={[
          {
            artifact_id: "generated_1",
            project_id: "project_1",
            job_id: "job_1",
            artifact_type: "generated_image",
            title: "AI生成示意图",
            path: "outputs/generated.png",
            metadata: { public_url: "/files/generated.png", mime_type: "image/png", ai_generated: true },
            created_at: "2026-08-18T09:00:00+08:00"
          }
        ]}
      />
    );
    const view = within(container);

    expect(view.getAllByText("AI生成示意图").length).toBeGreaterThan(0);
    expect(view.getByText(/生成结果会标记/)).toBeInTheDocument();
    fireEvent.change(view.getByLabelText("MiniMax AI 生成"), { target: { value: "蓝绿色水循环教学示意图" } });
    fireEvent.change(view.getByLabelText("图片比例"), { target: { value: "4:3" } });
    fireEvent.click(view.getByRole("button", { name: "生成并保存" }));

    expect(onGenerateImage).toHaveBeenCalledWith({
      prompt: "蓝绿色水循环教学示意图",
      model: "image-01",
      aspectRatio: "4:3"
    });
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("does not call the paid image endpoint when the teacher cancels confirmation", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const onGenerateImage = vi.fn();
    const { container } = render(<SideDrawer {...baseProps} activeTab="images" imageGenerationConfigured onGenerateImage={onGenerateImage} />);
    const view = within(container);
    fireEvent.change(view.getByLabelText("MiniMax AI 生成"), { target: { value: "季风环流图" } });
    fireEvent.click(view.getByRole("button", { name: "生成并保存" }));
    expect(onGenerateImage).not.toHaveBeenCalled();
  });

  it("prevents duplicate paid generation submissions while a request is pending", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let resolveGeneration: (() => void) | undefined;
    const onGenerateImage = vi.fn(
      () => new Promise<void>((resolve) => {
        resolveGeneration = resolve;
      })
    );
    const { container } = render(
      <SideDrawer
        {...baseProps}
        activeTab="images"
        imageGenerationConfigured
        onGenerateImage={onGenerateImage}
      />
    );
    const view = within(container);
    const prompt = view.getByLabelText("MiniMax AI 生成");
    const form = container.querySelector(".image-generation-form") as HTMLFormElement;
    fireEvent.change(prompt, { target: { value: "季风环流教学示意图" } });

    fireEvent.submit(form);
    fireEvent.submit(form);

    expect(onGenerateImage).toHaveBeenCalledTimes(1);
    resolveGeneration?.();
    await waitFor(() => expect(prompt).toHaveValue(""));
  });

  it("renders one-map area statistics", () => {
    render(
      <SideDrawer
        {...baseProps}
        activeTab="stats"
        oneMapStats={{
          status: "success",
          summary: "已统计 1 个一张图图层，命中 2 个要素。",
          geometry_used: true,
          totals: { matched_count: 2, total_population: 1000, total_area: 10, density: 100 },
          layers: [
            {
              layer_id: "one_map_population",
              name: "人口密度",
              catalog_id: "china_province_population_density",
              feature_count: 31,
              matched_count: 2,
              total_population: 1000,
              total_area: 10,
              density: 100,
              rows: [
                { name: "上海市", region_code: "310000", population: 500, area: 5, density: 100 },
                { name: "江苏省", region_code: "320000", population: 500, area: 5, density: 100 }
              ],
              method: "representative_point_within_selection"
            }
          ]
        }}
      />
    );

    expect(screen.getByTestId("drawer-stats")).toBeInTheDocument();
    expect(screen.getByText("人口密度")).toBeInTheDocument();
    expect(screen.getByText(/上海市/)).toBeInTheDocument();
  });
});
