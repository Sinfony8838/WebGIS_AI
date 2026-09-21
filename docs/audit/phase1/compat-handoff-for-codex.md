# 给课堂开发（Codex「人口分布上课模式优化」）的兼容性交接

> 一次性交接说明。加固分支**尚未合并、未上线**；本文不要求你停工或改变当前实现方式，只在你的下一个 main 同步节点需要知道这些。

## 1. 基线

| 项 | SHA | 状态 |
|---|---|---|
| 已验收加固基线 | `df8ca27`（claude/phase1-hardening，19 提交） | 未合并，证据完备（后端 886 passed 含真实 QGIS、前端 414、浏览器课堂链路） |
| 集成候选 | `c7a6630`（claude/phase1-integration-review = df8ca27 + merge origin/main@75405e9） | Draft PR 评审中，**未合并** |
| 所基于的 main | `75405e9`（PR #31 之后） | — |

## 2. 接口变化（你的前端代码可能消费）

- **`GET /health` 已收窄为 `{"status":"success"}`**（最小存活探针）。不要再从 /health 读取任何能力字段。
- **`GET /ui/capabilities`**（公开）承载前端能力集：`ui.assistant_v2_enabled`、`online_services.{amap_poi_enabled,weather_basemap_enabled}`、`llm.{enabled,provider,model}`、`voice_asr.{available,state,reason}`、`image_generation.{configured,model}`、`gis_workflow`、`basemaps`、`templates`、`knowledge_base.item_count`。使用 `types.ts` 的 `UiCapabilities` + `api.ts` 的 `fetchUiCapabilities()`；字段白名单，不含路径/base_url/密钥来源/异常文本。
- **`GET /diagnostics`**（仅 admin）：运行路径、qgis_root、build info（`git_sha` 未配置时为 `"unknown"`）。
- **错误码**：新增 `DATASET_NOT_ALLOWED`（数据引用越权/跨项目）与 `QGIS_BUSY`（地理处理排队超时）——前端按 code 区分提示；此前两者被降级为 INTERNAL_ERROR。
- **语音 WS 终态语义**：`4407`=需先改密、`4429`=并发会话上限、`1009`=帧过大、`1000`+`session_timeout`/`session_idle`=时长/空闲超时。这些是**终态**，前端（voiceSession.ts 已实现）不自动重连、保留手动重试；传输类错误（1006 等）才走有界 3 次退避。新增语音交互时请沿用该分类，不要为终态码做自动重连。
- **上传上限**：dataset 512MB、kb/ppt/题库单文件 50MB、image-library/timeline 20MB（均可配 `WEBGIS_AI_MAX_*`），超限 413。JSON 体默认 32MB（`WEBGIS_AI_MAX_JSON_BODY_BYTES`）。
- **workflow 提交**：客户端 `parameters.project_id` 与顶层不一致 → 400；服务端强制注入可信项目上下文。

## 3. 必须保护的行为（评审会盯，请勿在课堂分支里绕开）

1. **授权边界**：/files 与响应内授权只认"本请求已授权的项目/题库根"；跨项目 upload 引用、workspace 外绝对路径一律拒绝（worker 端同样执行）。新增课堂资源入口时请走 `_grant_response_files(..., allowed_roots=...)` 模式。
2. **数据根与测试隔离**：`WEBGIS_AI_DATA_DIR` 单点解析；`backend/tests/conftest.py` 在 backend/data 含 auth.db/runtime.json 时拒绝收集。优先使用全新独立工作树；重跑前确认目录不是符号链接或 Junction、仅含本轮测试生成数据，再将它归档到该工作树内的独立目录。不得删除桌面或上线实例的数据，也不得仅为测试通过而绕过保护。
3. **任务状态一致性**：QGIS 步骤名额在底层任务运行期间占用（请求返回≠释放）；取消≠完成。
4. **报告口径**：`duration_minutes` 是会话经过时长（`duration_semantics:"session_elapsed"`）；`effective_teaching_minutes` 显式 null；正确率分母是 `valid_count`（文本/无效提交单独计 `text_count`）；`data_source` 标注来源；推荐项必带可定位 `evidence_refs` 或"设计建议（证据不足）"。
5. **报告 LLM 载荷只含汇总**：作答原文、教师备注原文、昵称、participants 列表不出服务端（`ReportService._llm_summary_payload` 白名单）。新增复盘功能时沿用白名单模式。
6. **grant_file 首授即定**：授权行不因后续响应改派归属。

## 4. 交集与依赖（按文件/接口列出，未猜测你的实际改动）

- `frontend/src/App.tsx`（#31 已与你共用；候选分支含 capabilities 消费切换——合并时 git 已自动交错，tsc 通过）
- `frontend/src/{types.ts,api.ts}`：`UiCapabilities`/`fetchUiCapabilities` 新契约；`HealthResponse` 已收窄——如果你此前从 /health 拿能力字段，需迁移。
- `frontend/src/components/CopilotWidget.tsx` / `voiceSession.ts` / `voiceStream.ts`：语音终态处理（若你改语音交互入口）。
- `backend/app/main.py`（授权、预算中间件、语音 WS）、`runtime.py`（capabilities/diagnostics/submit_workflow）、`reports.py`（口径）。
- 事件/状态语义：class session 的 `anomalies`、`data_source`、`valid_count/text_count` 为**新增字段**（向后兼容）；未删除既有字段。

## 5. 后续集成建议

加固 Draft PR 评审合并 → 你在一个可交付节点整体同步 main → 对「加固 + 新课堂功能」组合版重新跑核心验收（后端全量 + 前端 + 你的课堂链路 + 真实 QGIS 三工作流）。**不建议**复制粘贴安全补丁、零散挑选安全提交、或长期维护两套接口（/health 富字段已不存在，以 capabilities 为准）。

## 附：部署约束（提前知晓，本轮不建设）

多进程部署不能只调大并发数字：需同时核 RuntimeStore 单写者/状态一致性边界与 LLM/QGIS 按进程限额（当前 AdmissionGate/LLM 闸为每进程语义）。
