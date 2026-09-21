# Phase 1 收尾与集成验收记录（第二轮）

- 日期：2026-09-20 ~ 2026-09-21（本机时区 UTC+8）
- 分支：`claude/phase1-hardening`，起点 `a277acc6`（第一轮 8 提交），本轮新增 11 提交，最终 HEAD `1024c7e`。
- **origin/main 前移记录（2026-09-20 21:54，验收进行期间）**：集成所有者将主检出 fast-forward 至 `75405e9`（PR #31「feat: reorganize map tools and restore screenshots」，19 文件 +883/−234，纯前端：地图工具/截图选择器/城市研究面板重组）。与本分支改动交集**仅 `frontend/src/App.tsx` 一个文件**（本分支改动为 /ui/capabilities 导入与消费切换；PR #31 为截图/工具接线，不同功能区），合并预计小冲突，按 AGENTS.md 由集成所有者处理。本分支未擅自合并。
- 环境：Windows 10.0.26200 / Python 3.12.10 / Node v24.14.0（CI 为 Node 22）/ Chrome IAB 自动化 / vite preview 4173 + uvicorn 18801（仅回环）。
- 验收状态体系沿用 PASS / FAIL / BLOCKED / NOT_RUN。

## 一、本轮提交（10 个，均在原 8 提交之上）

| 提交 | 任务 | 内容 |
|---|---|---|
| 3a161e1 | A | 标准测试入口隔离守卫（根 conftest：清继承覆盖 + 拒绝已有实例） |
| 1fa6967 | B | grant_file 首授即定（先红后绿回归：管理员预览不再改派教师授权） |
| 1f97780 | C1 | /ui/capabilities 正式契约接入 api.ts/types.ts；build-info unknown |
| 2f380d5 | C3 | 语音 WS 等待期预算（wait_for）；前端 4407/4429 终态不自动重连 |
| ef45f8f | C4/C5 | 剩余上传入口全上限；QGIS 闸状态一致性；错误码白名单补 DATASET_NOT_ALLOWED/QGIS_BUSY |
| 2c59e11 | C6 | LLM 出站并发闸（公共入口、fake provider、单进程声明） |
| d37fc93 | C7 | 访问日志 query 剥离（控制组实测→修复→哨兵复验 0 次落盘） |
| f368df3 | D | evidence_refs 可定位性校验、real 标签免责、重复发起合并、载荷信息量断言 |
| （QGIS 测试）| V | 真实 facility_buffer 门控用例 |
| （最终文档）| VI | 本文件 + open-items 更新 + PR 说明 |

## 二、任务逐项结论

### A. 标准测试入口隔离 — PASS
- 实证：上轮全量 pytest 在工作树生成了 `backend/data/auth/auth.db(80KB)+state/runtime.json(75KB)` —— 标准 `pytest backend/tests` 在导入/收集期即打开**当前检出**的默认数据根；主检出含生产数据时会被打开（WAL 可写）。
- 修复：`backend/tests/conftest.py`（先于一切应用导入）：清 `WEBGIS_AI_DATA_DIR/WEBGIS_AI_AUTH_DB` 继承覆盖；默认数据根含 auth.db 或 runtime.json 时拒绝收集（`WEBGIS_AI_ALLOW_EXISTING_DATA=1` 显式豁免）。合成目录双向验证（4 tests PASS）。CI 全新检出不受影响。
- worker 子进程配置：T1 的 per-workspace 数据根推导 + 回退仓库布局已由 T1 测试固定。

### B. 授权收口 — PASS（1 项修复 + 1 项设计确认）
- **确认并修复**：`grant_file` 的 `ON CONFLICT(path) DO UPDATE` 会把文件授权改派给最后授予者——管理员预览教师题库即锁死教师自己的题图访问（先写失败回归再修：`DO NOTHING` 首授即定）。回归覆盖：教师保留访问、无关教师仍拒、重复授权稳定。
- 同教师双项目串用：新回归固定（workflow 嵌套 project_id + upload 引用 + worker 边界全拒）。
- 历史授权行：`get_public_file` 继续尊重（有意兼容；生产表禁止清洗）；新授权已被 T2 允许根收口。合法导入/题图/报告下载/重复导出回归全绿（45 passed）。

### C1/C3/C4/C5/C6/C7 — PASS（要点）
- capabilities 为显式白名单构造（非 health 转发）；/diagnostics 教师 403、匿名 401；build SHA 未配置返回 `unknown`。
- 语音：总时长/空闲预算在**等待下一条消息期间**也生效（asyncio.wait_for，静默客户端实测关闭）；新增 `WEBGIS_AI_VOICE_IDLE_TIMEOUT_SECONDS`(默认300)。前端 4429/4407 终态+明确提示、不自动重连（有界退避仅保留给传输错误）；关闭码实测来自真实 TestClient 断连。
- 预算：题库导入（逐文件 50MB+文件名）、image-library（20MB，原为整读后检查）、timeline generate（20MB）全部改为分块上限、413 先于缓冲；JSON 中间件覆盖截图/视觉快照等 JSON 入口。
- QGIS 闸：名额在底层步骤运行期间保持占用（不因提交请求返回而释放）、QGIS_BUSY 不派发即报错、失败后名额释放（3 tests）。
- LLM 出站：`chat_completion` 公共入口每实例闸（`WEBGIS_AI_LLM_MAX_CONCURRENT` 默认 4 / 队列超时 30s，可配置）；fake urlopen 覆盖满额/超时/异常释放。**单进程语义**：多进程部署需按进程配置。
- 日志：控制组证明默认 uvicorn 访问日志把 `?access_token=SENTINEL` 完整落盘；`QueryStrippingAccessFormatter`+log-config 接入启动脚本后，真实 uvicorn 哨兵实测 **0 次**落盘且访问日志仍完整。

### D. 报告复验 — PASS（31 report 相关测试）
- 重复发起同一题合并为单条目、口径一致；evidence_refs 全部可由 `evidence_ref_exists` 定位到本会话真实证据（或显式"设计建议（证据不足）"）；real 标签渲染免责声明（元数据≠验收证明）；LLM 载荷保留 type/collection_mode/计数/option 分布/verdict 聚合（脱敏不退化）。

## 三、浏览器集成验收 — PASS（技术验收口径）

环境：真实 uvicorn 后端（沙箱数据根、users 鉴权、**MiniMax 显式禁用**避免真实付费调用、QGIS 未配置）+ vite 构建产物 + 合成管理员/教师甲/教师乙。核心业务 API 全真实；无外部付费服务替身（AI 直接禁用走真实降级路径）。

主链路逐环通过（均为真实 UI 操作）：
1. 登录（含首次强制改密）→ 工作台、项目自动创建、capabilities 正常加载（"系统已连接"）。
2. 教案设计：规则版「生成整份初稿」一次预填 18 章节（全部待确认，系统不自动确认）→ 九步逐步确认（15 项）→ 预演结构检查通过（40/40 分钟）→ 发布 v2 + Word 生成 → 模拟测试四项检查全部通过 → 「可开真实课堂」。
3. 课堂模式：开始上课 → 环节 2 切换（场景自动准备 scene_applied 事件落盘）→ 口头提问卡呈现（朗读卡）→ 投屏答题（计时器）。
4. 教师观察：答对 1 次 + 误区 1 次（标签"把人口总量当密度"+备注）→ 截图存证（框选→"地图截图已入库"）。
5. 结束上课 → 课后复盘 → 生成并展示报告：872.4 分（真实墙钟，如实）、"未采集"作答（不虚构）、截图回看带"不能单独证明理解"、误区标签聚合、**AI 禁用下降级为"规则生成·证据保护"**、练习推荐带完整证据边界文案；Markdown 下载链接存在，匿名访问 401。

复验项：
- **刷新/重登恢复 PASS**：验收跨真实数小时，教师会话 8 小时空闲到期被正确 401 登出（生产语义）；重登后 running 课堂完整恢复（课中面板/环节/计时/投屏层）。
- **服务重启恢复 PASS**：杀掉并重启后端（同沙箱）→ 刷新页面：登录态、项目、已结束课堂与完整报告全部恢复可读。
- **AI 不可用降级 PASS**：报告规则生成、无 busy、无付费调用。
- **QGIS 不可用降级 PASS**：工作流提交明确失败 `[QGIS_ENV_NOT_READY]`，无卡死。
- **窄屏响应式 PASS（390×844 截图存档；仅响应式模拟，非真机验收）**。
- **语音**：本机语音模型可用，真实"语音不可用"无法在本机自然复现（服务端行为已由 C3 单测固定；自动化环境无麦克风授权属环境限制）——**真人语音/真机保留 BLOCKED**。

产品级观察（记录，不修，见 open-items）：数据库面板向已登录所有者展示服务器绝对路径（本地优先产品取向，非公开接口泄露）；投屏层秒级重渲染影响自动化 actionability（非功能缺陷）；超长会话计时 UI 直显墙钟数值（报告侧已有诚实语义，UI 提示可后续优化）。

## 四、真实 QGIS — PASS（REAL_QGIS_PASS）
- 探测：`D:\QGIS 3.40.10`（OSGeo4W，bin/python.exe + o4w_env.bat 齐全）。上轮 NOT_RUN 结论有误（沿用了过时路径假设），本轮纠正。
- `QGIS_ROOT="D:\QGIS 3.40.10" pytest backend/tests/test_workflow_population_templates.py`：**24 passed, 0 skipped**，含四条真实 worker 工作流——population_choropleth（人口分级）、**facility_buffer（缓冲区，新增：产物必须为多边形）**、hu_line_compare（34 省东西拆分+无重叠+全覆盖断言）、classify_field。真实产物、真实子进程、输出入沙箱。
- 失败恢复语义由 qgis_reliability 套件 + C5 闸测试覆盖。

## 五、回滚演练 — PASS
- 临时 worktree（rollback-drill @ a277acc）`git revert fbe5106`（T4）干净应用；回滚树上旧报告测试 19 passed。
- 演练全程只写演练树自身的临时 backend/data；**未用任何旧数据覆盖新记录**（沙箱/分支工作树未触碰）；演练树已删除。

## 六、最终回归 — PASS

- 后端全量：`QGIS_ROOT="D:\QGIS 3.40.10" python -m pytest backend/tests -q -ra --deselect backend/tests/test_download_voice_models.py` → **886 passed, 2 skipped（symlink 权限 / 私有题库资产缺失，原因如实）, 7 deselected（需真实语音模型下载）, 148 subtests passed, 300s, exit 0**。含 4 条真实 QGIS worker 工作流。
- 前端：`npm test -- --run` → **414/414 passed**（首次满负载并行下 RehearsalPanel 出现一次时序失败：单文件重跑通过、全量复跑全绿——判定为既有 flake，未以删断言/扩 mock 换绿，如实记录）；`npm run build` → exit 0。
- `git diff --check` → 干净。
- 过程修正（均已在交付前修复并复跑）：① conftest 预检幂等（自引用导入重跑导致收集中止）；② 守卫测试的干净复跑断言在全量上下文需临时移开运行生成标记。最终一轮全量即包含这两项修复。

## 七、状态表

| 项 | 状态 |
|---|---|
| 标准入口隔离（A） | PASS |
| 授权收口（B，含 grant_file 修复） | PASS |
| capabilities/diagnostics/预算/闸/日志（C1-C7） | PASS |
| 报告口径与隐私（D） | PASS |
| 浏览器完整课堂链路（技术验收） | PASS |
| 刷新/重登/重启恢复 | PASS |
| AI/QGIS 不可用降级 | PASS |
| 窄屏响应式（模拟） | PASS |
| 真实 QGIS 四工作流 | **REAL_QGIS_PASS** |
| 回滚演练（T4 独立回退） | PASS |
| 真人语音/真机/真实教师课堂/线上 | **BLOCKED**（需授权/真人，未伪造） |
