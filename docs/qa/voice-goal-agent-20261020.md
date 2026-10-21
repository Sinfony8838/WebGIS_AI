# 语音目标执行与创造性 Agent 验收（2026-10-20）

## 任务与基线

- 分支：`codex/ai-voice-classroom-20261019`；本轮起点：`7ff5873fb47a737dedc799d339ddbc458dffe71a`。
- 独立工作树：`C:/Users/zcyxn/.codex/worktrees/ai-voice-classroom-20261019/WebGIS-AI`。
- 保留此前紧凑界面、ASR 启动取消、播报队列与迟到语音隔离的实现。
- 本轮范围：AI/语音服务、任务接口与持久化、交互界面和对应测试；由同一实施者串行修改共享入口。
- 主工作区、环境文件、凭据、生产数据与私人课件未修改；未合并或部署到生产。
- 实现提交：`06109257c309b5a005051a054c9b51121e0876f4`；主线同步提交：`a237205984bd84e02034c8311efecd87471752ab`；整句路由修正：`cc5e692d86dd20b45406af99eb6e81849379eac2`。
- 已同步当前 `origin/main`：`163c25c565745b60d0aa8c44d2adb73beb3ab514`，保留 #88 数据迁移与 #89 PPT 单入口变更；本任务没有改写这些功能。
- 允许范围为下列 AI/语音服务、任务接口、交互 UI、测试和验收文档；依赖现有权限服务、MiniMax 客户端、工作流执行器与教学设计服务。禁止范围为主工作区、生产实例、凭据、依赖目录和私人资产。

## 已实现行为

1. 高频操作与完整匹配的复合指令使用规则通道，0 次模型请求。已知模板复用原参数解析、预检与执行器；命名数据源绑定当前项目图层，缺参数直接澄清。
2. 开放目标首次模型请求同时理解目标并规划；按领域取能力说明。Agent 可请求补充能力、生成新工作流、观察真实结果后修正或生成独立教学草稿。
3. 生成工作流沿用原 JSON DSL：17 个已实现算子、最多8步、只引用前序结果、只绑定当前项目数据、输入另存快照。保留字段/CRS/几何与权限校验，禁止脚本、保留算子、嵌套工作流、任意文件路径和不允许的表达式函数。
4. 统一每回合3次模型请求预算，失败也计数，嵌套文本服务共享上下文；语音工作流后台总结使用确定性文案。记录模型次数、耗时和供应商 token，缺失用量为未知。
5. 共享已成功执行的对象与结果，并按项目、课堂和数据版本失效。教学草稿必须引用实际观察结果；原子创建新草稿，保留现有草稿及发布流程。
6. 继承风险与权限检查。结束课堂及语音发起付费图片生成需确认；课堂学情记录和发布提问仍保留专业教学模式的边界。
7. `JobRecord` 兼容增加 `activity`、`usage`、`ui_actions`。消息接口不变，新客户端声明 `ui_observation_protocol=1`；通过 `/jobs/{job_id}/ui-observations` 幂等回报 UI 状态，`/jobs/{job_id}/cancel` 停止任务。
8. UI 操作在任务进行时下发，待应用回执后确认；回执检查鉴权、CSRF、任务发起者、项目、课堂与动作编号。缺失/过期回执保持未确认；重连只重发回执；恢复和终态任务不重放动作。
9. 同一单行动效显示执行、智能体思考、工具调用、核对和确认阶段。隐藏常驻路由徽标与忙碌时重复底部提示，工具与用量折叠查看；提供教学草稿及产物入口。
10. 执行中仅接受带唤醒词的明确停止任务短句；任务结束重建收音 epoch，丢弃执行期间迟到音频。停止传递至模型等待、工具和 QGIS 取消；保留已完成结果。

## 验证结果与证据级别

| 检查 | 结果 | 边界 |
|---|---|---|
| 全量后端 `python -m pytest backend/tests -q --tb=short` | 1475 passed, 9 skipped, 200 subtests passed（317.09秒） | 在干净源码副本中执行，空设备模型目录，不含运行实例或密钥 |
| 整句路由与 Agent 定向 `python -m unittest backend.tests.test_interaction_agent.InteractionAgentTests backend.tests.test_interaction_regressions.InteractionRegressionTest -q` | 34 tests, OK | 包含丢失回执8秒超时、取消传递、3次上限、完整语句和独立草稿 |
| 真实 QGIS 生成流程到教学草稿 | 1 native test, OK | 真实 PyQGIS，模型与 UI 回执使用固定夹具 |
| 全量前端 `npm test -- --maxWorkers=1 --minWorkers=1` | 95 files, 772 tests passed | 组件/状态机测试，包含旧帧、重连、噪音及开放目标 |
| 前端 `npm run build` | PASS | TypeScript 与 Vite 生产构建；保留原有 bundle 大小提示 |
| `git diff --check` | PASS | 提交前重新核查 |
| 真实 MiniMax 模型回合 | PARTIAL / budget_exhausted | 3 次真实请求已记录；临时脚本启动方式导致 QGIS 子进程失败，未产出教学草稿 |
| 真实麦克风、录音 ASR/TTS | UNRUN | 不将模型替身、状态测试和浏览器原生 TTS 代码当作真实课堂体验证据 |
| 浏览器屏幕验收 | UNRUN | 浏览器自动化启动失败：`CreateProcessSecurityEnvironment HRESULT 0x80070020` |
| 同一录音前后 P50/P95、真实 API 费用对照 | UNRUN | 已提供运行计数和耗时；尚无匹配的真实录音窗口 |

最终完整后端源码副本：`D:/webgis-voice-release-rf91j820/source`。
对应源码提交为 `cc5e692d86dd20b45406af99eb6e81849379eac2`。
验收副本最初记录的提交为 `ffcebac5da43ae5402e4a906fbc33fa378503f7c`；GitHub 邮箱隐私保护要求仅修改尚未发布提交的作者/提交者邮箱。重建后的每个提交代码树均逐一核对一致，公开祖先未变；本地恢复引用为 `refs/codex-recovery/voice-goal-before-email-5340299`，映射记录在 `D:/webgis-voice-release-rf91j820/commit-email-map.json`。
后端应用 `.py` 文件聚合摘要：
`694f6b7ae1d2d5c31fcc26d5e75e5b34e899158144766a2f447af70d0912e09e`。
复制清单中 Python/TypeScript 源码聚合摘要：
`b20659ba2413b23e9de1775f7ddd59d38fdecb056abb16433804fe8a56f0fab0`。
摘要按排序后的相对文件名 UTF-8 字节与文件内容依次 SHA256；不包含凭据、依赖或运行实例。
原始完整日志与身份记录：`D:/webgis-voice-release-rf91j820/pytest.log`、`source-identity.json`。
前端完整日志：`D:/webgis-voice-frontend-83eadb80e31e4b02a550ca69c3c6c9ec/tests.log`、`build.log`。
真实 QGIS 完整日志：`D:/webgis-voice-native-e9e73e75ef4d4fb98cdba6a350fd7333/native-qgis.log`（1 项，4.318 秒）。
定向回归包含修复前能复现的3个标点分句反例，修复后整句进入一次规划，不提前执行前半句；34项用例在18.602秒内通过。

真实 GIS 验收使用 `D:/QGIS 3.40.10` 的后台 PyQGIS：
- 原始三条记录的 value 为5、25、35；运行新组合 load → filter → stats → export。
- 筛选结果为25、35；总数2、总和60、平均值30，均从真实统计文件读取。
- 项目新增结果图层，原始三条记录保持不变。
- 第二轮模型替身观察真实结果，创建三道题的独立教学草稿，引用实际 observation_id。
- 本项证明服务与真实 GIS 的闭环，未证明真实模型会稳定规划该任务，也未证明浏览器渲染与真实语音延迟。

原始工作树的 pytest 入口因已有本地实例标记拒绝执行；没有绕过保护。
改用仅复制源码的临时目录，并在独立环境中清除数据根/密钥覆盖、设置空设备目录。
首次真实 GIS 验收发现旧测试夹具只重设上传与状态目录，遗漏 `workflows_dir`；已修正。
10个可明确确认由本轮临时项目生成的工作流目录已归档并保留 SHA256 清单：
`C:/Users/zcyxn/AppData/Local/Temp/webgis-agent-owned-test-workflows-yjfi2qdw`。
其余本地目录未动，没有修改既有实例状态或主工作区。

## 真实模型回合与环境异常

- 使用当前 `MiniMax-M2.7-highspeed` 和仅含5、25、35的独立临时项目，目标为筛选、统计、新结果图层和三道探究题。
- 模型实际生成 load → filter → aggregate_stats → export 的新组合。临时脚本通过标准输入启动，触发 Windows multiprocessing 对 `<stdin>` 的路径限制；Worker 返回 `WORKER_START_FAILED`。这是本次验收脚本的问题，不能算作模型到 GIS 和教学草稿的全链路通过。
- 最终回合状态 `budget_exhausted`：3 次模型请求，输入10135 / 输出1243 token，模型27016毫秒，总墙钟27500毫秒；首个界面动作未发生，GIS/ASR/TTS 实际处理耗时未测得。没有新结果图层或教学草稿，原始三条记录保留。
- 完整报告：`D:/webgis-voice-live-model-w0ozqdy_/acceptance.json`。未另开付费回合重试。后续真实模型到产物验收应从带 `if __name__ == "__main__"` 的保存脚本或模块启动；UI 回执仍需与真实浏览器验证区分。
- 恢复后的 C 盘默认并发前端测试曾因 Node 内存不足中断；单进程重跑时 Vite 临时模块消失，结果为64套通过、1套失败、686项通过、30个未处理错误，不能算完整通过。
- C 盘后端副本在运行中丢失源码和 GIS 夹具，结果为129失败、1330通过、11跳过、13个准备错误、194个子测试通过（387秒）；保留该失败分母，不作为代码回归结论。后续改在 D 盘分离源码副本和 scratch，前端也使用独立 D 盘 TEMP/TMP 并限制1个工作进程。
- 浏览器工具在释放磁盘空间后仍因 `CreateProcessSecurityEnvironment HRESULT 0x80070020` 无法启动；没有反复重启或将组件测试冒充屏幕验收。

## 可复现命令

在仅复制 `git ls-files --cached --others --exclude-standard` 源码的 D 盘目录执行后端检查。子进程清除继承的 `WEBGIS_AI_*`、`MINIMAX_*` 和 `QGIS_ROOT`；`LOCALAPPDATA` 指向空设备目录，`TEMP`/`TMP`/`TMPDIR` 指向独立 scratch，`PYTHONPATH` 指向源码副本。没有设置绕过实例保护的变量。

```powershell
& 'C:/Users/zcyxn/AppData/Local/Programs/Python/Python312/python.exe' -m pytest backend/tests -q --tb=short

# 独立工作树中，TEMP/TMP 指向 D 盘验收目录
& 'C:/Program Files/nodejs/npm.cmd' test -- --maxWorkers=1 --minWorkers=1
& 'C:/Program Files/nodejs/npm.cmd' run build

$env:QGIS_ROOT = 'D:/QGIS 3.40.10'
$env:WEBGIS_AI_AGENT_NATIVE_QGIS = '1'
& 'C:/Users/zcyxn/AppData/Local/Programs/Python/Python312/python.exe' -m unittest backend.tests.test_interaction_agent.NativeInteractionAgentTests.test_native_qgis_generated_analysis_to_grounded_teaching_draft -v

git diff --check
```

## 保留与限制

- 3D 地球/UI shell、lesson-session-report、TOP20 查询及健康接口的原有回归包含在完整测试中；没有恢复旧课堂包或运行快照。
- 原有教学/工具模式行为保持；交互模式遇超长计划拒绝并要求修正，避免悄悄执行前半段。
- UI 回执证明前端状态已应用，不证明所有地图瓦片下载完毕或完成屏幕级视觉检查。
- 网络连接/等待响应头阶段由原客户端超时约束；取消后迟到响应不会执行新动作。API 供应商已经接收的请求不保证撤回计费。
- 自动执行范围是项目内可撤销的操作与独立新产物；不执行模型任意 Python/SQL，不自动发布教案。
- 只参考开源架构，继续使用当前 MiniMax、ASR/TTS、QGIS 与权限服务，没有引入第二套 Agent 框架。

参考：[Home Assistant local-first/shared history](https://www.home-assistant.io/blog/2025/02/13/voice-chapter-9-speech-to-phrase/)、[LangGraph workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)、[smolagents bounded action-observation loop](https://huggingface.co/docs/smolagents/reference/agents)。

## 本轮文件清单

- `backend/app/main.py`
- `backend/app/models.py`
- `backend/app/runtime.py`
- `backend/app/services/agent_capabilities.py`
- `backend/app/services/agent_harness.py`
- `backend/app/services/assistant.py`
- `backend/app/services/interaction_agent.py`
- `backend/app/services/interaction_operations.py`
- `backend/app/services/interaction_run.py`
- `backend/app/services/lesson_design.py`
- `backend/app/services/llm_planner.py`
- `backend/app/services/minimax_client.py`
- `backend/app/services/minimax_image_client.py`
- `backend/app/services/session_engine.py`
- `backend/app/services/workflow_templates.py`
- `backend/app/store.py`
- `backend/tests/test_interaction_agent.py`
- `backend/tests/test_interaction_job_api.py`
- `backend/tests/test_interaction_regressions.py`
- `backend/tests/test_planner_coverage.py`
- `backend/tests/test_voice_tools.py`
- `docs/qa/voice-goal-agent-20261020.md`
- `frontend/src/App.tsx`
- `frontend/src/__tests__/AgentControlOverlay.test.tsx`
- `frontend/src/__tests__/CopilotWidget.test.tsx`
- `frontend/src/__tests__/ThinkingIndicator.test.tsx`
- `frontend/src/__tests__/uiActionReceiver.test.ts`
- `frontend/src/__tests__/voiceGate.test.ts`
- `frontend/src/__tests__/voiceSession.test.ts`
- `frontend/src/api.ts`
- `frontend/src/components/AgentControlOverlay.tsx`
- `frontend/src/components/CopilotWidget.tsx`
- `frontend/src/components/ThinkingIndicator.css`
- `frontend/src/components/ThinkingIndicator.tsx`
- `frontend/src/lib/interactionActivity.ts`
- `frontend/src/lib/uiActionReceiver.ts`
- `frontend/src/types.ts`
- `frontend/src/voiceGate.ts`
- `frontend/src/voiceSession.ts`
