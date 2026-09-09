import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { MapEvidenceLegend } from "../components/MapEvidenceLegend";
import { collectLegendRows, composeSnapshotDocument, drawSnapshotInk, wrapSnapshotText } from "../lib/snapshotDocument";
import type { LayerRecord } from "../types";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("map snapshot source sheet", () => {
  it("freezes the actual folded legend, including colors and sources but no controls", () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true }));
    const props = { globe: false, themeIds: [], showFit: false, onShowFit: vi.fn(), basemapId: "amap_light" };
    const shanghai = { layer_id: "shanghai", visible: true, metadata: { catalog_id: "shanghai_population_density" } } as LayerRecord;
    const { container, rerender } = render(<MapEvidenceLegend {...props} layers={[shanghai]} />);
    const root = container.querySelector(".map-legend-content")!;
    expect(root).toHaveAttribute("hidden");
    const frozen = collectLegendRows(root);
    expect(frozen.find(row => row.kind === "swatches")).toMatchObject({ items: expect.arrayContaining([{label:"<1千", color:expect.any(String)}]) });
    const texts = frozen.filter(row => row.kind === "text").map(row => row.text).join(" ");
    expect(texts).toContain("2020 年常住人口");
    expect(texts).toContain("https://tjj.sh.gov.cn/tjnj/2021tjnj/C0202.htm");
    expect(texts).not.toContain("图例与数据");
    rerender(<MapEvidenceLegend {...props} layers={[]} />);
    expect(collectLegendRows(container.querySelector(".map-legend-content"))).toEqual([]);
    expect(frozen.filter(row => row.kind === "text").map(row => row.text).join(" ")).toBe(texts);
  });

  it("includes the age indicator and official table URL when the legend is folded", () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true }));
    const age = { layer_id: "age", visible: true, metadata: { catalog_id: "shanghai_age_60_plus_2020" } } as LayerRecord;
    const { container } = render(<MapEvidenceLegend globe={false} themeIds={[]} showFit={false} onShowFit={vi.fn()} layers={[age]} />);
    const rows = collectLegendRows(container.querySelector(".map-legend-content"));
    const value = JSON.stringify(rows);
    expect(value).toContain("60岁及以上人口占比");
    expect(value).toContain("≥35%");
    expect(value).toContain("2020 七普");
    expect(value).toContain("https://tjj.sh.gov.cn/tjnj/2025tjnj/C0212.htm");
    expect(value).not.toContain("人/km²");
  });

  it("wraps long source URLs and Chinese text without losing characters", () => {
    const measure = { measureText: (value:string) => ({ width: Array.from(value).length * 10 }) as TextMetrics };
    const value = "人口密度：上海🌏 https://example.org/data/source?year=2020";
    const lines = wrapSnapshotText(measure, value, 80);
    expect(lines.join("")).toBe(value);
    expect(lines.every(line => measure.measureText(line).width <= 80)).toBe(true);
  });

  it("aligns viewport ink with an offset map at a different pixel ratio", () => {
    const ink = document.createElement("canvas"); ink.width = 1600; ink.height = 1000;
    vi.spyOn(ink, "getBoundingClientRect").mockReturnValue({left:10,top:20,width:800,height:500} as DOMRect);
    const drawImage = vi.fn();
    drawSnapshotInk({drawImage} as unknown as CanvasRenderingContext2D, ink, {left:110,top:70,width:400,height:200});
    expect(drawImage).toHaveBeenCalledWith(ink, 200,100,800,400,0,0,400,200);
  });

  it("places readable sources below the map and fails if an official legend cannot load", async () => {
    const drawnText: [string,number,number][] = [];
    const draws: unknown[][] = [];
    const context = {measureText:(value:string)=>({width:value.length*8}), scale:vi.fn(),fillRect:vi.fn(),beginPath:vi.fn(),moveTo:vi.fn(),lineTo:vi.fn(),stroke:vi.fn(),setLineDash:vi.fn(),
      fillText:(...args:[string,number,number])=>drawnText.push(args),drawImage:(...args:unknown[])=>draws.push(args)};
    vi.spyOn(HTMLCanvasElement.prototype,"getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype,"toDataURL").mockReturnValue("data:image/png;base64,exported");
    vi.stubGlobal("Image", class {naturalWidth=800; naturalHeight=400; crossOrigin=""; onload:(()=>void)|null=null; onerror:(()=>void)|null=null;
      set src(value:string) {queueMicrotask(()=>value==="bad"?this.onerror?.():this.onload?.());}
    });
    const metadata = { title:"上海人口密度", capturedAt:"2026/9/9", basemap:"参考底图", attribution:"数据提供方", rows:[{kind:"text" as const,text:"2020年普查及区划面积 https://example.org/source"}] };
    expect(await composeSnapshotDocument("data:image/png;base64,map",metadata,400)).toContain("exported");
    expect(draws[0].slice(1)).toEqual([120,0,400,200]);
    expect(drawnText.every(item=>item[2]>200)).toBe(true);
    expect(drawnText.map(item=>item[0]).join("")).toContain("2020年普查");
    await expect(composeSnapshotDocument("data:image/png;base64,map",{...metadata,rows:[{kind:"image",src:"bad",alt:"官方图例"}]},400)).rejects.toThrow("图例图片无法读取");
  });
});
