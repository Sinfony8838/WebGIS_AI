import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const oneMap = path.join(root, "backend", "app", "data", "builtin", "one_map");
const catalogPath = path.join(oneMap, "catalog.json");
const boundariesPath = path.join(oneMap, "boundaries", "china_provinces.geojson");
const templateBoundariesPath = path.join(root, "backend", "app", "data", "builtin", "population", "china_provinces.geojson");
const densityPath = path.join(oneMap, "population", "china_province_population_density.geojson");
const agingPath = path.join(oneMap, "population", "china_aging_rate_province.geojson");
const gdpPath = path.join(oneMap, "economy", "china_province_gdp_per_capita.geojson");
const worldBoundariesPath = path.join(oneMap, "boundaries", "world_countries.geojson");
const worldDensityPath = path.join(oneMap, "population", "world_population_density.geojson");
const worldPopulationCsvPath = path.join(oneMap, "population", "world_population_by_country.csv");
const lessonPath = path.join(root, "backend", "app", "data", "builtin", "lessons", "population_distribution_lesson.json");

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeJson(filePath, payload) {
  fs.writeFileSync(filePath, JSON.stringify(payload), "utf8");
}

function points(values) {
  if (Array.isArray(values) && typeof values[0] === "number") {
    return [values];
  }
  return Array.isArray(values) ? values.flatMap(points) : [];
}

function coversTaiwan(feature) {
  return points(feature?.geometry?.coordinates).some(([lon, lat]) => lon >= 119 && lon <= 123 && lat >= 21 && lat <= 26.5);
}

function findTaiwan(features) {
  return features.find((feature) =>
    Number(feature?.properties?.adcode) === 710000 ||
    feature?.properties?.name === "台湾省" ||
    feature?.properties?.region_code === "TWN"
  );
}

function normalizeWorldTaiwan(filePath) {
  const data = readJson(filePath);
  const taiwan = findTaiwan(data.features || []);
  if (!taiwan || !coversTaiwan(taiwan)) {
    throw new Error(`World map is missing Taiwan geometry: ${path.relative(root, filePath)}`);
  }
  taiwan.properties.name = "中国台湾省";
  taiwan.properties.name_en = "Taiwan, China";
  taiwan.properties.administrative_status = "中国台湾省";
  writeJson(filePath, data);
}

const boundaries = readJson(boundariesPath);
const taiwanBoundary = findTaiwan(boundaries.features);
if (!taiwanBoundary) {
  throw new Error("Bundled China province boundaries are missing Taiwan province (adcode 710000)");
}

const gdp = readJson(gdpPath);
let taiwanGdp = gdp.features.find((feature) => feature?.properties?.name === "台湾省");
if (!taiwanGdp) {
  taiwanGdp = {
    type: "Feature",
    properties: {
      name: "台湾省",
      name_en: "Taiwan",
      gdp_per_capita_2020: null,
      iso3: "TWN",
      data_status: "同口径数据暂缺",
      source_name: "Bundled China province boundary; GDP value intentionally left null"
    },
    geometry: taiwanBoundary.geometry
  };
  gdp.features.push(taiwanGdp);
  writeJson(gdpPath, gdp);
}

if (!coversTaiwan(taiwanGdp)) {
  throw new Error("Taiwan province geometry is outside the expected geographic extent");
}

const aging = readJson(agingPath);
const taiwanAging = findTaiwan(aging.features || []);
if (!taiwanAging || !coversTaiwan(taiwanAging)) {
  throw new Error("Aging-rate map is missing Taiwan province geometry");
}
Object.assign(taiwanAging.properties, {
  population: null,
  elderly_65plus: null,
  aging_rate: null,
  youth_rate: null,
  source_year: "2020",
  source_name: "台湾省边界；同口径年龄结构数据暂缺",
  data_status: "同口径数据暂缺",
  license: "边界仅用于完整地图表达；不得将空值解释为零"
});
writeJson(agingPath, aging);

normalizeWorldTaiwan(worldBoundariesPath);
normalizeWorldTaiwan(worldDensityPath);
const worldCsv = fs.readFileSync(worldPopulationCsvPath, "utf8");
const normalizedWorldCsv = worldCsv.replace(/^中华民国,Taiwan,TWN,/m, '中国台湾省,"Taiwan, China",TWN,');
if (!normalizedWorldCsv.includes('中国台湾省,"Taiwan, China",TWN,')) {
  throw new Error("World population CSV is missing the normalized Taiwan row");
}
fs.writeFileSync(worldPopulationCsvPath, normalizedWorldCsv, "utf8");

const catalog = readJson(catalogPath);
const gdpCatalog = catalog.items.find((item) => item.id === "china_province_gdp_per_capita");
if (!gdpCatalog) {
  throw new Error("Catalog entry missing: china_province_gdp_per_capita");
}
gdpCatalog.includes_taiwan = true;
gdpCatalog.source_name = "Global subnational GDP per capita 1990-2022 + Taiwan boundary (no comparable value)";
gdpCatalog.description = "中国省级人均 GDP 专题图完整保留台湾省边界；台湾省同口径数值暂缺并以无数据样式显示。";
const agingCatalog = catalog.items.find((item) => item.id === "china_aging_rate_province");
if (!agingCatalog) {
  throw new Error("Catalog entry missing: china_aging_rate_province");
}
agingCatalog.source_name = "第七次全国人口普查分年龄性别数据（大陆31省区市）；台湾省边界无同口径指标";
agingCatalog.description = "大陆31省区市使用第七次全国人口普查年龄结构数据；台湾省保留完整边界并以无数据样式显示。";
for (const id of ["world_countries", "world_population_density", "world_population_by_country"]) {
  const item = catalog.items.find((entry) => entry.id === id);
  if (item && !String(item.description || "").includes("台湾地区在课堂标签中统一显示为中国台湾省")) {
    item.description = `${item.description || ""} 台湾地区在课堂标签中统一显示为中国台湾省。`.trim();
  }
}
writeJson(catalogPath, catalog);

const lesson = readJson(lessonPath);
const catalogIds = new Set(lesson.stages.flatMap((stage) => stage?.scene?.catalog_layers || []));
const audited = [];
for (const mandatoryPath of [templateBoundariesPath, boundariesPath, densityPath, agingPath, gdpPath]) {
  const data = readJson(mandatoryPath);
  const taiwan = findTaiwan(data.features || []);
  if (!taiwan || !coversTaiwan(taiwan)) {
    throw new Error(`Mandatory population map is missing Taiwan province: ${path.relative(root, mandatoryPath)}`);
  }
}
for (const id of catalogIds) {
  const item = catalog.items.find((entry) => entry.id === id);
  if (!item || !String(item.geometry_type || "").includes("Polygon") || !String(item.coverage || "").startsWith("China")) {
    continue;
  }
  const sourcePath = path.join(root, String(item.source).replace(/^builtin:/, "backend/app/data/builtin/"));
  const data = readJson(sourcePath);
  const covered = data.features.some(coversTaiwan);
  if (!covered) {
    throw new Error(`Population lesson map does not cover Taiwan province: ${id}`);
  }
  if (!item.includes_taiwan) {
    throw new Error(`Catalog metadata does not declare Taiwan coverage: ${id}`);
  }
  audited.push(id);
}

if (taiwanAging.properties.aging_rate !== null || taiwanGdp.properties.gdp_per_capita_2020 !== null) {
  throw new Error("Missing Taiwan indicators must remain null instead of being classified as zero");
}
console.log(
  `Taiwan coverage verified for 5 mandatory population maps and ${audited.length} lesson polygon maps; ` +
  `world labels normalized: ${audited.join(", ")}`
);
