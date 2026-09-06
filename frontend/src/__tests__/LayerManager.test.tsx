import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LayerManager } from "../components/LayerManager";
import type { DatasetCatalogItem, LayerRecord } from "../types";

function makeLayer(overrides: Partial<LayerRecord> = {}): LayerRecord {
  return {
    layer_id: "layer_a",
    name: "人口密度图层",
    kind: "vector",
    source: "one_map_catalog",
    geometry_type: "Polygon",
    visible: true,
    opacity: 1,
    z_index: 3,
    style: {},
    metadata: {},
    data_rev: 0,
    ...overrides
  } as LayerRecord;
}

function makeDataset(overrides: Partial<DatasetCatalogItem> = {}): DatasetCatalogItem {
  return {
    id: "world_population_by_country",
    name: "世界人口（分国家）",
    category: "population",
    format: "geojson",
    status: "ready",
    ...overrides
  } as DatasetCatalogItem;
}

function renderManager(overrides: Partial<Parameters<typeof LayerManager>[0]> = {}) {
  const props = {
    open: true,
    onClose: vi.fn(),
    layers: [makeLayer()],
    busy: false,
    onToggleLayer: vi.fn(),
    onFocusLayer: vi.fn(),
    onDeleteLayer: vi.fn(),
    datasetCatalogItems: [makeDataset()],
    onLoadDataset: vi.fn(),
    ...overrides
  };
  render(<LayerManager {...props} />);
  return props;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("LayerManager", () => {
  it("lists layers with visibility, focus and delete actions", () => {
    const props = renderManager();

    expect(screen.getByTestId("layer-manager")).toBeTruthy();
    expect(screen.getByText("人口密度图层")).toBeTruthy();
    expect(screen.getByText(/可见 1 \/ 共 1/)).toBeTruthy();

    fireEvent.click(screen.getByLabelText("隐藏 人口密度图层"));
    expect(props.onToggleLayer).toHaveBeenCalledWith("layer_a", false);

    fireEvent.click(screen.getByText("人口密度图层"));
    expect(props.onFocusLayer).toHaveBeenCalledWith("layer_a");

    window.confirm = vi.fn(() => true);
    fireEvent.click(screen.getByLabelText("删除 人口密度图层"));
    expect(props.onDeleteLayer).toHaveBeenCalledWith("layer_a");
  });

  it("skips deletion when confirm is dismissed", () => {
    const props = renderManager();
    window.confirm = vi.fn(() => false);
    fireEvent.click(screen.getByLabelText("删除 人口密度图层"));
    expect(props.onDeleteLayer).not.toHaveBeenCalled();
  });

  it("offers loadable catalog datasets for adding layers", () => {
    const props = renderManager({
      datasetCatalogItems: [
        makeDataset(),
        makeDataset({ id: "csv_plain", name: "无几何表格", format: "csv" })
      ]
    });

    fireEvent.click(screen.getByTestId("layer-manager-add-toggle"));
    const list = screen.getByTestId("layer-manager-add-list");
    expect(list.textContent).toContain("世界人口（分国家）");
    expect(list.textContent).not.toContain("无几何表格");

    fireEvent.click(screen.getByText("世界人口（分国家）"));
    expect(props.onLoadDataset).toHaveBeenCalledWith(props.datasetCatalogItems[0]);
  });
});
