# One Map Missing Data Requirements

Last updated: 2026-09-09

| Data | Target format | Recommended source | Missing reason | Manual required | Status |
| --- | --- | --- | --- | --- | --- |
| ~~中国城市人口数据~~ | ~~CSV/GeoJSON~~ | ~~第七次全国人口普查~~ | ~~已从 人口课程数据 补入~~ | - | **filled** |
| ~~中国省级 GDP 数据~~ | ~~GeoJSON~~ | ~~全球分省人均GDP 1990-2022~~ | ~~已从 人口课程数据 补入~~ | - | **filled** |
| ~~中国地级市 GDP 数据~~ | ~~GeoJSON~~ | ~~立方数据学社 1990-2023~~ | ~~已从 人口课程数据 补入~~ | - | **filled** |
| 中国年降水量数据 | GeoJSON/COG/TIF | DWD / GPCC V2025，1991—2020，0.25° | 已补400毫米等值线及方法、许可；完整降水面图/数值查询尚未接入 | no | partial：china_precipitation_400mm |
| 中国 1 月/7 月平均气温数据 | GeoJSON/COG/TIF | WorldClim v2.1 monthly tavg zonal stats | large raster; not bundled in first pass | no | open |
| 中国主要交通线数据 | GeoJSON | OSM/official railway-road network | license/source choice needs confirmation | no | open |
| 世界年降水量数据 | GeoJSON/COG/TIF | WorldClim v2.1 precipitation by country | large raster; generate by zonal_stats when cached | no | open |
| 世界气温数据 | GeoJSON/COG/TIF | WorldClim v2.1 tavg by country | large raster; generate by zonal_stats when cached | no | open |
| 世界夜间灯光数据 | GeoJSON/COG/TIF | EOG VIIRS annual VNL | large raster and download policy review required | no | open |
| 上海市 GDP 数据 | CSV/GeoJSON | 上海统计年鉴/国家数据 | requires official table export | yes | open |
| 上海轨道交通或中心城区范围 | GeoJSON | 上海开放数据/OSM | source/license not selected | no | open |

## 非测绘级数据的真实数据替换计划（2026-07-27 审计）

以下条目当前以 schematic/estimated 状态提供（前端"可视化地图"面板已显示"示意/估算"徽标），
替换为真实数据的可行路径与优先级如下。生成脚本可复用 `scripts/ingest_natural_themes.py`
的下载→裁剪→简化→写 catalog 范式（`_fetch_ne_rivers`/`build_climate_types`/`update_catalog`）。

| 数据集 | 现状成因 | 真实替代源（免费/可离线） | 获取难度 | 优先级 |
| --- | --- | --- | --- | --- |
| `china_migration_flows`（estimated） | 4 条手绘直线连 7 大区中心，migrants 为整十估值 | **五普/六普/七普省际人口迁移 OD 矩阵**（普查长表公开统计），按省对绘制真实加权弧线；弧线渲染 `globeThemes.ts` 已就绪可直接复用 | 需数据整理（录入 OD 表） | **高**（教学含金量最高，一次把估算升为真实普查数据） |
| `china_vegetation_zones`（schematic） | 省 adcode→植被带字典 + 省界 dissolve（`ingest_natural_themes.py` `_dissolve_provinces_by`） | **WWF Olson 陆地生态区/生物群系**（现成矢量，公开），裁剪中国 + 重分类到教学 6 带 | 可直接下载 | 中 |
| `china_terrain_steps`（schematic） | 省 adcode→阶梯字典 + 省界 dissolve；东部省 fillna 一刀切 | SRTM/GEBCO 公开 DEM 重分类高程带（<500/500-2000/>3000m）后矢量化平滑；或据 DEM 晕渲手工数字化两条阶梯界线（昆仑-祁连-横断、大兴安岭-太行-巫山-雪峰） | 需矢量化 | 中 |
| `teaching_maps` 16 张课本扫描图 | 仅 bbox bounds 目测配准（多张中国图共用粗框），无地面控制点 | 在现有 bounds 基础上为每张图加 2-3 对 GCP 做仿射配准（对照矢量底图可识别点） | 需人工点控制点 | 低（扫描图已从课程主路径退役） |
| `china_major_rivers` 要素级 source_name 写 `ne_50m` 与 catalog 的 `ne_10m` 不一致 | 文档瑕疵 | 重跑 ingest 或批量改 properties | 一行修正 | 低 |

注：`china_climate_types` 为真实气候矢量（5 类），无需替换——前端曾存在的"热带雨林"死配色
与"（省级精度）"过时描述已于 2026-07-27 修正（`globeThemes.ts`）。

## Filled from 人口课程数据 (2026-06-13)

| Dataset | Source file | Catalog ID |
| --- | --- | --- |
| 中国城市人口（七普 353 城） | `全国地级市 2020 七普人口数据.xlsx` | `china_city_population_2020` |
| 中国省级人均 GDP（31 省含边界） | `polyg_adm1_gdp_perCapita_1990_2022.gpkg` | `china_province_gdp_per_capita` |
| 中国地级市人均 GDP（375 城含边界） | `1990-2023年我国地级市人均GDP数据.shp` | `china_city_gdp_per_capita` |
| 中国气候类型分布（9 类省级） | `中国气候类型分布.zip` | `china_climate_types` |

## 2026-09-09 降水对照补充

已联网核验并补入 GPCC 400毫米年降水量对照线，详见 [数据方法与复现](climate/china_precipitation_400mm.md)。WorldClim 2.1 官方禁止未经许可再分发，故未将其资料打包；改用 DWD 明确允许 CC BY 4.0 署名复用的 GPCC 数据。400毫米对照线不等于完整自然专题资料已补齐，未把其他气温、地形或三维数据标为完成。
