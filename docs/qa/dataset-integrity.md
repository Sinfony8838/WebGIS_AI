# 数据导入完整性 QA（dataset-import-integrity）

任务分支：`claude/dataset-import-integrity`
起始基线：`origin/main` = `00bb920`
日期：2026-09-08

## 1. 范围与目标

数据导入后位置正确、字段完整、数据损失可解释；失败不留下半成品。
允许修改的文件：`backend/app/services/datasets.py`、`crs_detector.py`、
`crs_reprojector.py`、`frontend/src/components/UploadDialog.tsx`（及专属样式/
测试）、对应既有测试、`backend/tests/dataset_integrity/`、
`scripts/qa/dataset_integrity/`、本文档。

## 2. 发现的真实缺口（基线 00bb920）

1. **失败残留**：`import_upload` 先把原始字节写入 uploads 目录再解析；解析
   失败后文件留在磁盘上（半成品）。
2. **CSV 丢行不可见**：非法/越界行被静默跳过，界面显示“全部成功”。
3. **CSV 编码单一**：只支持 UTF-8/BOM，中文 Excel 常见的 GB18030、UTF-16
   导出直接抛 `UnicodeDecodeError`。
4. **pyshp NULL Shape 崩溃**：含空几何的 Shapefile 在
   `__geo_interface__` 处抛 `GeoJSON_Error`，整个导入失败。
5. **pyshp 构造期解码失败泄漏句柄**：GBK 属性表 + UTF-8 Reader 在 Windows
   上让临时解压目录无法删除。
6. **ZIP 防护不全**：未限制条目数/解压总大小；多个 `.shp` 时静默取第一个
   （多图层歧义）；缺 `.shx`/`.dbf` 时报库内部错误而非友好提示。
7. **CRS 标签不诚实**：pyproj 缺失时投影坐标原样存储，但 `stored_crs` 仍写
   `EPSG:4326`（只改标签未转换坐标）。
8. **边界未校验**：图片叠加 bounds 未检查顺序/范围；CSV 缺少经纬度反置的
   可解释跳过原因。
9. **重复导入行为未定义**：同名图层反复累积，无法区分。
10. **上传界面无错误反馈**：提交失败时对话框静默停留，无任何提示。

## 3. 实施内容

### backend/app/services/datasets.py（重构）

- **两阶段导入**：全部解析/校验/转换在内存中完成后才写盘。任何失败在
  uploads 目录零残留（文件、兄弟 GeoJSON、临时解压目录均不产生或已清理）。
- **CSV 行报告** `row_report`：`total_rows / imported_rows / skipped_rows /
  skip_reasons`（坐标缺失、坐标不是有效数字、坐标超出经纬度范围、疑似经纬度
  反置、空行）。部分失败照常导入有效行并返回统计——不再悄悄丢行。
  全部被跳过时抛出含主导原因与建议的中文错误；投影坐标（|值|≥1000）触发
  `CrsAssumptionError`（保留原有对外错误类型与文案）。
- **编码链**：UTF-16 BOM → utf-8-sig → gb18030 → latin-1（保底），编码名记入
  元数据与报告；CSV 经/纬列新增中文别名 `经度/纬度`。
- **GeoJSON 要素报告** `feature_report`：缺失几何/非法要素按条跳过并计数；
  空集合、非法 JSON 给出中文错误（含行列号）。
- **ZIP 加固**：条目数 ≤2000、解压总量 ≤512 MB、单条目 ≤256 MB；`__MACOSX`/
  隐藏目录排除；多个 `.shp` 报歧义（列出文件名）；缺 `.shx`/`.dbf` 报缺少
  配套文件；`.prj` 与所选 `.shp` 同名配对；NULL Shape 跳过并计数；DBF 编码
  先探测（UTF-8 → GB18030）再构造 Reader，中文属性不乱码。
- **CRS 诚实标签**：`crs_converted` 与 `stored_crs` 如实反映转换结果。源
  CRS ≠ 4326 且未能转换（pyproj 缺失/失败）时，`stored_crs` 保留源 CRS、
  图层隐藏（`visible=false`），并给出中文提示——绝不只改标签不转坐标。
- **范围诊断（仅警告，不改坐标）**：`COORD_RANGE_SUSPECT`（未声明 CRS 且坐
  标越界）、`COORD_RANGE_CONFLICT`（声明 4326 但坐标越界）、
  `REPROJECTION_SUSPECT`（转换后仍越界）。数值范围永远不被当作确认 CRS 的
  依据。
- **重复导入**：同名图层自动命名为“名称 (2)”、“(3)”，元数据记录
  `duplicate_import/renamed_from`，两份文件均保留在磁盘。
- **结果消息**：自然中文汇总，例如“成功导入 980 条记录，20 条被跳过（7 条
  坐标缺失、…）；坐标按 EPSG:4326 处理。”

### backend/app/services/crs_detector.py

- `classify_coordinate_pair`：逐行分类 ok / suspected_swap / out_of_range。
- `summarize_geojson_coord_range`：采样扫描坐标范围异常（仅诊断）。

### backend/app/services/crs_reprojector.py

- 报告新增 `features_total / features_transformed / features_untouched`，
  如实统计实际转换的要素数。

### frontend/src/components/UploadDialog.tsx（+.css）

- 提交失败在对话框内显示中文错误（此前静默无反馈），可修改后重试。
- 后端返回导入结果时展示完整中文报告：总行/成功/跳过、跳过原因明细、来源
  CRS → 存储 CRS、是否已转换、全部 CRS 警告。
- CSV 经/纬字段默认改为留空自动识别（此前硬编码 lat/lon 会导致中文列文件
  导入失败）；上传期间按钮显示“正在导入…”并禁用。
- 新增 `frontend/src/__tests__/UploadDialog.test.tsx`（10 个用例）。

## 4. 样本覆盖（36 类，全部程序化生成）

生成器：`scripts/qa/dataset_integrity/sample_factory.py`；
CLI：`generate_samples.py --out <dir>`（含 manifest.json 与每类预期结果）。
覆盖：中文字段、UTF-8/BOM/GB18030/UTF-16、引用字段、空值、非法数字、经纬
度反置、越界坐标、投影坐标误当经纬度、空几何、复杂几何（带洞 MultiPolygon、
GeometryCollection）、显式/缺失/冲突 CRS、EPSG:4326、EPSG:3857、EPSG:32650、
CGCS2000（EPSG:4490、EPSG:4547）、pyproj 不可用、ZIP 路径逃逸/炸弹/多图层/
缺配套/嵌套目录/GBK DBF、图片 bounds 全部非法形态。合计 36 类。

## 5. 验收测试

`backend/tests/dataset_integrity/`：71 个用例，全部通过
（`python -m pytest backend/tests -q` → 533 passed + 9 subtests）。
测试使用独立的临时状态目录、独立项目，不接触真实课堂数据。

## 6. 坐标转换精度（`verify_crs_accuracy.py`，4/4 通过）

| 用例 | 控制依据 | 容差（度） | 实测最大误差 |
| --- | --- | --- | --- |
| EPSG:3857 → 4326 | 球面 Web Mercator 闭式公式 | 1e-6（≈0.1 m） | 1.8e-14（纬度） |
| EPSG:32650 → 4326 | 中央经线不变量 + 直接 pyproj 对照 | 1e-7（≈1 cm） | 0（经度差、对照差） |
| EPSG:4547 → 4326 | CGCS2000 3° 带中央经线定义不变量 | 1e-7 | 1.4e-14 |
| EPSG:4490 → 4326 | CGCS2000/WGS84 实现差（亚米级） | 1e-5（≈1 m） | 0 |

往返闭合（4326→源→4326）全部 ≤ 1.4e-9 m（容差 1e-3 m）。

## 7. 性能对比（`benchmark_import.py`，基线 00bb920，5 次取中位）

| 样本 | 基线耗时 | 当前耗时 | 基线峰值内存 | 当前峰值内存 | 一致性 |
| --- | --- | --- | --- | --- | --- |
| CSV 20,000 行 | 5.19 s | 5.04 s（×1.03） | 32.9 MiB | 32.9 MiB | 要素数/坐标哈希一致 |
| GeoJSON 5,000 面（32650→4326） | 1.81 s | 1.40 s（×1.29） | 19.9 MiB | 15.5 MiB | 要素数/坐标点数一致 |

优化手段：导入改为内存解析避免整文件二次读取；兄弟 GeoJSON 由
`json.dumps+write_bytes` 改为流式 `json.dump`；CSV 由整表 DictReader 物化
改为流式逐行。未丢字段、未降精度、未删几何（指纹一致性由脚本验证）。

## 8. 浏览器实测

通过真实浏览器在隔离端口（后端 19122 / 前端 5192）以独立用户/项目执行上传，
覆盖：合法 CSV 位置与属性、混合有效性 CSV 的中文统计反馈、投影 CSV 的失败
提示、ZIP Shapefile 地图位置。证据与结论见 PR 描述。

## 9. 集成需求（需要共享文件接线，本任务未抢改）

1. **App.tsx + api.ts**：`handleUploadDataset` 目前丢弃 `/datasets/upload`
   响应体。接口已就绪（响应含 `layer/crs/row_report/feature_report/message`）。
   需求：`uploadDataset` 返回完整响应体并透传给 `UploadDialog.onSubmit` 的
   resolve 值；对话框即可展示“成功导入 980 条…”的完整报告（组件已支持，
   见 `UploadDialog.test.tsx` 最后两个用例）。未接线时对话框保持原有“成功
   即关闭”行为，不影响现有交互。
2. **runtime.py（可选）**：`set_job_status` 的 `summary` 目前仅含图层名；可
   改用 `result["message"]` 让任务流/助手消息呈现同样的中文统计。

## 10. 未完成事项与风险

- 图片叠加仍按 bounds=WGS84 经纬度解释（无世界文件解析）；界面上已明示。
- GeoJSON 内嵌 `.crs` 为非 EPSG 授权（如 ESRI 编码）时按未声明处理（保守）。
- 大于 512 MB 解压总量的 ZIP 被拒绝；如课堂确有超大矢量需求需另行评估流式
  OGR 管线。
- CSV 千分位（“1,234.5”）等区域格式数字未支持。
