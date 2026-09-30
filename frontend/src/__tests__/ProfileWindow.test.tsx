import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProfileWindow, type MeasureRecord } from "../components/ProfileWindow";
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

const result: MapProfileResult = {
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

describe("ProfileWindow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(cleanup);

  it("runs a population profile for its own line and shows the record name", async () => {
    previewMock.mockResolvedValue(result);
    const onHover = vi.fn();
    render(<ProfileWindow projectId="p1" record={record} densitySources={densitySources} onHover={onHover} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "人口密度变化" }));
    await waitFor(() => expect(previewMock).toHaveBeenCalledWith("p1", {
      coordinates: record.coordinates,
      kind: "population",
      source_id: "shanghai_worldpop_2020"
    }));
    expect(await screen.findByText(/本地裁剪栅格最近邻取值/)).toBeVisible();
    expect(screen.getByTestId("profile-window-msr_1")).toHaveTextContent("测线 1");
  });

  it("shows conversion note, alpha caveat and attribution in the footnote", async () => {
    previewMock.mockResolvedValue(result);
    render(<ProfileWindow projectId="p1" record={record} densitySources={densitySources} onHover={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "人口密度变化" }));
    const footnote = await screen.findByText(/换算为人\/km²，非逐建筑实测/);
    expect(footnote).toHaveTextContent("alpha 产品（R2025A v1），仍可能更新");
    expect(footnote).toHaveTextContent("DOI:10.5258/SOTON/WP00839");
    expect(footnote).toHaveTextContent("无数据 2 点，不作推断");
  });

  it("closes its own line via the header button", () => {
    const onClose = vi.fn();
    render(<ProfileWindow projectId="p1" record={record} densitySources={densitySources} onHover={vi.fn()} onClose={onClose} />);
    fireEvent.click(screen.getByTestId("profile-window-close-msr_1"));
    expect(onClose).toHaveBeenCalledWith("msr_1");
  });

  it("drags by the header and resizes from the corner handle", () => {
    render(<ProfileWindow projectId="p1" record={record} densitySources={densitySources} onHover={vi.fn()} onClose={vi.fn()} />);
    const win = screen.getByTestId("profile-window-msr_1");
    const before = win.style.left;
    const header = win.querySelector(".profile-window-head") as HTMLElement;
    fireEvent.pointerDown(header, { pointerId: 1, clientX: 200, clientY: 200, button: 0 });
    fireEvent.pointerMove(header, { pointerId: 1, clientX: 320, clientY: 160 });
    fireEvent.pointerUp(header, { pointerId: 1 });
    expect(parseInt(win.style.left, 10)).toBe(parseInt(before, 10) + 120);
    const handle = screen.getByTestId("profile-window-resize-msr_1");
    const widthBefore = parseInt(win.style.width, 10);
    fireEvent.pointerDown(handle, { pointerId: 2, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(handle, { pointerId: 2, clientX: 220, clientY: 140 });
    fireEvent.pointerUp(handle, { pointerId: 2 });
    expect(parseInt(win.style.width, 10)).toBe(widthBefore + 120);
  });

  it("stays out of view when hidden and clears hover on close", () => {
    const onHover = vi.fn();
    const onClose = vi.fn();
    const { rerender } = render(<ProfileWindow projectId="p1" record={record} densitySources={densitySources} hidden onHover={onHover} onClose={onClose} />);
    expect(screen.getByTestId("profile-window-msr_1").className).toContain("is-hidden");
    rerender(<ProfileWindow projectId="p1" record={record} densitySources={densitySources} hidden={false} onHover={onHover} onClose={onClose} />);
    fireEvent.click(screen.getByTestId("profile-window-close-msr_1"));
    expect(onClose).toHaveBeenCalledWith("msr_1");
  });

  it("keeps its full header and close button inside the viewport after dragging", () => {
    render(<ProfileWindow projectId="p1" record={record} densitySources={densitySources} onHover={vi.fn()} onClose={vi.fn()} />);
    const win = screen.getByTestId("profile-window-msr_1");
    const header = win.querySelector(".profile-window-head") as HTMLElement;
    fireEvent.pointerDown(header, { pointerId: 1, clientX: 200, clientY: 200 });
    fireEvent.pointerMove(header, { pointerId: 1, clientX: 3000, clientY: 3000 });
    fireEvent.pointerUp(header, { pointerId: 1 });
    expect(parseFloat(win.style.left) + parseFloat(win.style.width)).toBeLessThanOrEqual(window.innerWidth - 8);
    expect(parseFloat(win.style.top) + parseFloat(win.style.height)).toBeLessThanOrEqual(window.innerHeight - 8);
  });
});
