import { Circle, Fill, Stroke, Style, Text } from "ol/style";
import { asArray, asString } from "ol/color";
import * as Cesium from "cesium";
import type { LayerRecord } from "../types";
import { densityColor, densityRadius, rankColor, shanghaiAgeColor, shanghaiDensityColor } from "./populationVisual";

type PropertyGetter = (key: string) => unknown;
export type StyledFeature = { getGeometry: () => { getType: () => string } | undefined; get: PropertyGetter };

function numberValue(fallback: number, ...values: unknown[]): number {
  for (const value of values) {
    if (typeof value !== "number" && (typeof value !== "string" || !value.trim())) continue;
    const number = Number(value);
    if (Number.isFinite(number) && number >= 0) return number;
  }
  return fallback;
}
function colorValue(fallback: string, ...values: unknown[]): string {
  for (const value of values) {
    if (typeof value !== "string" || !value.trim()) continue;
    try { asArray(value); return value; } catch { /* try feature/default color */ }
  }
  return fallback;
}
const unit = (value: number) => Math.max(0, Math.min(1, value));

/** Layer override, feature decoration, then existing 2D defaults. Zero is valid. */
export function resolveVectorStyle(record: LayerRecord, get: PropertyGetter) {
  const style = record.style || {};
  const densityTemplate = ["builtin_population_regions", "builtin_population_density"].includes(record.layer_id);
  let fillColor = colorValue("#47a3ff", style.fillColor, get("__fillColor"));
  let fillOpacity = unit(numberValue(0.22, style.fillOpacity, get("__fillOpacity")));
  let strokeColor = colorValue("#e7edf5", style.strokeColor, get("__strokeColor"));
  let strokeWidth = numberValue(2, style.strokeWidth, get("__strokeWidth"));
  let radius = numberValue(7, style.radius, get("__radius"));
  if (densityTemplate) {
    fillColor = densityColor(get("density")); fillOpacity = .88; strokeColor = "#ffffff"; strokeWidth = .9;
    radius = densityRadius(get("density"));
  }
  if (record.metadata?.catalog_id === "shanghai_population_density") {
    fillColor = shanghaiDensityColor(get("density")); fillOpacity = .98; strokeColor = "#4b7776"; strokeWidth = .9;
  }
  if (record.metadata?.catalog_id === "shanghai_age_60_plus_2020") {
    fillColor = shanghaiAgeColor(get("age_60_plus_pct")); fillOpacity = .98; strokeColor = "#ffffff"; strokeWidth = 1;
  }
  if (record.metadata?.visualization && Number(get("rank")) > 0) {
    const visualization = record.metadata.visualization as { items?: unknown[] };
    const rankCount = (Array.isArray(visualization.items) ? visualization.items.length : 0)
      || (Array.isArray(record.data.features) ? record.data.features.length : 0) || 20;
    fillColor = rankColor(Number(get("rank")), rankCount); fillOpacity = .94; strokeColor = "#ffffff"; strokeWidth = 1.4;
  }
  if (record.layer_id === "generated_hu_line") {
    strokeColor = get("line_type") === "dynamic" ? "#d88a26" : "#07575f";
    strokeWidth = get("line_type") === "dynamic" ? 2 : 3;
  }
  return {
    fillColor, fillOpacity, strokeColor, strokeWidth, radius, densityTemplate,
    // Preserve the existing point boost while respecting an explicitly transparent fill.
    pointOpacity: fillOpacity === 0 ? 0 : Math.min(fillOpacity + .36, .9),
    pointStrokeWidth: strokeWidth === 0 ? 0 : 1.2
  };
}

function colorWithOpacity(color: string, opacity: number): string {
  const rgba = asArray(color);
  return asString([rgba[0], rgba[1], rgba[2], (rgba[3] ?? 1) * unit(opacity)]);
}

export function openLayersVectorStyle(record: LayerRecord, showFit = false) {
  return (feature: StyledFeature) => {
    const geometryType = feature.getGeometry()?.getType() || record.geometry_type;
    if (record.layer_id === "generated_hu_line" && feature.get("line_type") === "dynamic" && !showFit) return undefined;
    const { fillColor, fillOpacity, strokeColor, strokeWidth, radius, densityTemplate, pointOpacity, pointStrokeWidth } = resolveVectorStyle(record, key => feature.get(key));
    const labelField = String(record.style.labelField || "name");
    const labelValue = feature.get("__hideLabel") === true ? "" : String(feature.get(labelField) || feature.get("name") || "");
    const catalogId = String(record.metadata?.catalog_id || "");
    const coverage = String(record.metadata?.coverage || "").toLowerCase();
    const templateId = String(record.metadata?.template_id || "");
    const provinceLevelLayer = coverage.includes("china province-level") || [
      "china_provinces", "china_province_population_density", "china_aging_rate_province", "china_province_gdp_per_capita"
    ].includes(catalogId) || ["population_distribution", "population_density", "hu_line_comparison"].includes(templateId);
    return new Style({
      fill: geometryType.includes("Polygon") ? new Fill({ color: colorWithOpacity(fillColor, fillOpacity) }) : undefined,
      // Canvas ignores lineWidth=0; omit the stroke so zero cannot leave a visible outline.
      stroke: strokeWidth > 0 ? new Stroke({ color: strokeColor, width: strokeWidth,
        lineDash: record.layer_id === "generated_hu_line" ? feature.get("line_type") === "dynamic" ? [7, 5] : undefined : (feature.get("__lineDash") as number[] | undefined) || undefined }) : undefined,
      image: geometryType.includes("Point") ? new Circle({
        declutterMode: densityTemplate ? "none" : undefined, radius,
        fill: new Fill({ color: colorWithOpacity(fillColor, pointOpacity) }),
        stroke: pointStrokeWidth > 0 ? new Stroke({ color: strokeColor, width: pointStrokeWidth }) : undefined
      }) : undefined,
      text: labelValue && (!provinceLevelLayer || geometryType.includes("Point")) ? new Text({
        text: labelValue, font: "500 12px 'Microsoft YaHei UI', 'Segoe UI', sans-serif",
        fill: new Fill({ color: "#18343f" }), stroke: new Stroke({ color: "#ffffff", width: 3 }),
        backgroundFill: new Fill({ color: "rgba(255,255,255,.9)" }), padding: [3, 4, 3, 4],
        offsetY: geometryType.includes("Point") ? -(radius + 12) : 0
      }) : undefined
    });
  };
}

function globeColor(color: string, opacity: number) {
  const rgba = asArray(color);
  return new Cesium.Color(rgba[0] / 255, rgba[1] / 255, rgba[2] / 255, (rgba[3] ?? 1) * unit(opacity));
}

/** Rendering adapter only; never edits GeoJSON analytical attributes. */
export function applyCesiumVectorStyle(source: Cesium.GeoJsonDataSource, record: LayerRecord) {
  const time = Cesium.JulianDate.now();
  const opacity = unit(numberValue(1, record.opacity));
  for (const entity of source.entities.values) {
    const properties = entity.properties?.getValue(time) || {};
    const style = resolveVectorStyle(record, key => properties[key]);
    const stroke = globeColor(style.strokeColor, opacity);
    if (entity.billboard || entity.point) {
      entity.billboard = undefined;
      entity.point = new Cesium.PointGraphics({
        color: globeColor(style.fillColor, style.pointOpacity * opacity), pixelSize: style.radius * 2,
        outlineColor: stroke, outlineWidth: style.pointStrokeWidth, heightReference: Cesium.HeightReference.CLAMP_TO_GROUND
      });
    }
    if (entity.polygon) {
      entity.polygon.material = new Cesium.ColorMaterialProperty(globeColor(style.fillColor, style.fillOpacity * opacity));
      entity.polygon.outline = new Cesium.ConstantProperty(style.strokeWidth > 0);
      entity.polygon.outlineColor = new Cesium.ConstantProperty(stroke);
      entity.polygon.outlineWidth = new Cesium.ConstantProperty(style.strokeWidth);
    }
    if (entity.polyline) {
      entity.polyline.material = new Cesium.ColorMaterialProperty(stroke);
      entity.polyline.width = new Cesium.ConstantProperty(style.strokeWidth);
    }
  }
}
