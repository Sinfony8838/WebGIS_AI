import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { VisualQueryPopup } from "../components/VisualQueryPopup";
import type { LayerRecord } from "../types";

function makeLayer(overrides: Partial<LayerRecord> = {}): LayerRecord {
  const items = Array.from({ length: 20 }, (_, index) => {
    const rank = index + 1;
    return {
      rank,
      name:
        [
          "重庆市",
          "上海市",
          "北京市",
          "成都市",
          "广州市",
          "深圳市",
          "天津市",
          "西安市",
          "苏州市",
          "郑州市",
          "武汉市",
          "杭州市",
          "保定市",
          "石家庄市",
          "临沂市",
          "东莞市",
          "青岛市",
          "长沙市",
          "哈尔滨市",
          "南阳市",
        ][index] ?? `城市${rank}`,
      province: "测试省",
      value: 32_000_000 - rank * 1_000_000,
      unit: "人",
      share: 1 - rank * 0.04,
      fill_color: "#dc2626",
    };
  });
  const features = items.map((item) => ({
    type: "Feature",
    properties: {
      name: item.name,
      province: item.province,
      rank: item.rank,
      value: item.value,
      unit: item.unit,
      __fillColor: item.fill_color,
    },
    geometry: {
      type: "MultiPolygon",
      coordinates: [
        [
          [
            [110, 30],
            [115, 30],
            [115, 35],
            [110, 35],
            [110, 30],
          ],
        ],
      ],
    },
  }));
  return {
    layer_id: "visual_query_prefecture_population_2020_topd20",
    name: "2020年地级市人口Top-20",
    kind: "vector",
    source: "generated",
    geometry_type: "MultiPolygon",
    visible: true,
    opacity: 1,
    z_index: 80,
    style: { labelField: "name" },
    data: { type: "FeatureCollection", features },
    metadata: {
      year: 2020,
      metric: "population",
      operation: "top",
      limit: 20,
      order: "desc",
      geo_level: "prefecture",
      dataset: "prefecture_population",
      feature_count: 20,
      unit: "人",
      visualization: {
        type: "bar",
        x: "name",
        y: "value",
        unit: "人",
        title: "2020 年地级市常住人口 Top-20",
        items,
        palette: items.map((item) => item.fill_color ?? "#dc2626"),
        maximum: items[0]?.value ?? 0,
      },
    },
    ...overrides,
  };
}

describe("VisualQueryPopup", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders the title and 20 ranked bars", () => {
    const layer = makeLayer();
    const onClose = vi.fn();
    const onFocus = vi.fn();
    render(
      <VisualQueryPopup
        layer={layer}
        onClose={onClose}
        onFocusItem={onFocus}
      />
    );

    expect(screen.getByTestId("visual-query-title").textContent).toContain("2020");
    const bars = screen.getAllByTestId(/^visual-query-bar-\d+$/);
    expect(bars).toHaveLength(20);
    expect(screen.getByTestId("visual-query-value-1").textContent).toContain("万人");
  });

  it("formats population as 万人", () => {
    const layer = makeLayer();
    render(
      <VisualQueryPopup
        layer={layer}
        onClose={vi.fn()}
        onFocusItem={vi.fn()}
      />
    );

    // 1st item has 31,000,000 → 3100 万人
    expect(screen.getByTestId("visual-query-value-1").textContent).toBe("3100 万人");
  });

  it("forwards clicks on a bar to the focus callback", () => {
    const layer = makeLayer();
    const onFocus = vi.fn();
    render(
      <VisualQueryPopup
        layer={layer}
        onClose={vi.fn()}
        onFocusItem={onFocus}
      />
    );

    const firstBar = screen.getByTestId("visual-query-bar-1");
    const button = within(firstBar).getByRole("button");
    fireEvent.click(button);
    expect(onFocus).toHaveBeenCalledTimes(1);
    const [item, layerArg] = onFocus.mock.calls[0];
    expect(item.rank).toBe(1);
    expect(item.name).toBeTruthy();
    expect(layerArg.layer_id).toBe(layer.layer_id);
  });

  it("hides when the close button is clicked", () => {
    const layer = makeLayer();
    const onClose = vi.fn();
    render(
      <VisualQueryPopup
        layer={layer}
        onClose={onClose}
        onFocusItem={vi.fn()}
      />
    );

    fireEvent.click(screen.getByTestId("visual-query-close"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("visual-query-popup")).toBeNull();
  });

  it("returns nothing when the layer is null", () => {
    const { container } = render(
      <VisualQueryPopup
        layer={null}
        onClose={vi.fn()}
        onFocusItem={vi.fn()}
      />
    );
    expect(container.firstChild).toBeNull();
  });
});
