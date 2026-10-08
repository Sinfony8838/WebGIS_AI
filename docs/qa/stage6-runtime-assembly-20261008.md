# Stage 6 — 后端运行时服务组装边界

- 分支：`codex/stage6-runtime-assembly`；起点：`719a7846e19d146d483e818fc6e794ba98edbb27`。
- 目标：将服务构造和连接集中在 `assemble_runtime_services`，保留业务逻辑、构造顺序和旧测试替换入口。
- 范围：`backend/app/runtime.py`、`backend/app/runtime_assembly.py`、`backend/tests/test_runtime_assembly.py`、本记录。
- 不改：前端、端点、资源 ID、任务枚举、GIS 数学、持久化格式、存储锁、生产数据、依赖及发布配置。

## 组装与恢复边界

`WebGISRuntime.__init__` 仍先配置目录、取得 RuntimeStore；只有新建 Store 执行重启对账，且对账异常关闭新写入者后传播。之后才构造服务。注入的 Store 仍属于调用者，不自动对账或关闭。

`RuntimeServiceFactories` 显式传入 19 个现有构造入口，启动时从 `runtime.py` 的旧模块符号取得，保留测试在启动前替换旧构造符号的契约。没有新的容器、注册表或运行配置。组装模块导入时不构造服务。

服务构造、助手依赖绑定、会话资源检索、任务摘要回调、重启状态镜像、时间线、原有语音预热、课堂连接和统计回调保持原顺序。最后的项目规范化仍在运行时入口。现有构造失败语义沿用；本步不顺带调整服务关闭政策。

## 当前架构文字总图

浏览器的 React 页面通过 `useProjectSnapshotRefresh` 对用户、项目、请求批次归属进行核对，通过 `useWorkflowStream` 观察原任务的 SSE 与查询恢复。OpenLayers/Cesium 适配器共用样式契约；`GlobeProjectLayers` 管理当前项目矢量几何修订及隐藏视图对账。

FastAPI 路由保留认证和资源校验，调用 WebGISRuntime。运行时持有配置和单写入者 Store，并通过组装模块连接助手、会话、规划器、视觉、资源检索、知识库、教学地图、课堂和任务执行器。执行器对接既有 PyQGIS 工作进程并登记文件产物，前端通过原资源授权接口获取产物。本文未进行真实模型或 PyQGIS 调用。

生产仍是 Cloudflared 服务 → Caddy → 单个本地 Uvicorn 后端，以及 Caddy 静态前端构建。发布代码位于固定工作树；其 data Junction 指向既有数据根，依赖 Junction 仅用于发布。测试工作树不共享生产 data Junction。v2 备份包含 backend/data、位于源码资源目录的知识索引及被忽略的教学/芬兰资源；本步不搬迁这些资源。

## 路线收口

| 边界 | 独立提交/评审 |
| --- | --- |
| 恢复清单与 v2 备份工具 | PR 61 |
| 会话、课堂、教案、图像资源绑定 | PR 62–65 |
| Store 加载、项目恢复、单写入者 | PR 66–68 |
| 终态清理、全程取消、重启对账、断流恢复 | PR 69–72 |
| 有界 PPT 工作与项目状态提交 | PR 73–74 |
| 样式契约与三维几何修订 | PR 75–76 |
| 后端服务组装提取 | 本任务 |

前端项目刷新、任务观察、地图适配已在前述步骤形成独立模块；本任务补后端组装。App.tsx 仍为 4734 行，runtime.py 为 2952 行；这是规模记录，不是缺陷判断。后续拆分应由具体依赖和独立验收驱动，不因行数继续扩大本次范围。

## 验证

- 新组装测试 11 项，核对顺序、同一依赖引用、关键字参数、绑定回调、新 Store 恢复异常关闭、注入 Store 归属及旧模块替换入口。
- 聚焦：`python -m pytest backend/tests/test_runtime_assembly.py backend/tests/test_startup_reconciliation.py backend/tests/test_runtime.py -q`：52 通过，9.71 秒。
- 全量：Python 3.12 执行 `python -m pytest backend/tests -q`，1297 通过、8 跳过、178 子测试通过，387.46 秒。`git diff --check` 通过。
- 前端源码不改；该基线的 PR/main CI 均为 90 文件、692 项与构建通过，本任务 CI 仍需独立运行。
- 新测试只使用合成替身，不访问数据库、模型、QGIS 或 COM。完整回归使用本任务专用数据根，不使用生产数据。
- 未声称健康检查代表课堂、真实模型、真实 QGIS、COM 或手机公网验收；浏览器三维合成验收记录见 Stage 5b。

## 回滚与未改动确认

代码可回退到起点，保留新教学数据和前述资源校验。没有持久化迁移，也不恢复旧运行状态。发布前完成完整离线备份，核对进程、端口、Junction 和公开前端字节，发布后观察至少 15 分钟；实际发布证据记录于 PR。

未修改主目录已有变更、其他任务代码或生产业务文件；只保留本任务合成测试目录和必要操作证据，不提交运行时数据。
