import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { LayerRecord } from "../types";
import { MapEvidenceLegend } from "../components/MapEvidenceLegend";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const props = { basemapId: "nasa_nightlights_2016", layers: [], globe: false, themeIds: [], showFit: false, onShowFit: vi.fn() };
describe("MapEvidenceLegend", () => {
  it("lets a narrow classroom open and close readable source details", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true })));
    render(<MapEvidenceLegend {...props} />);
    const toggle = screen.getByRole("button", { name: "图例与数据" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: /NASA Black Marble/ })).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: /NASA Black Marble/ })).toBeVisible();
    fireEvent.click(toggle);
    expect(screen.queryByRole("link", { name: /NASA Black Marble/ })).not.toBeInTheDocument();
  });
  it("keeps the desktop legend expanded and hides it when no thematic layer is visible", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })));
    const { rerender } = render(<MapEvidenceLegend {...props} />);
    expect(screen.getByRole("button", { name: "图例与数据" })).toHaveAttribute("aria-expanded", "true");
    rerender(<MapEvidenceLegend {...props} basemapId="amap_light" />);
    expect(screen.queryByRole("button", { name: "图例与数据" })).not.toBeInTheDocument();
  });
});


describe("precipitation comparison", () => {
  const line = { layer_id: "generated_hu_line", visible: true, metadata: {} } as LayerRecord;
  const precipitation = { layer_id: "one_map_china_precipitation_400mm", visible: true, metadata: { catalog_id: "china_precipitation_400mm" } } as LayerRecord;
  it("does not reveal the comparison during the student's first drawing or in 3D", () => {
    const onTogglePrecipitation = vi.fn();
    const { rerender } = render(<MapEvidenceLegend {...props} basemapId="amap_light" layers={[]} onTogglePrecipitation={onTogglePrecipitation} />);
    expect(screen.queryByRole("checkbox", { name: /400毫米/ })).not.toBeInTheDocument();
    rerender(<MapEvidenceLegend {...props} layers={[line]} globe themeIds={["hu_line"]} onTogglePrecipitation={onTogglePrecipitation} />);
    expect(screen.queryByRole("checkbox", { name: /400毫米/ })).not.toBeInTheDocument();
  });
  it("waits for the authoritative layer before checking the comparison and supports removal", async () => {
    let finish!: () => void;
    const onTogglePrecipitation = vi.fn(() => new Promise<void>(resolve => { finish = resolve; }));
    const { rerender } = render(<MapEvidenceLegend {...props} basemapId="amap_light" layers={[line]} onTogglePrecipitation={onTogglePrecipitation} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /400毫米/ }));
    expect(onTogglePrecipitation).toHaveBeenCalledWith(true);
    expect(screen.getByRole("checkbox", { name: /400毫米/ })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /400毫米/ })).not.toBeChecked();
    await act(async () => { finish(); });
    rerender(<MapEvidenceLegend {...props} basemapId="amap_light" layers={[line, precipitation]} onTogglePrecipitation={onTogglePrecipitation} />);
    expect(screen.getByRole("checkbox", { name: /400毫米/ })).toBeChecked();
    expect(screen.getByText(/1991—2020 气候平均/)).toBeVisible();
    fireEvent.click(screen.getByText("降水来源与读图范围"));
    expect(screen.getByRole("link", { name: /DWD \/ GPCC V2025/ })).toHaveAttribute("href", expect.stringContaining("opendata.dwd.de"));
    fireEvent.click(screen.getByRole("checkbox", { name: /400毫米/ }));
    expect(onTogglePrecipitation).toHaveBeenLastCalledWith(false);
    await act(async () => { finish(); });
  });
  it("honors map write locks", () => {
    render(<MapEvidenceLegend {...props} basemapId="amap_light" layers={[line]} busy onTogglePrecipitation={vi.fn()} />);
    expect(screen.getByRole("checkbox", { name: /400毫米/ })).toBeDisabled();
  });
});

it("shows the census year, percentage scale and archived source for the age map", () => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })));
  const layer = { layer_id: "age", visible: true, metadata: { catalog_id: "shanghai_age_60_plus_2020" } } as LayerRecord;
  render(<MapEvidenceLegend {...props} basemapId="amap_light" layers={[layer]} />);
  expect(screen.getByText("上海 · 60岁及以上人口占比")).toBeVisible();
  expect(screen.getByText("≥35%")).toBeVisible();
  expect(screen.getByText(/2020 七普/)).toBeVisible();
  fireEvent.click(screen.getByText("年龄数据来源与口径"));
  expect(screen.getByRole("link", { name: /七普各区年龄构成/ })).toHaveAttribute("href", "https://tjj.sh.gov.cn/tjnj/2025tjnj/C0212.htm");
  expect(screen.getByText(/区级比例不能确定街镇/)).toBeVisible();
});

describe("textbook overlay reading", () => {
  const textbook = (id:string, name:string, opacity:number, z_index:number) => ({
    layer_id:id, name, visible:true, opacity, z_index, kind:"raster", source:"teaching_map",
    metadata:{teaching_map_id:id, legend_url:`/files/${id}-legend.png`, source_year:id === "population" ? "2015" : "教材材料"}
  } as LayerRecord);
  it("pairs climate with its own legend when population has zero opacity", () => {
    render(<MapEvidenceLegend {...props} basemapId="amap_light" layers={[
      textbook("population","芬兰人口分布图",0,20), textbook("climate","芬兰降水气温图",1,21)
    ]}/>);
    expect(screen.getByRole("img", {name:"芬兰降水气温图原图图例"})).toBeVisible();
    expect(screen.queryByRole("img", {name:"芬兰人口分布图原图图例"})).not.toBeInTheDocument();
    expect(screen.queryByText(/多图叠置/)).not.toBeInTheDocument();
  });
  it("labels mixed colors and presents each legend in the actual paint order", () => {
    render(<MapEvidenceLegend {...props} basemapId="amap_light" layers={[
      textbook("population","芬兰人口分布图",.5,20), textbook("climate","芬兰降水气温图",.5,21),
      textbook("terrain","芬兰地形图",.5,22)
    ]}/>);
    expect(screen.getByText("多图叠置 · 3幅教材图")).toBeVisible();
    expect(screen.getByText(/画面颜色为混合色/)).toHaveTextContent("芬兰地形图 → 芬兰降水气温图 → 芬兰人口分布图");
    expect(screen.getByText("芬兰地形图 · 50% · 最上层")).toBeVisible();
    expect(screen.getByRole("img",{name:"芬兰地形图原图图例"})).toBeVisible();
    expect(screen.getByAltText("芬兰人口分布图原图图例")).not.toBeVisible();
    fireEvent.click(screen.getByText("芬兰人口分布图 · 50%"));
    expect(screen.getByRole("img",{name:"芬兰人口分布图原图图例"})).toBeVisible();
  });
});
