import { expect,it } from "vitest";
import { densityColor,densityRadius,shanghaiDensityColor } from "../lib/populationVisual";
it("distinguishes absent data from a true zero and treats threshold equality consistently",()=>{
  expect(densityColor(null)).not.toBe(densityColor(0));
  expect(densityColor("bad")).toBe(densityColor(null));
  expect(densityColor(9.99)).not.toBe(densityColor(10));
  expect(densityColor(799.9)).not.toBe(densityColor(800));
  expect(densityRadius(400)).toBeCloseTo(densityRadius(100)*2);
  expect(densityRadius(1e9)).toBe(24);
});

it("keeps low and high Shanghai district densities distinguishable",()=>{
  expect(shanghaiDensityColor(538)).not.toBe(shanghaiDensityColor(8250));
  expect(shanghaiDensityColor(8250)).not.toBe(shanghaiDensityColor(32357));
  expect(shanghaiDensityColor(null)).not.toBe(shanghaiDensityColor(0));
  expect(shanghaiDensityColor(999)).not.toBe(shanghaiDensityColor(1000));
});

it("keeps age percentages separate from density and rejects impossible ratios", async () => {
  const { shanghaiAgeColor } = await import("../lib/populationVisual");
  expect(shanghaiAgeColor(16.6)).not.toBe(shanghaiAgeColor(39.7));
  expect(shanghaiAgeColor(0)).not.toBe(shanghaiAgeColor(null));
  expect(shanghaiAgeColor(101)).toBe(shanghaiAgeColor(null));
  expect(shanghaiAgeColor(19.9)).not.toBe(shanghaiAgeColor(20));
});
