import { describe, expect, it } from "vitest";
import type { LayerRecord } from "../types";
import { DENSITY_SCALE } from "../lib/populationVisual";
import { thematicColor, rankLegend } from "../lib/thematicPalette";
import { resolveVectorStyle } from "../lib/vectorStyle";
const layer = { layer_id:"builtin_population_regions", style:{}, metadata:{style_overrides:{fillColor:"#ef4444"}}, data:{features:[]} } as unknown as LayerRecord;
describe("thematic palette editing", () => {
  it("keeps every class boundary and missing value while recoloring all bins", () => {
    for (const value of [0, 9.99, 10, 99.99, 100, 399.99, 400, 799.99, 800, 9999]) {
      const expected = DENSITY_SCALE.find(item => value < item.max)!;
      expect(resolveVectorStyle(layer, key => key === "density" ? value : undefined).fillColor).toBe(thematicColor(layer, expected.color));
    }
    expect(new Set(DENSITY_SCALE.map(item => thematicColor(layer,item.color))).size).toBe(5);
    expect(resolveVectorStyle(layer, () => null).fillColor).toBe("#dbe1e6");
    expect(thematicColor({...layer,metadata:{style_overrides:{fillColor:"invalid"}}}, "#288b87")).toBe("#288b87");
  });
  it("uses the same colors and exact numeric values for every rank in legend and renderer", () => {
    const items=Array.from({length:20},(_,i)=>({rank:i+1,name:`City ${i}`,value:100000-i*1000,unit:"人"}));
    const record={...layer,layer_id:"ranked",metadata:{...layer.metadata,visualization:{items}}};
    const snapshot=JSON.stringify(record);
    const legend=rankLegend(record);
    for (const item of legend) expect(resolveVectorStyle(record,key=>key === "rank" ? item.rank : undefined).fillColor).toBe(item.color);
    expect(new Set(legend.map(item=>item.color)).size).toBe(20);
    expect(legend[0].label).toBe("100,000 人");
    expect(legend[19].label).toBe("81,000 人");
    expect(JSON.stringify(record)).toBe(snapshot);
  });
  it("preserves workflow feature classes instead of flattening them with the layer fill", () => {
    const record={...layer,layer_id:"workflow",style:{fillColor:"#ef4444"},metadata:{...layer.metadata,workflow_style:{legend:{items:[]}}}};
    for (const color of ["#edf6f3", "#70bbae", "#095c61"]) expect(resolveVectorStyle(record,key=>key==="__fillColor" ? color : undefined).fillColor).toBe(thematicColor(record,color));
  });
});
