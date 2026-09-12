# 人口专题 GIS 工作流端到端覆盖与优化 — QA 记录

- 分支:`codex/zcode-population-workflow`(基于 origin/main `028e0db`)
- 日期:2026-09-11
- 实测环境:Windows 11,真实 QGIS 3.40.10(`D:\QGIS 3.40.10`,OSGeo4W 布局,自带 Python 3.12.11),后端测试用 Python 3.12.10
- 测试数据:仓库内置人口数据集(一张图省级人口密度 34 要素、大区中心点、迁徙连线),未触碰教师上传数据

## 1. 七模板覆盖表

覆盖级别说明:

- **已实际运行** = 在真实 QGIS worker 上端到端执行成功,并核对了产物文件与数据库镜像;
- **仅校验** = 只过了结构校验/模板展开,未起真实 worker;
- **受数据或 QGIS 环境限制** = 当前环境无法真实执行的部分。

| 模板 | 覆盖级别 | 实测结果(真实 QGIS) | 校验要点 |
| --- | --- | --- | --- |
| `population_choropleth` | 已实际运行 | success,34 要素,产物 geojson+style+stats+png,数据库镜像 3 条 | 默认密度字段;`area_field` 变体(先算密度再分级)同样 success |
| `facility_buffer` | 已实际运行 | success,300km 缓冲 dissolve=1 要素,镜像 2 条 | 消息里"300公里"距离解析;auto_project 处理 4326 |
| `hu_line_compare` | 已实际运行 | success,9 步全绿;东 25 省 11.88 亿人 / 西 9 省 2.50 亿人,两侧互斥合计 34 省 | **修复后**真实几何分侧(见 §2);东侧含上海、西侧含新疆 |
| `clip_to_region` | 已实际运行 | success,7 个中心点全部落在省域内,镜像 2 条 | 点层被面层裁剪 |
| `overlay_intersection` | 已实际运行 | success,迁徙连线与省域求交得 24 段,镜像 2 条 | 线×面交集,属性合并(`_2` 后缀由 QGIS 处理) |
| `spatial_join_attributes` | 已实际运行 | success,7 个中心点全部连上省属性,镜像 2 条 | intersects 谓词,1_to_1 |
| `classify_field` | 已实际运行 | success,`population_class` 取值 0–4,镜像 2 条 | 5 级 jenks,导出 geojson 含分级列 |
| (保留 op:`heatmap` / `add_label` / `export_layout_pdf`) | 仅校验 | 提交前即被拒绝,报「操作尚未实现」 | 不再放行到 worker 才失败 |

每条已运行工作流按任务要求核对了:

1. **参数校验**:结构校验(缺必填参数、未知 op)在提交时同步报错,不启动后台任务;
2. **进度事件**:`workflow_created → workflow_started → step_started → step_success(/artifact_ready)→ workflow_success` 事件链完整(单测断言);
3. **取消和失败状态**:stub 注入 `PROCESSING_FAILED` → 工作流 `error`;注入 `STEP_CANCELLED` → 工作流进入专门的 **`cancelled`** 状态(新),不再是笼统的 error;
4. **结果文件注册**:geojson/style/stats/png 产物逐类注册到 `WorkflowRecord.artifacts`,并镜像到 RuntimeStore(数据库面板可查,按 workflow_id 幂等去重);
5. **地图与数据库识别**:前端 `WorkflowDock` 按 geojson+style 产物渲染分级设色图层(现有行为,回归确认);数据库面板镜像数量与产物类别一致(见上表 mirror 列);
6. **错误可读性**:所有错误路径都有 `user_friendly` 中文文案;预检错误会**指出缺什么**(数据集名/字段名+步骤 id+可用字段列表)。

## 2. 修复的人口工作流断点

1. **`hu_line_compare` 名不副实(核心断点)**:模板标题与统计名叫"胡焕庸线两侧",但步骤里**没有任何东西部划分**——只是全国分级设色 + 全省混排统计,课堂演示讲不出"东西对比"。
   修复(仅改模板,不动执行器):新增 `calculate_field` 用质心相对胡焕庸线(黑河 127.5°E,50.2°N → 腾冲 98.5°E,24.7°N)的符号判断写入 `hu_side` 字段;新增东/西两侧 `filter_features` + 各自 `export_geojson`(真实分侧文件);统计步骤以 `hu_side` 为标签字段、保留省份名列。实测分侧比例 25:9(人口 11.88 亿:2.50 亿),与胡线经典格局一致。
2. **未实现操作放行到后台才失败**:`heatmap` 等保留 op 此前能通过校验、进入 worker 后才报 `UNKNOWN_OP`。现改为校验期直接拒绝(`STEP_OP_NOT_IMPLEMENTED`),普通教师能在提交时看到「操作尚未实现」。
3. **缺参/预检错误的提示太笼统**:校验失败时 toast 只有"工作流校验未通过"。现在会把具体问题(哪个步骤、缺什么参数/字段、可用字段有哪些)拼进 `user_friendly`。
4. **取消被当成失败**:教师取消后状态是 `error` ❌。现在执行器区分 `STEP_CANCELLED`,工作流状态改为 `cancelled`,前端面板显示 ⏹️ 已取消(全局与步骤级),并提示"可以调整参数后重新提交"。
5. **测试基建**:此前 executor 单测使用不存在的 `demo.geojson` 数据源——恰恰是现在预检要拦的模式,已改为在临时 uploads 里写入真实小数据集。

## 3. 新增参数预检(小而实用)

`workflow_executor.run_preflight` 在**启动后台任务之前**执行(结构校验通过后):

- **输入图层**:`builtin:` / `upload:` / 裸文件名解析(与 worker 解析规则一致);找不到 → `DATASET_NOT_FOUND`,报错里带数据集名与步骤 id;
- **字段**:choropleth/classify 的分级字段、aggregate_stats 的统计与标签字段、calculate_field/filter_features 表达式里的 `"..."` 引用,沿 `${step.key}` 引用链回溯到数据集后逐一核对;字段缺失 → `FIELD_NOT_FOUND`,报错里列出**可用字段**;
- **CRS**:GeoJSON 声明的坐标系若非 EPSG:4326/CRS84 → **警告**(不阻断),提示结果位置可能偏离底图;
- **保留已填参数**:预检失败不同步清空前端表单(验证:提交失败后输入框内容保留,教师修正后可直接重跑);
- **不提交注定失败的任务**:预检失败的工作流同步落库为 error 并回放 `workflow_created + workflow_error` 事件,**不启动执行线程**(测试断言 stub worker 零调用);
- 明确不做的:不做表达式语义分析、不预跑 QGIS——预检保持廉价,权威校验仍在 worker。

## 4. 测试矩阵与验证命令

`backend/tests/test_workflow_population_templates.py`(新增):

- 三条人口核心工作流(population_choropleth / hu_line_compare / classify_field)各含 **success / 缺参 / 执行失败** 三类用例;
- 预检:缺数据集、缺字段(报可用字段)、表达式字段拼写错误、CRS 警告不阻断、保留 op 拒绝、合法数据集零告警;
- 取消:stub 取消 → `cancelled` 状态 + 终止事件携带 record;
- 模板覆盖:7 模板全部展开并通过校验;hu_line 结构断言(必须真分侧);
- **真实 QGIS 门控套件**(`RealQgisPopulationRunTests`,设 `QGIS_ROOT` 即运行,否则 skip):三条工作流真实 worker 运行,断言东/西两侧文件互斥、合计 34 省、上海在东/新疆在西、`population_class` 0–4。

前端:`WorkflowDock.test.tsx`(cancelled 面板文案、预检失败 toast + 表单保留)、`useWorkflowStream.test.ts`(cancelled 状态透传)。

验证结果(详见 handoff):

```
后端全量:pytest backend/tests -q → 全绿(含 QGIS_ROOT 开启时的真实运行用例)
前端:npm test 全绿;npm run build 成功;git diff --check 干净
```

## 5. 已知限制与后续建议

- `aggregate_stats` 产物文件名固定为 `stats.json`,同一工作流里第二个统计步骤会覆盖前一个的文件(本次通过"单统计步骤+标签列"绕开;若将来需要双统计卡,应在 handler 层支持自定义输出名);
- 预检只读 GeoJSON(≤32MB),Shapefile/GPKG 等格式的字段核对留待 worker 权威校验;
- 数据库镜像依赖 `store.register_artifact`,项目不存在时会静默失败(仅影响伪项目;生产提交已校验项目归属,未改动不在授权清单内的 store.py);
- 前端仍未提供取消按钮(取消走 `POST /workflow/{id}/cancel`,CSRF token 封装在 api.ts 内,本次无权限扩展 api.ts);
- `classify_field` 无 `export_map_png` 步骤,地图 PNG 仅人口分级设色模板提供(现状,未改动)。
