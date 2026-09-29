# 上海 2020 年 WorldPop ~100m 人口数据包（构建、部署与验收）

## 数据源与版本锁定

| 项 | 值 |
| --- | --- |
| 产品 | WorldPop Global 2015–2030 Individual countries, 100m, **R2025A v1（alpha，仍可能更新）** |
| 文件 | `chn_pop_2020_CN_100m_R2025A_v1.tif`（全国，约 877 MB，3 角秒 ≈100m，WGS84） |
| 原始单位 | **每像元估计人数**（persons per pixel） |
| 下载 | <https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2020/CHN/v1/100m/constrained/chn_pop_2020_CN_100m_R2025A_v1.tif> |
| 页面 | <https://hub.worldpop.org/geodata/summary?id=72922> |
| 方法与限制 | [Global2 Release Statement R2025A](https://data.worldpop.org/repo/prj/Global_2015_2030/R2025A/doc/Global2_Release_Statement_R2025A_v1.pdf) |
| 许可 | CC BY 4.0　DOI: 10.5258/SOTON/WP00839 |

引用（CC BY 4.0 署名要求）：

> WorldPop (www.worldpop.org - School of Geography and Environmental Science, University of
> Southampton; Department of Geography and Geosciences, University of Louisville; Département de
> Géographie, Université de Namur) and Center for International Earth Science Information Network
> (CIESIN), Columbia University (2025). Global 2015-2030 R2025A. DOI:10.5258/SOTON/WP00839.

## 构建（一次性预处理，可复现）

```powershell
# 构建依赖（仅脚本需要；运行时为零依赖纯 Python 读取器）
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pip install -r scripts/requirements-geodata.txt rasterio

# 1) 下载原始全国 GeoTIFF 到仓库外任意目录（原始文件不入 Git）
# 2) 裁剪 + 面积换算 + 写包（数据包落在 <data-dir>/population/shanghai_worldpop_2020/）
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" scripts/build_shanghai_worldpop_2020.py `
    --tif D:\data\chn_pop_2020_CN_100m_R2025A_v1.tif `
    --data-dir backend/data
```

脚本行为：

- 从 `backend/app/data/builtin/one_map/boundaries/shanghai_districts.geojson` 求全市 bbox 并外扩 0.02°；
- 逐行按像元中心纬度用 `cell_area_km2`（球面近似，随纬度变化）把“每像元人数”换算为 **人/km²**；
- 写出自描述包：`package.json`（含来源/授权/换算方法/SHA-256/校验值）+ `density.f32`（float32 小端、北→南、nodata=NaN）；
- 打印校验值：估算总人口、像元数、nodata 数，并与 **2020 年七普上海 24,870,895 人** 对照（比值写入 `package.json.validation.ratio_vs_census`）。

## 部署与验收（部署包单独验收项）

1. 数据包位于运行数据目录：`<WEBGIS_AI_DATA_DIR 或 backend/data>/population/shanghai_worldpop_2020/`（`package.json` + `density.f32`）。
2. 启动后 `GET /population-raster/packages` 应返回该包的 `package_id/title/year=2020/resolution_m=100/caveats`。
3. 打开 2D 地图 → 测距（M）画一条上海测线 → 剖面小窗数据源选「上海 2020 年人口网格」→ 人口密度变化：
   - 图表正常渲染，nodata 点标注「无数据 N 点，不作推断」；
   - 脚注完整显示：来源 WorldPop、年份 2020、分辨率 ~100 米、**「原始每像元估计人数已按像元实际面积换算为人/km²，非逐建筑实测」**、alpha 声明与 CC BY 4.0 署名链接。
4. `package.json.validation.ratio_vs_census` 应接近 1（WorldPop 为估计值，允许小幅偏差；显著偏离时检查 bbox 与源文件版本）。

## 表述红线

- 该数据是**统计估计栅格**（随机森林再分配方法），**不得称为逐建筑或实测人口数据**；
- 课堂与图表必须标注：来源、年份（2020）、分辨率（~100 米）、估计属性、nodata 点数；
- 原始全国 GeoTIFF 不入 Git，仅交付裁剪脚本 + 数据包 + 校验值。

## 运行时读取

- 读取器：`backend/app/services/raster_dataset.py`（纯标准库：按需 seek 逐点取样，不整包载入）；
- 剖面：`map_profiles.py` 新增 `kind=population, source_id=shanghai_worldpop_2020`（本地取样，无外网请求）；
- 未部署时剖面返回明确错误（SOURCE_UNAVAILABLE），前端显示提示，不影响其他数据源；
- 现有来源（GPW 点查、行政区密度面）全部保留，可在剖面窗口数据源下拉中切换。
