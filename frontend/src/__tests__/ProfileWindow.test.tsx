import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProfileWindow, type MeasureRecord, type ProfileWindowGeometry } from "../components/ProfileWindow";
import type { MapProfileResult } from "../types";

// jsdom 没有 PointerEvent：拖拽测试需要真实的指针坐标。
class JsdomPointerEvent extends MouseEvent {
  pointerId: number;
  constructor(type: string, init: MouseEventInit & { pointerId?: number } = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 1;
  }
}
if (typeof window.PointerEvent === "undefined") {
  (window as unknown as { PointerEvent: typeof JsdomPointerEvent }).PointerEvent = JsdomPointerEvent;
}

const previewMock = vi.fn();
vi.mock("../api", () => ({
  previewMapProfile: (...args: unknown[]) => previewMock(...args)
}));

const record: MeasureRecord = {
  id: "msr_1",
  name: "测线 1",
  coordinates: [[121.4, 31.2], [121.6, 31.25]],
  totalKm: 21.4,
  color: "#087cad"
};

const densitySources = [
  { id: "shanghai_worldpop_2020", name: "上海 2020 年人口网格（WorldPop ~100m 估计）" },
  { id: "layer_x", name: "行政区密度面" }
];

const populationResult: MapProfileResult = {
  kind: "population",
  source_id: "shanghai_worldpop_2020",
  source_name: "上海 2020 年人口网格（WorldPop ~100m 估计）",
  source_year: "2020",
  source_url: "https://hub.worldpop.org/geodata/summary?id=72922",
  unit: "人/km²",
  sampling: "本地裁剪栅格最近邻取值（WorldPop ~100m / 3 角秒）",
  resolution_m: 100,
  total_distance_km: 21.4,
  sample_spacing_m: 500,
  no_data_count: 2,
  samples: [
    { distance_km: 0, lon: 121.4, lat: 31.2, value: 15300 },
    { distance_km: 10.7, lon: 121.5, lat: 31.22, value: null },
    { distance_km: 21.4, lon: 121.6, lat: 31.25, value: 4200 }
  ],
  source_attribution: "WorldPop R2025A (CC BY 4.0) DOI:10.5258/SOTON/WP00839",
  source_caveats: ["alpha 产品（R2025A v1），仍可能更新。", "每像元估计人数换算为人/km²，非逐建筑实测。"],
  value_note: "原始每像元估计人数已按像元实际面积换算为人/km²。"
};

const terrainResult: MapProfileResult = {
  ...populationResult,
  kind: "terrain",
  source_id: "mapzen_terrain",
  source_name: "Mapzen terrain tiles",
  source_year: "",
  unit: "m",
  samples: [
    { distance_km: 0, lon: 121.4, lat: 31.2, value: 4 },
    { distance_km: 21.4, lon: 121.6, lat: 31.25, value: 6 }
  ]
};

const baseGeometry: ProfileWindowGeometry = { left: 96, top: 120, width: 560, height: 330 };

type MountProps = Partial<Parameters<typeof ProfileWindow>[0]>;

function mount(overrides: MountProps = {}) {
  const props: Parameters<typeof ProfileWindow>[0] = {
    projectId: "p1",
    windowId: "pw_1_population",
    record,
    kind: "population",
    densitySources,
    sourceId: "shanghai_worldpop_2020",
    geometry: baseGeometry,
    onGeometryChange: vi.fn(),
    onSourceChange: vi.fn(),
    onHover: vi.fn(),
    onClose: vi.fn(),
    ...overrides
  };
  const view = render(<ProfileWindow {...props} />);
  return { view, props };
}

describe("ProfileWindow（每线每图一窗，任务3）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(cleanup);

  it("auto-runs the population profile for its line on mount and shows the record name", async () => {
    previewMock.mockResolvedValue(populationResult);
    mount();
    await waitFor(() => expect(previewMock).toHaveBeenCalledWith("p1", {
      coordinates: record.coordinates,
      kind: "population",
      source_id: "shanghai_worldpop_2020"
    }));
    expect(await screen.findByText(/本地裁剪栅格最近邻取值/)).toBeVisible();
    const win = screen.getByTestId("profile-window-pw_1_population");
    expect(win).toHaveTextContent("测线 1");
    expect(win).toHaveTextContent("人口密度变化");
  });

  it("runs the terrain profile for the same line as a separate window", async () => {
    previewMock.mockResolvedValue(terrainResult);
    mount({ windowId: "pw_1_terrain", kind: "terrain", sourceId: "" });
    await waitFor(() => expect(previewMock).toHaveBeenCalledWith("p1", {
      coordinates: record.coordinates,
      kind: "terrain",
      source_id: "mapzen_terrain"
    }));
    expect(await screen.findByText(/Mapzen terrain tiles/)).toBeVisible();
    // 地形窗口不显示人口数据源选择
    expect(screen.queryByLabelText("测线 1人口密度数据源")).toBeNull();
  });

  it("re-fetches when the population source changes and reports the change", async () => {
    previewMock.mockResolvedValue(populationResult);
    const { view } = mount();
    await screen.findByText(/本地裁剪栅格最近邻取值/);
    fireEvent.change(screen.getByLabelText("测线 1人口密度数据源"), { target: { value: "layer_x" } });
    // 父组件（App）收到 onSourceChange 后回写 sourceId 触发重取数
    view.rerender(<ProfileWindow
      projectId="p1" windowId="pw_1_population" record={record} kind="population"
      densitySources={densitySources} sourceId="layer_x"
      geometry={baseGeometry}
      onGeometryChange={vi.fn()} onSourceChange={vi.fn()} onHover={vi.fn()} onClose={vi.fn()}
    />);
    await waitFor(() => expect(previewMock).toHaveBeenLastCalledWith("p1", {
      coordinates: record.coordinates,
      kind: "population",
      source_id: "layer_x"
    }));
  });

  it("closes only itself via the header button", () => {
    const { props } = mount();
    fireEvent.click(screen.getByTestId("profile-window-close-pw_1_population"));
    expect(props.onClose).toHaveBeenCalledWith("pw_1_population");
  });

  it("emits geometry changes when dragged by the header and resized from the corner handle", () => {
    const { props } = mount();
    const win = screen.getByTestId("profile-window-pw_1_population");
    const header = win.querySelector(".profile-window-head") as HTMLElement;
    fireEvent.pointerDown(header, { pointerId: 1, clientX: 200, clientY: 200, button: 0 });
    fireEvent.pointerMove(header, { pointerId: 1, clientX: 320, clientY: 160 });
    fireEvent.pointerUp(header, { pointerId: 1 });
    expect(props.onGeometryChange).toHaveBeenCalledWith("pw_1_population", {
      left: baseGeometry.left + 120,
      top: baseGeometry.top - 40,
      width: baseGeometry.width,
      height: baseGeometry.height
    });
    const handle = screen.getByTestId("profile-window-resize-pw_1_population");
    fireEvent.pointerDown(handle, { pointerId: 2, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(handle, { pointerId: 2, clientX: 220, clientY: 140 });
    fireEvent.pointerUp(handle, { pointerId: 2 });
    expect(props.onGeometryChange).toHaveBeenLastCalledWith("pw_1_population", {
      left: baseGeometry.left,
      top: baseGeometry.top,
      width: baseGeometry.width + 120,
      height: baseGeometry.height + 40
    });
  });

  it("stays out of view when hidden and still closes its own window", () => {
    const onClose = vi.fn();
    const { view } = mount({ hidden: true, onClose });
    expect(screen.getByTestId("profile-window-pw_1_population").className).toContain("is-hidden");
    view.rerender(<ProfileWindow
      projectId="p1" windowId="pw_1_population" record={record} kind="population"
      densitySources={densitySources} sourceId="shanghai_worldpop_2020"
      geometry={baseGeometry} hidden={false}
      onGeometryChange={vi.fn()} onSourceChange={vi.fn()} onHover={vi.fn()} onClose={onClose}
    />);
    fireEvent.click(screen.getByTestId("profile-window-close-pw_1_population"));
    expect(onClose).toHaveBeenCalledWith("pw_1_population");
  });

  it("keeps its header inside the viewport after a huge drag", () => {
    const { props } = mount();
    const win = screen.getByTestId("profile-window-pw_1_population");
    const header = win.querySelector(".profile-window-head") as HTMLElement;
    fireEvent.pointerDown(header, { pointerId: 1, clientX: 200, clientY: 200 });
    fireEvent.pointerMove(header, { pointerId: 1, clientX: 3000, clientY: 3000 });
    fireEvent.pointerUp(header, { pointerId: 1 });
    const calls = props.onGeometryChange.mock.calls as Array<[string, ProfileWindowGeometry]>;
    const last = calls[calls.length - 1][1];
    expect(last.left + last.width).toBeLessThanOrEqual(window.innerWidth - 8);
    expect(last.top + last.height).toBeLessThanOrEqual(window.innerHeight - 8);
  });

  it("shows conversion note, alpha caveat and attribution in the footnote", async () => {
    previewMock.mockResolvedValue(populationResult);
    mount();
    const footnote = await screen.findByText(/换算为人\/km²，非逐建筑实测/);
    expect(footnote).toHaveTextContent("alpha 产品（R2025A v1），仍可能更新");
    expect(footnote).toHaveTextContent("DOI:10.5258/SOTON/WP00839");
    expect(footnote).toHaveTextContent("无数据 2 点，不作推断");
  });
});
