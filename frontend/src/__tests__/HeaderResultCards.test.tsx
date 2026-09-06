import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SearchResultsCard, StatsResultsCard } from "../components/HeaderResultCards";
import type { DatasetStatsResponse, PoiSearchItem } from "../types";

const poiItem: PoiSearchItem = {
  poi_id: "poi_1",
  name: "洋山深水港",
  address: "上海市浦东新区",
  type: "港口",
  district: "浦东新区",
  city: "上海市",
  location: [121.9, 30.6]
} as PoiSearchItem;

const stats: DatasetStatsResponse = {
  summary: "命中 2 个图层，覆盖 3 个区县。",
  geometry_used: { type: "Polygon" },
  layers: [
    {
      layer_id: "layer_pop",
      name: "人口分布",
      matched_count: 3,
      feature_count: 10,
      total_population: 1200,
      total_area: 6340.5,
      density: 0.19,
      method: "area_weighted_intersection",
      rows: [{ name: "浦东新区", coverage_ratio: 0.42 }]
    }
  ],
  totals: { matched_count: 3, total_population: 1200, total_area: 6340.5, density: 0.19 }
} as unknown as DatasetStatsResponse;

afterEach(() => {
  cleanup();
});

describe("SearchResultsCard", () => {
  it("stays hidden when closed and lists results when open", () => {
    const onClose = vi.fn();
    const onFocusResult = vi.fn();
    const { rerender } = render(
      <SearchResultsCard open={false} summary="完成" results={[poiItem]} onClose={onClose} onFocusResult={onFocusResult} />
    );
    expect(screen.queryByTestId("search-results-card")).toBeNull();

    rerender(
      <SearchResultsCard open summary="完成" results={[poiItem]} onClose={onClose} onFocusResult={onFocusResult} />
    );
    expect(screen.getByTestId("search-results-card")).toBeTruthy();
    expect(screen.getByText("洋山深水港")).toBeTruthy();
    expect(screen.getByText("完成")).toBeTruthy();

    fireEvent.click(screen.getByText("洋山深水港"));
    expect(onFocusResult).toHaveBeenCalledWith(poiItem);

    fireEvent.click(screen.getByLabelText("关闭检索结果"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("StatsResultsCard", () => {
  it("renders totals and per-layer statistics", () => {
    const onClose = vi.fn();
    render(<StatsResultsCard open stats={stats} onClose={onClose} />);

    expect(screen.getByTestId("stats-results-card")).toBeTruthy();
    expect(screen.getByText("一张图区域统计")).toBeTruthy();
    expect(screen.getByText("人口分布")).toBeTruthy();
    expect(screen.getByText(/面积比例估算/)).toBeTruthy();

    fireEvent.click(screen.getByLabelText("关闭统计结果"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renders an empty state when nothing matched", () => {
    render(<StatsResultsCard open stats={{ ...stats, layers: [] }} onClose={vi.fn()} />);
    expect(screen.getByText("本次统计没有命中图层。")).toBeTruthy();
  });
});
