import { describe, expect, it } from "vitest";
import * as Cesium from "cesium";
import { asArray } from "ol/color";
import Feature from "ol/Feature";
import Point from "ol/geom/Point";
import Polygon from "ol/geom/Polygon";
import LineString from "ol/geom/LineString";
import CircleStyle from "ol/style/Circle";
import VectorLayer from "ol/layer/Vector";
import type { LayerRecord } from "../types";
import { applyCesiumVectorStyle, openLayersVectorStyle, resolveVectorStyle } from "../lib/vectorStyle";

function layer(patch: Partial<LayerRecord> = {}): LayerRecord {
  return { layer_id: "synthetic", name: "synthetic", kind: "vector", source: "upload", geometry_type: "Polygon",
    visible: true, opacity: 1, z_index: 1, style: {}, metadata: {}, data: { features: [] }, ...patch };
}
function engines(record: LayerRecord, properties: Record<string, unknown> = {}) {
  const source = new Cesium.GeoJsonDataSource("synthetic-no-network");
  const polygon = source.entities.add({ id: "polygon", polygon: {}, properties });
  const point = source.entities.add({ id: "point", billboard: {}, properties });
  const line = source.entities.add({ id: "line", polyline: {}, properties });
  applyCesiumVectorStyle(source, record);
  const style = openLayersVectorStyle(record);
  const pointStyle = style(new Feature({ ...properties, geometry: new Point([0, 0]) }))!;
  const polygonStyle = style(new Feature({ ...properties, geometry: new Polygon([[[0,0],[1,0],[1,1],[0,0]]]) }))!;
  const lineStyle = style(new Feature({ ...properties, geometry: new LineString([[0,0],[1,1]]) }))!;
  const olLayer = new VectorLayer({ opacity: record.opacity });
  const time = Cesium.JulianDate.now();
  const polygonColor = (polygon.polygon!.material as Cesium.ColorMaterialProperty).getValue(time)!.color;
  const lineColor = (line.polyline!.material as Cesium.ColorMaterialProperty).getValue(time)!.color;
  return { polygon, point, line, pointStyle, polygonStyle, lineStyle, olLayer, polygonColor, lineColor, time };
}
function expectColorAgreement(css: string, color: Cesium.Color, opacity = 1) {
  const rgba = asArray(css);
  expect(color.red).toBeCloseTo(rgba[0] / 255);
  expect(color.green).toBeCloseTo(rgba[1] / 255);
  expect(color.blue).toBeCloseTo(rgba[2] / 255);
  expect(color.alpha).toBeCloseTo((rgba[3] ?? 1) * opacity);
}

describe("shared vector display contract", () => {
  it("layer overrides win in both engines without modifying decorated feature values", () => {
    const properties = Object.freeze({ __fillColor: "#123456", __fillOpacity: .8, __strokeColor: "#abcdef", __strokeWidth: 6, __radius: 9 });
    const record = layer({ style: Object.freeze({ fillColor: "#ff0000", fillOpacity: .4, strokeColor: "#00ff00", strokeWidth: 3, radius: 5 }) });
    const rendered = engines(record, properties);
    expectColorAgreement(rendered.polygonStyle.getFill()!.getColor() as string, rendered.polygonColor);
    expectColorAgreement(rendered.lineStyle.getStroke()!.getColor() as string, rendered.lineColor);
    expect(rendered.polygonColor.red).toBe(1);
    expect(rendered.polygonColor.alpha).toBeCloseTo(.4);
    expect(rendered.line.polyline!.width!.getValue(rendered.time)).toBe(3);
    expect((rendered.pointStyle.getImage() as CircleStyle).getRadius()).toBe(5);
    expect(rendered.point.point!.pixelSize!.getValue(rendered.time)).toBe(10);
    expect(properties.__fillColor).toBe("#123456");
    expect(record.style.fillColor).toBe("#ff0000");
  });

  it("feature decorations win when a layer has no override, including workflow class colors", () => {
    const rendered = engines(layer({ source: "output_artifact" }), { __fillColor: "#4488cc", __fillOpacity: .85, __strokeColor: "#102030", __strokeWidth: 1.6, __radius: 6 });
    expectColorAgreement(rendered.polygonStyle.getFill()!.getColor() as string, rendered.polygonColor);
    expect(rendered.polygonColor.alpha).toBeCloseTo(.85);
    expectColorAgreement(rendered.lineStyle.getStroke()!.getColor() as string, rendered.lineColor);
    expect(rendered.line.polyline!.width!.getValue(rendered.time)).toBe(1.6);
  });

  it("keeps the existing 2D default and nonzero point boost in the shared contract", () => {
    const rendered = engines(layer());
    expectColorAgreement(rendered.polygonStyle.getFill()!.getColor() as string, rendered.polygonColor);
    expect(rendered.polygonColor.alpha).toBeCloseTo(.22);
    const circle = rendered.pointStyle.getImage() as CircleStyle;
    expect(circle.getRadius()).toBe(7);
    expectColorAgreement(circle.getFill()!.getColor() as string, rendered.point.point!.color!.getValue(rendered.time));
    expect(rendered.point.point!.color!.getValue(rendered.time).alpha).toBeCloseTo(.58);
  });

  it.each(["layer", "feature"])("zero fill, stroke width and radius survive %s values", origin => {
    const record = layer({ style: origin === "layer" ? { fillOpacity: 0, strokeWidth: 0, radius: 0 } : {} });
    const rendered = engines(record, origin === "feature" ? { __fillOpacity: 0, __strokeWidth: 0, __radius: 0 } : { __fillOpacity: .9, __strokeWidth: 9, __radius: 9 });
    expect(rendered.polygonColor.alpha).toBe(0);
    expect(asArray(rendered.polygonStyle.getFill()!.getColor() as string)[3]).toBe(0);
    expect(rendered.lineStyle.getStroke()!.getWidth()).toBe(0);
    expect(rendered.line.polyline!.width!.getValue(rendered.time)).toBe(0);
    expect(rendered.polygon.polygon!.outline!.getValue(rendered.time)).toBe(false);
    const circle = rendered.pointStyle.getImage() as CircleStyle;
    expect(circle.getRadius()).toBe(0);
    expect(circle.getStroke()!.getWidth()).toBe(0);
    expect(rendered.point.point!.pixelSize!.getValue(rendered.time)).toBe(0);
    expect(rendered.point.point!.color!.getValue(rendered.time).alpha).toBe(0);
  });

  it("numeric strings preserve zero instead of taking a fallback", () => {
    expect(resolveVectorStyle(layer({ style: { fillOpacity: "0", strokeWidth: "0", radius: "0" } }), () => 8)).toMatchObject({ fillOpacity: 0, strokeWidth: 0, radius: 0 });
  });

  it.each([undefined, null, "", false, {}, NaN, Infinity, -1])("invalid numeric override %s falls back to valid feature metadata", value => {
    const props = { __fillOpacity: .4, __strokeWidth: 3, __radius: 9 };
    expect(resolveVectorStyle(layer({ style: { fillOpacity: value, strokeWidth: value, radius: value } }), key => props[key as keyof typeof props])).toMatchObject({ fillOpacity: .4, strokeWidth: 3, radius: 9 });
  });

  it.each([0, .5, 1])("combines CSS alpha and layer opacity %s equally in both engines", opacity => {
    const rendered = engines(layer({ opacity, style: { fillColor: "rgba(12, 34, 56, 0.5)", fillOpacity: .4, strokeColor: "rgba(21, 43, 65, 0.6)" } }));
    expectColorAgreement(rendered.polygonStyle.getFill()!.getColor() as string, rendered.polygonColor, rendered.olLayer.getOpacity());
    expectColorAgreement(rendered.lineStyle.getStroke()!.getColor() as string, rendered.lineColor, rendered.olLayer.getOpacity());
    expectColorAgreement((rendered.pointStyle.getImage() as CircleStyle).getFill()!.getColor() as string, rendered.point.point!.color!.getValue(rendered.time), opacity);
  });

  it("supports named CSS colors and falls back from invalid layer colors", () => {
    const rendered = engines(layer({ style: { fillColor: "red", strokeColor: "invalid-css-color", fillOpacity: 0 } }), { __strokeColor: "blue" });
    expect(rendered.polygonColor.red).toBe(1);
    expect(rendered.polygonColor.alpha).toBe(0);
    expect(rendered.lineColor.blue).toBe(1);
  });

  it("retains population display breaks, symbol radius and special-layer precedence", () => {
    const record = layer({ layer_id: "builtin_population_density", style: { fillColor: "red", fillOpacity: 0 } });
    const props = { density: 400 };
    const value = resolveVectorStyle(record, key => props[key as keyof typeof props]);
    expect(value).toMatchObject({ fillColor: "#288b87", fillOpacity: .88, strokeColor: "#ffffff", strokeWidth: .9, radius: 11 });
  });

  it.each([
    ["shanghai_population_density", { density: 5000 }, "#70bbae", "#4b7776", .9],
    ["shanghai_age_60_plus_2020", { age_60_plus_pct: 30 }, "#756bb1", "#ffffff", 1]
  ])("retains %s teaching colors and widths", (catalog_id, props, fillColor, strokeColor, strokeWidth) => {
    const value = resolveVectorStyle(layer({ metadata: { catalog_id } }), key => (props as Record<string, unknown>)[key]);
    expect(value).toMatchObject({ fillColor, strokeColor, strokeWidth, fillOpacity: .98 });
  });

  it.each([[1, "#274c77"], [20, "#b7c9e2"]])("retains TOP20 rank %s colors without changing rank data", (rank, color) => {
    const props = Object.freeze({ rank });
    expect(resolveVectorStyle(layer({ metadata: { visualization: {} }, data: { features: Array(20).fill({}) } }), key => props[key as keyof typeof props])).toMatchObject({ fillColor: color, fillOpacity: .94, strokeWidth: 1.4 });
  });

  it("retains dynamic Hu-line visibility, dashes and fixed-line styling", () => {
    const record = layer({ layer_id: "generated_hu_line" });
    const dynamic = new Feature({ line_type: "dynamic", geometry: new LineString([[0,0],[1,1]]) });
    expect(openLayersVectorStyle(record)(dynamic)).toBeUndefined();
    const shown = openLayersVectorStyle(record, true)(dynamic)!;
    expect(shown.getStroke()!.getLineDash()).toEqual([7, 5]);
    expect(shown.getStroke()!.getColor()).toBe("#d88a26");
    const fixed = new Feature({ line_type: "classic", geometry: new LineString([[0,0],[1,1]]) });
    expect(openLayersVectorStyle(record)(fixed)!.getStroke()!.getWidth()).toBe(3);
  });

  it("retains province polygon label suppression, point labels and explicit hide-label", () => {
    const record = layer({ metadata: { catalog_id: "china_provinces" } });
    const polygon = new Feature({ name: "synthetic", geometry: new Polygon([]) });
    const point = new Feature({ name: "synthetic", geometry: new Point([0,0]) });
    expect(openLayersVectorStyle(record)(polygon)!.getText()).toBeNull();
    expect(openLayersVectorStyle(record)(point)!.getText()!.getText()).toBe("synthetic");
    point.set("__hideLabel", true);
    expect(openLayersVectorStyle(record)(point)!.getText()).toBeNull();
  });
});
