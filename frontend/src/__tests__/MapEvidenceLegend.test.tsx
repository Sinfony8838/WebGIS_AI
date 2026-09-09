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
