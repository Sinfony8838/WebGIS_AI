import Polygon from "ol/geom/Polygon";
import { selectVisibleLabels, type LabelBox } from "./labelLayout";
/**
 * Thematic 3D layers for the Cesium digital globe.
 *
 * Each theme turns a one_map catalog dataset into Cesium entities that
 * support geography teaching directly on the globe:
 *
 *   - population_columns  省级人口柱体（高度=人口，颜色=密度）
 *   - density_fill        人口密度分级设色（贴地面）
 *   - density_3d          人口密度高度映射（拉伸棱柱）
 *   - hu_line             胡焕庸线（参考连线 + 两侧注记）
 *   - climate_zones       中国气候类型区划（着色面 + 注记）
 *   - migration_flows     人口迁徙弧线（发光弧 + 动态光点）
 *
 * Data is fetched through the read-only `/datasets/catalog/{id}/data`
 * endpoint (cached in api.ts) and is never written into project state,
 * so toggling themes has zero impact on runtime.json size.
 */
import * as Cesium from "cesium";
import { DENSITY_SCALE } from "./populationVisual";
import { fetchCatalogDatasetData } from "../api";
import type { GeoJsonFeature, GeoJsonFeatureCollection } from "../types";

export type GlobeThemeId =
  | "population_columns"
  | "density_fill"
  | "density_3d"
  | "hu_line"
  | "climate_zones"
  | "migration_flows";

export type GlobeLegendItem = { color: string; label: string };

export type GlobeThemeDef = {
  id: GlobeThemeId;
  name: string;
  description: string;
  legendTitle?: string;
  legend?: GlobeLegendItem[];
  legendNote?: string;
  /** 数据质量标注：schematic=教学示意，estimated=估算；缺省为真实数据。 */
  dataQuality?: "schematic" | "estimated";
};

export type GlobeScenePreset = {
  id: string;
  name: string;
  icon: string;
  description: string;
  themes: GlobeThemeId[];
  camera: { lon: number; lat: number; altitudeMeters: number; pitchDeg: number };
};

export type ThemeTooltip = { title: string; lines: string[] };

// ── Classification ──────────────────────────────────────────────────

/** Density class breaks in persons/km², matched to textbook conventions. */
const DENSITY_CLASSES = DENSITY_SCALE.map(item => ({...item, label: `${item.label} 人/km²`}));

function densityClass(density: number): { color: string; label: string } {
  if(!Number.isFinite(density)||density<0) return {color:"#dbe1e6",label:"缺失数据"};
  for (const cls of DENSITY_CLASSES) {
    if (density < cls.max) {
      return cls;
    }
  }
  return DENSITY_CLASSES[DENSITY_CLASSES.length - 1];
}

/** Qualitative palette for climate zones, keyed by name substring. */
const CLIMATE_COLORS: { match: string; color: string; label: string }[] = [
  { match: "热带季风", color: "#e05243", label: "热带季风气候" },
  { match: "亚热带季风", color: "#f2a04e", label: "亚热带季风气候" },
  { match: "温带季风", color: "#f5d95c", label: "温带季风气候" },
  { match: "温带大陆", color: "#b08a6a", label: "温带大陆性气候" },
  { match: "高山", color: "#8f7bd8", label: "高山高原气候" },
  { match: "高原", color: "#8f7bd8", label: "高原山地气候" }
];

function climateColor(name: string): string {
  // "亚热带季风" must be tested before "热带季风", so scan in列表顺序 with
  // the more specific entry placed first below.
  if (name.includes("亚热带季风")) return "#f2a04e";
  for (const entry of CLIMATE_COLORS) {
    if (name.includes(entry.match)) {
      return entry.color;
    }
  }
  return "#5bc8d6";
}

// ── Formatting helpers ──────────────────────────────────────────────

function formatPopulation(pop: number): string {
  if (!Number.isFinite(pop) || pop <= 0) return "—";
  if (pop >= 1e8) return `${(pop / 1e8).toFixed(2)} 亿人`;
  return `${Math.round(pop / 1e4).toLocaleString("zh-CN")} 万人`;
}

function formatDensity(density: number): string {
  if (!Number.isFinite(density)) return "—";
  return `${density < 10 ? density.toFixed(1) : Math.round(density).toLocaleString("zh-CN")} 人/km²`;
}

function numberProp(props: Record<string, unknown> | null, key: string): number {
  const value = props ? props[key] : undefined;
  const num = typeof value === "string" ? Number(value) : (value as number);
  return typeof num === "number" && Number.isFinite(num) ? num : NaN;
}

function stringProp(props: Record<string, unknown> | null, key: string): string {
  const value = props ? props[key] : undefined;
  return typeof value === "string" ? value : "";
}

// ── Geometry helpers ────────────────────────────────────────────────

type LonLat = [number, number];

/** Keep labels and columns inside the largest land polygon, including concave regions. */
function featureAnchor(feature: GeoJsonFeature): LonLat | null {
  const geometry=feature.geometry;
  if(!geometry) return null;
  if(geometry.type === "Point") return (geometry.coordinates as number[]).slice(0,2) as LonLat;
  const coordinates=geometry.type === "Polygon" ? [geometry.coordinates as number[][][]] : geometry.type === "MultiPolygon" ? geometry.coordinates as number[][][][] : [];
  const polygons=coordinates.map(coords=>new Polygon(coords)).sort((a,b)=>b.getArea()-a.getArea());
  return polygons[0] ? polygons[0].getInteriorPoint().getCoordinates().slice(0,2) as LonLat : null;
}

/** Sample an arch between two lon/lat points with a sine height profile. */
function sampleArc(from: LonLat, to: LonLat, peakMeters: number, samples = 64): Cesium.Cartesian3[] {
  const positions: Cesium.Cartesian3[] = [];
  for (let i = 0; i <= samples; i += 1) {
    const t = i / samples;
    const lon = from[0] + (to[0] - from[0]) * t;
    const lat = from[1] + (to[1] - from[1]) * t;
    const height = Math.sin(Math.PI * t) * peakMeters;
    positions.push(Cesium.Cartesian3.fromDegrees(lon, lat, height));
  }
  return positions;
}

function arcPointAt(from: LonLat, to: LonLat, peakMeters: number, t: number): Cesium.Cartesian3 {
  const lon = from[0] + (to[0] - from[0]) * t;
  const lat = from[1] + (to[1] - from[1]) * t;
  const height = Math.sin(Math.PI * t) * peakMeters;
  return Cesium.Cartesian3.fromDegrees(lon, lat, height);
}

function greatCircleKm(from: LonLat, to: LonLat): number {
  const start = Cesium.Cartographic.fromDegrees(from[0], from[1]);
  const end = Cesium.Cartographic.fromDegrees(to[0], to[1]);
  return new Cesium.EllipsoidGeodesic(start, end).surfaceDistance / 1000;
}

function setTooltip(entity: Cesium.Entity, tooltip: ThemeTooltip): void {
  (entity as unknown as { __themeTooltip?: ThemeTooltip }).__themeTooltip = tooltip;
}

export function getEntityTooltip(picked: unknown): ThemeTooltip | null {
  const entity = (picked as { id?: unknown })?.id;
  if (entity instanceof Cesium.Entity) {
    const tooltip = (entity as unknown as { __themeTooltip?: ThemeTooltip }).__themeTooltip;
    return tooltip ?? null;
  }
  return null;
}

// ── Theme builders ──────────────────────────────────────────────────

type ThemeHandle = { dataSources: Cesium.DataSource[]; labels?: Cesium.Entity[] };

const LABEL_FONT = "500 15px 'Microsoft YaHei UI', sans-serif";
const LABEL_FILL = Cesium.Color.fromCssColorString("#18343f");
const LABEL_OUTLINE = Cesium.Color.WHITE;

function makeLabel(text: string, options: Partial<Cesium.LabelGraphics.ConstructorOptions> = {}) {
  return new Cesium.LabelGraphics({
    text,
    font: LABEL_FONT,
    fillColor: LABEL_FILL,
    outlineColor: LABEL_OUTLINE,
    outlineWidth: 3,
    style: Cesium.LabelStyle.FILL_AND_OUTLINE,
    horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
    verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
    showBackground: true,
    backgroundColor: Cesium.Color.WHITE.withAlpha(.94),
    backgroundPadding: new Cesium.Cartesian2(7, 5),
    pixelOffset: new Cesium.Cartesian2(0, -8),
    disableDepthTestDistance: Number.POSITIVE_INFINITY,
    ...options
  });
}

/** 省级人口柱体：高度=人口，颜色=密度分级。 */
async function buildPopulationColumns(): Promise<ThemeHandle> {
  const { data } = await fetchCatalogDatasetData("china_province_population_density");
  const source = new Cesium.CustomDataSource("globe_theme_population_columns");
  const maxPopulation = Math.max(
    ...data.features.map((f) => numberProp(f.properties, "population")).filter(Number.isFinite),
    1
  );
  const ranked = [...data.features]
    .map((f) => numberProp(f.properties, "population"))
    .filter(Number.isFinite)
    .sort((a, b) => b - a);
  const labelThreshold = ranked[Math.min(9, ranked.length - 1)] ?? 0;

  const labels: Cesium.Entity[] = [];
  for (const feature of [...data.features].sort((a,b) => numberProp(b.properties,"population") - numberProp(a.properties,"population"))) {
    const props = feature.properties;
    const population = numberProp(props, "population");
    const density = numberProp(props, "density");
    const center = featureAnchor(feature) ?? (props?.center as number[] | undefined) ?? null;
    if (!center || !Number.isFinite(population)) continue;
    const [lon, lat] = center;
    const length = Math.max((population / maxPopulation) * 780_000, 12_000);
    const cls = densityClass(density);
    const color = Cesium.Color.fromCssColorString(cls.color).withAlpha(0.92);
    const name = stringProp(props, "short_name") || stringProp(props, "name");

    const column = source.entities.add({
      position: Cesium.Cartesian3.fromDegrees(lon, lat, length / 2),
      cylinder: {
        length,
        topRadius: 52_000,
        bottomRadius: 52_000,
        material: color,
        outline: false
      }
    });
    setTooltip(column, {
      title: name,
      lines: [`常住人口：${formatPopulation(population)}`, `人口密度：${formatDensity(density)}`]
    });

    if (population >= labelThreshold) {
      const label = source.entities.add({
        position: Cesium.Cartesian3.fromDegrees(lon, lat, length + 40_000),
        label: makeLabel(`${name} ${formatPopulation(population)}`, {
          font: "500 14px 'Microsoft YaHei UI', sans-serif"
        })
      });
      labels.push(label);
      setTooltip(label, {
        title: name,
        lines: [`常住人口：${formatPopulation(population)}`, `人口密度：${formatDensity(density)}`]
      });
    }
  }
  return { dataSources: [source], labels };
}

/** 人口密度分级设色（extruded=false）或高度映射（extruded=true）。 */
async function buildDensityPolygons(extruded: boolean): Promise<ThemeHandle> {
  const { data } = await fetchCatalogDatasetData("china_province_population_density");
  const source = await Cesium.GeoJsonDataSource.load(data as unknown as object, {
    fill: Cesium.Color.fromCssColorString("#fd8d3c").withAlpha(0.7),
    stroke: Cesium.Color.WHITE.withAlpha(0.4),
    strokeWidth: 1
  });
  source.name = extruded ? "globe_theme_density_3d" : "globe_theme_density_fill";
  for (const entity of source.entities.values) {
    if (!entity.polygon) continue;
    const density = Number(entity.properties?.density?.getValue?.() ?? NaN);
    const population = Number(entity.properties?.population?.getValue?.() ?? NaN);
    const name = String(
      entity.properties?.short_name?.getValue?.() || entity.properties?.name?.getValue?.() || ""
    );
    const cls = densityClass(density);
    entity.polygon.material = new Cesium.ColorMaterialProperty(
      Cesium.Color.fromCssColorString(cls.color).withAlpha(extruded ? 0.85 : 0.78)
    );
    entity.polygon.outline = new Cesium.ConstantProperty(true);
    entity.polygon.outlineColor = new Cesium.ConstantProperty(
      Cesium.Color.WHITE.withAlpha(extruded ? 0.25 : 0.42)
    );
    if (extruded) {
      // sqrt scale keeps直辖市 from dwarfing everything while low-density
      // western provinces stay visibly flat.
      const height = Math.min(Math.sqrt(Math.max(density, 0)) * 12_000, 820_000);
      entity.polygon.height = new Cesium.ConstantProperty(0);
      entity.polygon.extrudedHeight = new Cesium.ConstantProperty(Math.max(height, 3_000));
    } else {
      entity.polygon.height = new Cesium.ConstantProperty(0);
    }
    setTooltip(entity, {
      title: name,
      lines: [`人口密度：${formatDensity(density)}`, `常住人口：${formatPopulation(population)}`]
    });
  }
  return { dataSources: [source] };
}

/** 胡焕庸线：地表参考连线与端点注记。 */
async function buildHuLine(): Promise<ThemeHandle> {
  const { data } = await fetchCatalogDatasetData("hu_huanyong_line");
  const line = data.features.find((f) => f.geometry?.type === "LineString");
  const coords = (line?.geometry?.coordinates as number[][] | undefined) ?? [
    [127.499, 50.249],
    [98.497, 25.02]
  ];
  const from: LonLat = [coords[0][0], coords[0][1]];
  const to: LonLat = [coords[coords.length - 1][0], coords[coords.length - 1][1]];
  const source = new Cesium.CustomDataSource("globe_theme_hu_line");

  const samples = 48;
  const lons: number[] = [];
  const lats: number[] = [];
  for (let i = 0; i <= samples; i += 1) {
    const t = i / samples;
    lons.push(from[0] + (to[0] - from[0]) * t);
    lats.push(from[1] + (to[1] - from[1]) * t);
  }
  const groundPositions = lons.map((lon, i) => Cesium.Cartesian3.fromDegrees(lon, lats[i], 4_000));

  const glowLine = source.entities.add({
    polyline: {
      positions: groundPositions,
      width: 5,
      material: new Cesium.PolylineOutlineMaterialProperty({ color:Cesium.Color.fromCssColorString("#07575f"), outlineColor:Cesium.Color.WHITE, outlineWidth:1.5 })
    }
  });
  const tooltip: ThemeTooltip = {
    title: "胡焕庸线（黑河—腾冲）",
    lines: ["1935 年由胡焕庸提出", "1935 年口径：东南侧约36%国土、96%人口", "地名参考坐标连线，非测绘边界；依据见地图图例"]
  };
  setTooltip(glowLine, tooltip);

  source.entities.add({
    position: Cesium.Cartesian3.fromDegrees(from[0], from[1], 8_000),
    label: makeLabel("黑河")
  });
  source.entities.add({
    position: Cesium.Cartesian3.fromDegrees(to[0], to[1], 8_000),
    label: makeLabel("腾冲")
  });
  const midLon = (from[0] + to[0]) / 2;
  const midLat = (from[1] + to[1]) / 2;
  source.entities.add({
    position: Cesium.Cartesian3.fromDegrees(midLon + 7.5, midLat - 4, 60_000),
    label: makeLabel("东南侧 · 总体较密", {
      font: "500 14px 'Microsoft YaHei UI', sans-serif",
      fillColor: LABEL_FILL
    })
  });
  source.entities.add({
    position: Cesium.Cartesian3.fromDegrees(midLon - 8.5, midLat + 4.5, 60_000),
    label: makeLabel("西北侧 · 总体较疏", {
      font: "500 14px 'Microsoft YaHei UI', sans-serif",
      fillColor: LABEL_FILL
    })
  });
  return { dataSources: [source] };
}

/** 中国气候类型区划着色 + 分区注记。 */
async function buildClimateZones(): Promise<ThemeHandle> {
  const { data } = await fetchCatalogDatasetData("china_climate_types");
  const source = await Cesium.GeoJsonDataSource.load(data as unknown as object, {
    stroke: Cesium.Color.WHITE.withAlpha(0.35),
    strokeWidth: 1
  });
  source.name = "globe_theme_climate_zones";
  for (const entity of source.entities.values) {
    if (!entity.polygon) continue;
    const name = String(entity.properties?.name?.getValue?.() || "");
    const color = climateColor(name);
    entity.polygon.material = new Cesium.ColorMaterialProperty(
      Cesium.Color.fromCssColorString(color).withAlpha(0.55)
    );
    entity.polygon.outline = new Cesium.ConstantProperty(true);
    entity.polygon.outlineColor = new Cesium.ConstantProperty(Cesium.Color.WHITE.withAlpha(0.3));
    // Slight lift avoids z-fighting when combined with人口密度 fills.
    entity.polygon.height = new Cesium.ConstantProperty(1_500);
    setTooltip(entity, { title: name || "气候区", lines: ["中国主要气候类型分布（省级精度）"] });
  }
  // Label each distinct zone once, at the anchor of its largest feature.
  const labeled = new Set<string>();
  const featuresBySize = [...data.features].sort(
    (a, b) => JSON.stringify(b.geometry ?? "").length - JSON.stringify(a.geometry ?? "").length
  );
  for (const feature of featuresBySize) {
    const name = stringProp(feature.properties, "name");
    if (!name || labeled.has(name)) continue;
    const anchor = featureAnchor(feature);
    if (!anchor) continue;
    labeled.add(name);
    source.entities.add(
      new Cesium.Entity({
        position: Cesium.Cartesian3.fromDegrees(anchor[0], anchor[1], 30_000),
        label: makeLabel(name, { font: "500 14px 'Microsoft YaHei UI', sans-serif" })
      })
    );
  }
  return { dataSources: [source] };
}

/** 人口迁徙弧线：发光弧 + 沿弧循环的动态光点。 */
async function buildMigrationFlows(): Promise<ThemeHandle> {
  const { data } = await fetchCatalogDatasetData("china_migration_flows");
  const source = new Cesium.CustomDataSource("globe_theme_migration_flows");
  const start = Date.now();
  data.features.forEach((feature, index) => {
    const geometry = feature.geometry;
    if (!geometry || geometry.type !== "LineString") return;
    const coords = geometry.coordinates as number[][];
    if (!coords || coords.length < 2) return;
    const from: LonLat = [coords[0][0], coords[0][1]];
    const to: LonLat = [coords[coords.length - 1][0], coords[coords.length - 1][1]];
    const migrants = numberProp(feature.properties, "migrants");
    const name = stringProp(feature.properties, "name");
    const origin = stringProp(feature.properties, "origin");
    const destination = stringProp(feature.properties, "destination");
    const distanceKm = greatCircleKm(from, to);
    const peak = Math.min(Math.max(distanceKm * 1000 * 0.22, 180_000), 850_000);
    const width = 2.5 + (Number.isFinite(migrants) ? migrants / 55 : 2);

    const arc = source.entities.add({
      polyline: {
        positions: sampleArc(from, to, peak),
        width,
        material: new Cesium.PolylineGlowMaterialProperty({
          glowPower: 0.22,
          taperPower: 0.6,
          color: Cesium.Color.fromCssColorString("#4dd0e1")
        })
      }
    });
    const tooltip: ThemeTooltip = {
      title: name || `${origin} → ${destination}`,
      lines: [`迁徙方向：${origin} → ${destination}`, `迁徙规模：约 ${migrants} 万人`]
    };
    setTooltip(arc, tooltip);

    // Comet dot cycling along the arc; phase-offset per flow so the four
    // flows don't pulse in unison.
    const periodMs = 5200;
    const phase = index * 0.23;
    const comet = source.entities.add({
      position: new Cesium.CallbackProperty(() => {
        const t = ((Date.now() - start) / periodMs + phase) % 1;
        return arcPointAt(from, to, peak, t);
      }, false) as unknown as Cesium.PositionProperty,
      point: {
        pixelSize: 9,
        color: Cesium.Color.fromCssColorString("#fff59d"),
        outlineColor: Cesium.Color.fromCssColorString("#4dd0e1").withAlpha(0.9),
        outlineWidth: 3,
        disableDepthTestDistance: Number.POSITIVE_INFINITY
      }
    });
    setTooltip(comet, tooltip);

    const labelAnchor = arcPointAt(from, to, peak + 70_000, 0.5);
    source.entities.add({
      position: labelAnchor,
      label: makeLabel(`${name || `${origin}→${destination}`} · ${migrants}万人`, {
        font: "500 14px 'Microsoft YaHei UI', sans-serif"
      })
    });
  });
  return { dataSources: [source] };
}

const THEME_BUILDERS: Record<GlobeThemeId, () => Promise<ThemeHandle>> = {
  population_columns: buildPopulationColumns,
  density_fill: () => buildDensityPolygons(false),
  density_3d: () => buildDensityPolygons(true),
  hu_line: buildHuLine,
  climate_zones: buildClimateZones,
  migration_flows: buildMigrationFlows
};

// ── Theme metadata (panel + legend) ─────────────────────────────────

export const GLOBE_THEMES: GlobeThemeDef[] = [
  {
    id: "density_fill",
    name: "人口密度设色",
    description: "省级人口密度分级设色，与教材图例一致",
    legendTitle: "人口密度（2020）",
    legend: DENSITY_CLASSES.map((cls) => ({ color: cls.color, label: cls.label }))
  },
  {
    id: "density_3d",
    name: "密度高度映射",
    description: "人口密度拉伸为高度，直观呈现东密西疏",
    legendTitle: "人口密度 → 高度",
    legend: DENSITY_CLASSES.map((cls) => ({ color: cls.color, label: cls.label })),
    legendNote: "高度按 √密度 缩放"
  },
  {
    id: "population_columns",
    name: "人口柱体",
    description: "省级人口总量柱体，高度=人口、颜色=密度",
    legendTitle: "柱高 = 常住人口",
    legend: DENSITY_CLASSES.map((cls) => ({ color: cls.color, label: cls.label })),
    legendNote: "颜色表示人口密度分级"
  },
  {
    id: "hu_line",
    name: "胡焕庸线",
    description: "黑河—腾冲人口地理分界线及两侧对比",
    legendTitle: "胡焕庸线（1935）",
    legendNote: "黑河—腾冲参考连线；1935 年东南侧约36%国土、96%人口。不同年份口径不可混用。"
  },
  {
    id: "climate_zones",
    name: "气候区划",
    description: "中国五类主要气候类型分布（真实气候区划矢量）",
    legendTitle: "气候类型（5 类）",
    legend: [
      { color: "#e05243", label: "热带季风气候" },
      { color: "#f2a04e", label: "亚热带季风气候" },
      { color: "#f5d95c", label: "温带季风气候" },
      { color: "#b08a6a", label: "温带大陆性气候" },
      { color: "#8f7bd8", label: "高山高原气候" }
    ]
  },
  {
    id: "migration_flows",
    name: "人口迁徙",
    description: "主要区域间人口流动方向与规模（示意）",
    legendTitle: "人口迁徙流向",
    legendNote: "弧线宽度与光点表示迁徙规模（万人）。示意流线：教学演示用，非普查 OD 数据。",
    dataQuality: "estimated"
  }
];

export const GLOBE_THEME_MAP: Record<string, GlobeThemeDef> = Object.fromEntries(
  GLOBE_THEMES.map((theme) => [theme.id, theme])
);

/** 一键教学场景：主题组合 + 相机机位。 */
export const GLOBE_SCENE_PRESETS: GlobeScenePreset[] = [
  {
    id: "hu_density",
    name: "人口分布 · 胡焕庸线",
    icon: "🗺️",
    description: "密度设色 + 胡焕庸线，讲解我国人口分布大势",
    themes: ["density_fill", "hu_line"],
    camera: { lon: 103.8, lat: 36, altitudeMeters: 7_200_000, pitchDeg: -90 }
  },
  {
    id: "population_columns",
    name: "立体人口柱体",
    icon: "🏙️",
    description: "柱高比较人口总量，颜色比较密度；悬停查看各省数值",
    themes: ["population_columns"],
    camera: { lon: 106, lat: 34, altitudeMeters: 6_800_000, pitchDeg: -55 }
  },
  {
    id: "density_terrain",
    name: "密度“地形”",
    icon: "⛰️",
    description: "人口密度高度映射，东部隆起如山脉",
    themes: ["density_3d", "hu_line"],
    camera: { lon: 104, lat: 30, altitudeMeters: 8_600_000, pitchDeg: -78 }
  },
  {
    id: "migration",
    name: "人口迁徙流动",
    icon: "🔀",
    description: "区域间迁徙弧线动画，理解人口流动方向",
    themes: ["migration_flows", "density_fill"],
    camera: { lon: 106, lat: 31, altitudeMeters: 7_800_000, pitchDeg: -80 }
  },
  {
    id: "climate_pop",
    name: "气候 × 人口",
    icon: "🌦️",
    description: "气候区划叠加胡焕庸线，探究自然因素影响",
    themes: ["climate_zones", "hu_line"],
    camera: { lon: 103.8, lat: 36, altitudeMeters: 7_200_000, pitchDeg: -90 }
  }
];

// ── Manager ─────────────────────────────────────────────────────────

/**
 * Owns the lifecycle of theme data sources on a Cesium viewer. Handles
 * async loads racing against toggles: if a theme is switched off while
 * its data is still loading, the loaded handle is disposed on arrival.
 */
export class GlobeThemeManager {
  private viewer: Cesium.Viewer;
  private handles = new Map<GlobeThemeId, ThemeHandle>();
  private loading = new Map<GlobeThemeId, Promise<void>>();
  private wanted = new Set<GlobeThemeId>();
  private destroyed = false;
  private onError?: (themeId: GlobeThemeId, message: string) => void;
  private removeLabelLayout: () => void;
  private measure = document.createElement("canvas").getContext("2d");

  constructor(viewer: Cesium.Viewer, onError?: (themeId: GlobeThemeId, message: string) => void) {
    this.viewer = viewer;
    this.onError = onError;
    this.removeLabelLayout = viewer.scene.preRender.addEventListener(() => this.layoutLabels());
  }

  private layoutLabels(): void {
    const labels = [...this.handles.values()].flatMap(handle => handle.labels || []);
    if (!labels.length || !this.measure) return;
    const scene = this.viewer.scene, time = this.viewer.clock.currentTime;
    const boxes: LabelBox[] = [];
    const occluder = new Cesium.Occluder(new Cesium.BoundingSphere(Cesium.Cartesian3.ZERO, scene.globe.ellipsoid.minimumRadius), scene.camera.positionWC);
    for (const entity of labels) {
      const position = entity.position?.getValue(time);
      if (!position || !occluder.isPointVisible(position)) continue;
      const point = Cesium.SceneTransforms.worldToWindowCoordinates(scene, position);
      if (!point) continue;
      const label = entity.label!;
      this.measure.font = label.font?.getValue(time) || LABEL_FONT;
      const width = this.measure.measureText(label.text?.getValue(time) || "").width + 18;
      boxes.push({id:entity.id, left:point.x-width/2, top:point.y-39, width, height:31});
    }
    const visible = selectVisibleLabels(boxes, scene.canvas.clientWidth, scene.canvas.clientHeight);
    for (const entity of labels) {
      const show = visible.has(entity.id);
      if (entity.label!.show?.getValue(time) !== show) entity.label!.show = new Cesium.ConstantProperty(show);
    }
  }

  syncThemes(ids: string[]): void {
    if (this.destroyed) return;
    const next = new Set(
      ids.filter((id): id is GlobeThemeId => id in THEME_BUILDERS)
    );
    this.wanted = next;
    for (const [id, handle] of [...this.handles]) {
      if (!next.has(id)) {
        this.disposeHandle(handle);
        this.handles.delete(id);
      }
    }
    for (const id of next) {
      if (!this.handles.has(id) && !this.loading.has(id)) {
        const task = THEME_BUILDERS[id]()
          .then((handle) => {
            this.loading.delete(id);
            if (this.destroyed || !this.wanted.has(id)) {
              this.disposeHandle(handle);
              return;
            }
            this.handles.set(id, handle);
            for (const ds of handle.dataSources) {
              void this.viewer.dataSources.add(ds);
            }
            this.viewer.scene.requestRender();
          })
          .catch((error) => {
            this.loading.delete(id);
            const message = error instanceof Error ? error.message : String(error);
            this.onError?.(id, message);
          });
        this.loading.set(id, task);
      }
    }
    this.viewer.scene.requestRender();
  }

  destroy(): void {
    this.destroyed = true;
    this.removeLabelLayout();
    this.wanted.clear();
    for (const handle of this.handles.values()) {
      this.disposeHandle(handle);
    }
    this.handles.clear();
  }

  private disposeHandle(handle: ThemeHandle): void {
    for (const ds of handle.dataSources) {
      try {
        this.viewer.dataSources.remove(ds, true);
      } catch {
        /* viewer already torn down */
      }
    }
    if (!this.destroyed) {
      this.viewer.scene.requestRender();
    }
  }
}
