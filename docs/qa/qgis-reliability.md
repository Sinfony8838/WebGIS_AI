# QGIS 任务隔离、超时与故障恢复 — QA 记录

- 分支:`claude/qgis-worker-reliability`(基于 origin/main `00bb920`)
- 日期:2026-09-08
- 实测环境:Windows 11,真实 QGIS 3.40.10 LTR(`D:\QGIS 3.40.10`,OSGeo4W 布局,自带 Python 3.12.11),后端测试用 Python 3.12.10
- 测试数据:soak 脚本自建合成 GeoJSON(12/30 个点,随机种子固定),写入一次性 `WEBGIS_AI_DATA_DIR` 临时目录;**未触碰教师真实数据与运行中的应用状态**

## 1. 修复前风险(现状记录)

`backend/app/services/pyqgis_worker/worker_manager.py` 修复前的执行模型:

1. **多个请求抢读同一个输出队列**:`run_step` 的每个调用者(每个工作流一个线程)直接 `self._output_queue.get()`。两个并发工作流时,A 的结果可能被 B 的 `get()` 取走——B 按 `step_id` 匹配不认识就**丢弃**,A 一直等到超时;更糟的是两个工作流使用**相同 step_id** 时,B 会把 A 的结果当成自己的,直接**串结果**。
2. **仅按 `step_id` 匹配**:不同工作流同名步骤无法区分;消息没有请求唯一标识。
3. **超时/崩溃无隔离**:超时后旧结果仍留在公共队列,可能被下一个同名步骤请求消费;崩溃后所有等待者各自挂到超时,且错误一律报 `WORKER_CRASHED`,无法区分排队超时/执行超时/启动失败。
4. **无取消、无安全重试、无产物校验**;worker 侧 `Workspace.cleanup()` 只清内存,`steps/` 中间目录永久堆积。

以上结构性缺陷通过代码走查确认,并用 `backend/tests/qgis_reliability/test_correlation.py` 的并发复现用例在新模型上做了回归保护(修复前的模型无法通过该测试)。

## 2. 修复后的执行模型

**单 worker 串行执行 + 单一调度线程路由**(`worker_manager.py` 重写):

- 唯一的 worker 子进程持有 `QgsApplication`,步骤严格串行——遵守 QGIS 对象线程归属,**不做**算法级线程池并发。
- manager 侧唯一一个 `PyQgisWorkerDispatcher` 线程读公共输出队列;每个 `run_step` 调用者持有**私有 reply 队列**。
- 每条消息携带 `request_id`(uuid)+ `workflow_id` + `step_id`;调度线程按 `request_id` 路由。**迟到、重复、孤儿消息一律丢弃并计数**(`late_messages_dropped` / `duplicate_messages_dropped`),不可能串入新请求。
- worker 出队即回 `step_started` ack → **排队超时(`STEP_QUEUED_TIMEOUT`)与执行超时(`STEP_EXEC_TIMEOUT`)分离计量**,响应带 `timings{queued_ms, exec_ms, total_ms}`。
- worker 崩溃只影响当前代(generation)的请求;**引用了进程内图层的步骤不自动重试**(参数含 `${step.key}` 引用或 `_layer__` 别名 → 检测跳过),无引用步骤自动重试一次(全新 worker、全新 request_id);重试上限一次,不无限循环。
- 崩溃恢复只 `terminate()` manager 自己的子进程句柄,**绝不**清扫整机 Python/QGIS 进程。
- 新增错误码(`errors.py`):`WORKER_START_FAILED`、`WORKER_STUCK`、`WORKER_RESTARTED`、`STEP_QUEUED_TIMEOUT`、`STEP_EXEC_TIMEOUT`、`STEP_CANCELLED`、`OUTPUT_INVALID`。
- 产物校验(`validation.py`):成功步骤发布的路径产物必须存在、非空、可重新打开(GeoJSON 需通过 JSON 解析;PNG/GPKG/TIFF 校验魔数);**合法空结果**(如 filter_features 零命中,`feature_count: 0` + 有效空 FeatureCollection)明确成功,不误报失败。
- 确定性资源释放:`release_workflow` 清内存图层/步骤注册表并删除该工作流自有的 `steps/` 临时目录(`outputs/` 发布产物、日志、status.json 保留);引用了已释放/已丢失内存图层的后续请求得到准确的 `WORKER_RESTARTED` 报错。
- 取消:`run_step(..., cancel_event=...)`、`cancel_request(id)`、`cancel_workflow(id)`、executor 级 `cancel_workflow(id)`;取消立即唤醒等待者(`STEP_CANCELLED`),独立取消队列会在 worker 执行下一个排队步骤前优先处理取消,迟到结果被隔离。HTTP 端点接线属共享文件(main.py),未在本任务修改。
- 真实 QGIS 兼容修复(`bootstrap.py`):OSGeo4W `qgis-ltr-bin.env` 把 GRASS84 目录排在 Qt5 之前,且共享机器 PATH 混入的其他软件会遮蔽同名 DLL,导致 `import qgis.core` 报 "DLL load failed"。现按依赖顺序**全路径预加载** QGIS 运行时 DLL 并把 GRASS 目录移到 PATH 尾部(保留 GRASS 可用性)。

## 3. fake worker 测试结果(无 QGIS 依赖,协议级)

`backend/tests/qgis_reliability/`,30 项全部通过(fake worker 与真实 worker 同协议,可注入延迟/硬崩溃/软崩溃/重复/孤儿消息):

- 相同 step_id 4 工作流并发 ×6 轮:零串结果、零串目录
- 10 组 ×2 工作流相同步骤名交错:全部成功,输出归各自工作流
- 孤儿/伪造 request_id 消息被丢弃计数;重复结果折叠为一次投递
- 排队超时(0.8s 预算,queued_ms≈800,exec_ms=None)与执行超时(0.6s 预算)准确区分
- 执行超时后迟到结果被隔离;同 step_id 重跑得到自己的新结果
- 硬/软崩溃:准确 `WORKER_CRASHED` + 自动重试一次成功;含引用步骤不盲目重试
- 排队中崩溃的其他工作流请求:失败后自动重试成功
- 取消(执行中/排队中/按工作流)均 `STEP_CANCELLED`;取消后重跑成功
- 连续 4 轮启动/关闭:每次新 pid、无泄漏、shutdown 幂等;同一个 manager 关闭后可重新启动
- 启动进程立即失败或存活但不发 ready → `WORKER_START_FAILED`
- worker 协议级:ack/result 回显 request_id;取消跳过;产物缺失/截断 → `OUTPUT_INVALID`;合法空结果成功;release 清 `steps/` 保 `outputs/`

## 4. 真实 QGIS 实测结果(soak)

执行方式:

```powershell
python scripts/qa/qgis_reliability/run_soak.py --qgis-root "D:\QGIS 3.40.10" --out %TEMP%\qgis_soak_report.json
```

2026-09-08 实测(报告 JSON:10/10 项 verdict 全部通过):

**耗时与吞吐**

| 指标 | 实测值 |
| --- | --- |
| 冷启动 worker_ready(spawn + QGIS init) | 2912.9 ms |
| 冷启动后首个真实操作(load_layer) | 83.3 ms |
| Phase B 连续真实操作 | 30/30 成功,总 568.8 ms,平均 19.0 ms,最慢 81.1 ms |
| Phase C 交错(10 组 × 2 工作流) | 全部成功,组均 111.3 ms |
| 崩溃后恢复(新 worker + QGIS 重初始化 + load) | 2954.4 ms(generation 1 → 2) |

**正确性与隔离(必须为零的项)**

| 指标 | 实测值 |
| --- | --- |
| 串结果 / 串目录 / 重复发布产物 | **0 / 0 / 0**(逐请求校验 workflow_id、feature_count、产物路径归属) |
| 执行超时 | `STEP_EXEC_TIMEOUT` 在 55.9 ms 返回(预算 50 ms,exec_ms 计量准确) |
| 超时后迟到结果 | 被隔离丢弃(late_messages_dropped=2,含取消场景 1 次),重跑同 step_id 得到新结果 |
| 崩溃(仅终止 manager 自己的子进程 pid 13728) | 在飞请求准确 `WORKER_CRASHED`(attempt=1:参数含内存图层别名,不盲目重试) |
| 崩溃后新请求 | 全新 worker(generation 2)上成功;`auto_retries_skipped_refs=1` 证明跳过逻辑生效 |
| 取消 | `STEP_CANCELLED` 620.8 ms 返回;迟到结果隔离;重跑成功 |
| 合法空结果 | filter_features 零命中 → success + feature_count=0,不误报失败 |
| shutdown 后 worker pid | 已消失(进程数从 7 回落至 6) |

各阶段完整耗时明细以 `run_soak.py` 输出的 JSON 报告为准(含每步 queued_ms/exec_ms/wall_ms 与崩溃恢复耗时)。

## 5. 回归验证

- Python 3.12 后端全量:`python -m pytest backend/tests -q` → **492 passed**(462 既有 + 30 本任务新增),9 subtests passed
- `git diff --check` → 干净
- 不涉及前端改动,无需 npm test/build

## 6. 已知限制与后续事项

1. **HTTP 取消端点未接线**:`executor.cancel_workflow()` 已就绪,但暴露为 REST 端点需改 `backend/app/main.py`(共享文件,按协作规则留给集成负责人)。
2. 执行超时后 worker 可能仍卡在原步骤:后续请求快速失败(`WORKER_STUCK`)直到 worker 产出孤儿结果证明恢复;不会误用旧结果,但可用性受损——需要时可在 main.py 暴露管理端点强制重启 worker。
3. 崩溃后自动重试仅一次,且只对参数完全自包含(无 `${}` 引用、无内存别名)的步骤;多步工作流崩溃后需整体重跑(有明确错误指引)。
4. DLL 预加载清单针对 OSGeo4W 3.40 LTR 布局;其他 QGIS 版本若缺 DLL 会得到原有的精确报错而非静默失败。

## 7. 2026-09-09 Codex 接手复核

复核发现并修复三处原测试未覆盖的生命周期问题：排队取消消息与步骤共用 FIFO 时实际无法抢在步骤前生效；同一 manager 关停后立即重启时，旧调度线程可能被误认为新一代调度线程；worker 进程存活但始终不发送 `worker_ready` 时会继续进入排队超时，而不是返回 `WORKER_START_FAILED`。此外，原“启动失败”测试使用不可序列化的局部函数，Windows 子进程会在测试通过后输出 `WinError 6` traceback；现改为模块级故障 worker，进程和队列句柄均确定性回收。

复核后的独立验证：专属测试 **30 passed**，无退出 traceback；全量后端 **492 passed, 9 subtests passed**；真实 QGIS 3.40.10 soak 的 10 项 verdict 全部为 true。实测冷启动 7212.7 ms，连续 30 次真实操作平均 21.4 ms，10 组交错零串结果，执行超时 62.9 ms 返回，崩溃后 2470.6 ms 恢复，取消 611.7 ms 返回，最终 worker 进程已消失。冷启动时间受本机当时负载影响，功能与隔离判定全部通过。
