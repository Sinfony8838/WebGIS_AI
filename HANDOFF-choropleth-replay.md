# 交接文档 — claude/choropleth-replay(QA 轮 + 优化轮)

交接下来处理的 agent(Codex)。本文档总结了 2026-09-07/08 两轮工作:实机测试结果、已落地的修复、以及**未解决/未覆盖**的清单。

## 分支状态

- 分支 `claude/choropleth-replay`,工作树 `..\WebGIS-AI-worktrees\claude-choropleth-replay`
- 本地提交:c83ce28(merge origin/main)← 86cb346(QA 优化轮)← 91c9c63(credentials 修复)← 07985fc(制图回放功能)
- 合并了 main 的语音交互功能(853595e),合并后全绿
- 注意:截至交接时 `git push` 因 github.com:443 不可达失败,提交仅在本地,**需补推**

## 已完成的实机测试(独立测试栈 19000/5175,QGIS_ROOT=D:\QGIS 3.40.10)

| 项 | 结果 |
|---|---|
| GIS 工作流模板 ×7(/workflow/submit) | 7/7 成功;热运行 0.5~1.3s;产物完整 |
| 课堂地图模板 ×5(/templates/{id}/run) | 5/5 completed,图层正确生成 |
| 2D 目录图层 ×17(/datasets/catalog/layers) | 17/17 API 成功;9 个已截图目检渲染正常 |
| 三维主题 ×6 + 场景预设 ×5 | 6/6 + 5/5 通过(Cesium dataSources 实体数与相机坐标验证) |
| 教学地图叠加 ×15 | 补私有图片资产后 15/15 可服务;toggle 正常 |

测试脚本:`scripts/test_workflow_matrix.py`、`scripts/run_workflow_timed.py`、`scripts/set_layer_visibility.py`。
测试账号 claude-test@example.com / Test-Replay-2026!(测试库)。

## 本轮已落地的修复/优化(提交 86cb346)

1. 工作流产物 401 修复(91c9c63):WorkflowDock 四处产物 fetch 补 credentials:"include"。
2. 制图回放动画(07985fc):choropleth 结果在 2D 地图逐级填色回放 + 图例生长。
3. 分析类模板补样式:buffer/clip/intersection/join 输出 simple style;classify 输出 graduated style.json(此前全部灰图)。
4. WorkflowDock 支持 simple 样式与点要素渲染(此前 Point 几何在 Fill/Stroke 样式下不可见)。
5. 教学地图缺图状态化:list/get 返回 available;toggle 对缺图报友好错误;DatabaseViewer 显示"缺图"。
6. VisualMapPanel 目录加载失败显示错误态 + 重试(原来无限"加载中")。
7. 程序性视野守卫:服务端 fit/teaching-map 飞行后 2.5~3s 内抑制"zoom<3 自动切 3D",修复世界范围 2D 图层加载即被藏到地球后的问题。
8. 边界类目录图层(boundaries)描边化,不再被数值字段分级填色。
9. **store 性能修复**:大图层 data.features 外置到 state/layer_data/*.json(按 data_rev 缓存),runtime.json 从 25.3MB 降到 3.2MB。此前每个地级市 GDP 图层内联 7.7MB,任何一次状态保存都全量重写,拖慢所有 API。
10. worker workflow.log 增加时间戳(可观测性)。

## 未解决 / 未完成(交由 Codex)

### P1 — 工作流热运行延时回退(未修,根因已大幅收窄)
- 现象:上午热运行 0.61s/条;下午起每步固定 ~4s 执行 + ~3.7s 间隔(~32s/5 步工作流),与代码改动无关(worker 内部每步 ≤1s,已加时间戳日志验证;单独跑 handler 0.1s;mp.Queue 往返 0s;store 保存已修复)。
- 已排除:孤儿 QGIS worker 争抢(曾同时 9 个,已清理——**注意 start_webgis_ai.ps1 与 TaskStop 强杀会留下孤儿 worker,建议加唯一实例锁**)、状态文件膨胀(已修)、机器 CPU/磁盘(基准正常)、沙箱(禁用后依旧)。
- 建议 Codex:在干净 shell(非 agent 沙箱)复测;用 py-spy dump 主进程与 worker;对比 Windows Defender/索引器对 `backend/data/workflows` 与 mp pipe 的行为;检查 mp.Queue feeder 线程在 uvicorn 进程内的调度。

### P2 — 未逐项截图目检的层
- 世界国家边界、世界主要城市点、世界主要港口点、胡焕庸线(2D)、中国主要河流、地形三级阶梯、植被带、上海区县边界、省级人均GDP:API 物化 17/17 成功、渲染管线与已目检 9 层相同,但截图因 **IAB 截图管道在本环境反复卡死**(globe→plane 过渡后必卡)未逐层目检。建议在普通浏览器人工过一遍,或换 Playwright 独立实例。

### P3 — 已知限制(设计层,未改)
- `GET /projects/{id}` 响应仍内联全部图层 features(几十 MB):store 落盘已外置,但 API 响应与浏览器刷新仍重。建议改 lazy:图层 data 走独立端点按需拉取。
- hu_line_compare 模板只输出省域分级图,未叠加胡焕庸线(前端 WorkflowDock 单结果图层,第二 geojson 不渲染;需多结果图层支持)。
- 三维主题只有功能性验证(实体数/相机),视觉打磨(配色/相机取景/动效节奏)需人工在真机评估。
- 工作流结果只渲染在 2D OL 地图;3D 球上的结果可视化(如柱体/拔地)是既定二期。
- 用户新增大图层后 GET /projects 响应体积与刷新体验需回归。

### P4 — 环境注意事项
- 用户正在运行的实例(18999,来自 `.claude/worktrees/question-bank-lesson-flow`)`gis_workflow.qgis_root` 为空,跑 GIS 工作流会报 QGIS_ENV_NOT_READY;需带 `QGIS_ROOT` 重启(或用 start_webgis_ai.cmd)。
- 测试栈仍在 19000(后端)/5175(前端)运行;测试库账号 claude-test@example.com / Test-Replay-2026!;不需要时直接结束进程即可。
- 私有图片资产(人口地图/教学地图 JPG)不入库;worktree 缺图时从主检出 `backend/data/uploads/teaching_maps/` 拷贝。

## 验证记录(交接时点)

- `python -m pytest backend/tests -q` → 423 passed, 9 subtests
- `npm test` → 37 files / 220 passed
- `npm run build` → ✓ 4.85s
- `git diff --check` → 干净
- 合并 origin/main(a0491a1 语音交互)无冲突,合并后全绿
