# One Map Missing Data Requirements

Last updated: 2026-06-13

| Data | Target format | Recommended source | Missing reason | Manual required | Status |
| --- | --- | --- | --- | --- | --- |
| ~~中国城市人口数据~~ | ~~CSV/GeoJSON~~ | ~~第七次全国人口普查~~ | ~~已从 人口课程数据 补入~~ | - | **filled** |
| ~~中国省级 GDP 数据~~ | ~~GeoJSON~~ | ~~全球分省人均GDP 1990-2022~~ | ~~已从 人口课程数据 补入~~ | - | **filled** |
| ~~中国地级市 GDP 数据~~ | ~~GeoJSON~~ | ~~立方数据学社 1990-2023~~ | ~~已从 人口课程数据 补入~~ | - | **filled** |
| 中国年降水量数据 | GeoJSON/COG/TIF | WorldClim v2.1 precipitation zonal stats | large raster; not bundled in first pass | no | open |
| 中国 1 月/7 月平均气温数据 | GeoJSON/COG/TIF | WorldClim v2.1 monthly tavg zonal stats | large raster; not bundled in first pass | no | open |
| 中国主要交通线数据 | GeoJSON | OSM/official railway-road network | license/source choice needs confirmation | no | open |
| 世界年降水量数据 | GeoJSON/COG/TIF | WorldClim v2.1 precipitation by country | large raster; generate by zonal_stats when cached | no | open |
| 世界气温数据 | GeoJSON/COG/TIF | WorldClim v2.1 tavg by country | large raster; generate by zonal_stats when cached | no | open |
| 世界夜间灯光数据 | GeoJSON/COG/TIF | EOG VIIRS annual VNL | large raster and download policy review required | no | open |
| 上海市 GDP 数据 | CSV/GeoJSON | 上海统计年鉴/国家数据 | requires official table export | yes | open |
| 上海轨道交通或中心城区范围 | GeoJSON | 上海开放数据/OSM | source/license not selected | no | open |

## Filled from 人口课程数据 (2026-06-13)

| Dataset | Source file | Catalog ID |
| --- | --- | --- |
| 中国城市人口（七普 353 城） | `全国地级市 2020 七普人口数据.xlsx` | `china_city_population_2020` |
| 中国省级人均 GDP（31 省含边界） | `polyg_adm1_gdp_perCapita_1990_2022.gpkg` | `china_province_gdp_per_capita` |
| 中国地级市人均 GDP（375 城含边界） | `1990-2023年我国地级市人均GDP数据.shp` | `china_city_gdp_per_capita` |
| 中国气候类型分布（9 类省级） | `中国气候类型分布.zip` | `china_climate_types` |
