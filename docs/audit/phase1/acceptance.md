# Phase 1 验收证据表（T1–T5）

- 执行环境：Windows 10.0.26200 x64 / Git Bash；Python 3.12.10（本地）；Node v24.14.0（本地，CI 为 Node 22）。
- 源码基线：`a890b527335f8e0761dd7e73b945c1c107cd03b6`（origin/main，PR #30 合并点）；工作树分支 `claude/phase1-hardening`。
- 验收状态体系：PASS / FAIL / BLOCKED / NOT_RUN（定义见 baseline.md 第五节）。
- 记录脱敏：不含凭据、账号、学生身份、可复用会话标识；涉及的路径仅为 pytest 沙箱临时目录（已销毁）与本工作树标签。
- LLM provider：所有测试均为 mock / fake / 规则回退，未调用任何真实付费服务。

## T0 基线与证据清单 — PASS

| 项 | 结果 |
|---|---|
| `git fetch origin && git rev-parse origin/main` → a890b527… | exit 0 |
| 本地主检出 HEAD c99c32f8… 与 4 个未提交条目仅记录、未触碰 | exit 0 |
| `gh run view 34757637543` → completed / success @ a890b527 | exit 0 |
| 工作树隔离核验（backend/data 不存在、无 .env、无 symlink/junction） | exit 0 |
| 产出 docs/audit/phase1/baseline.md（git add -f 纳入） | PASS |

## T1 统一数据目录解析 — PASS

改动：config.resolve_data_root()（单一解析点，honors WEBGIS_AI_DATA_DIR，默认布局不变）；worker workspace_root() 回退修正（旧实现会错落到 backend/app/data）；builtin_root() 与数据根解耦；测试启动器 phase1_sandbox（导入前清继承覆盖 + 全目标沙箱断言）。

| 命令 | 结果 |
|---|---|
| `pytest backend/tests/test_phase1_data_isolation.py -q -ra` | 10 passed, exit 0 |
| `pytest backend/tests/test_config.py backend/tests/test_workflow_population_templates.py -q -ra` | 39 passed, 3 skipped（QGIS_ROOT 未配置，如实记录）, exit 0 |
| 验收点：主进程/worker/auth DB/state/uploads/outputs/workflows 同根；旧默认不变；不启动真实 worker 覆盖解析逻辑；输出仅标签 | PASS |

## T2 资源授权边界 — PASS（1 项受限 skip）

改动：新增 services/resource_access.py（规范化引用、resolve 后共享目录成员判定、项目/题库授权根）；get_public_file 改规范化判定；_grant_response_files 只授予请求已授权根内引用（13 个调用点收口）；submit_workflow 服务端强制注入 project_id（不一致 400）；worker resolve_dataset_path 项目绑定 + workspace 内绝对路径白名单 + resolved-path containment；API 预检同边界。

| 命令 | 结果 |
|---|---|
| `pytest backend/tests/test_phase1_resource_authorization.py -q -ra` | 27 passed, 1 skipped, exit 0 |
| skip 原因 | symlink 创建需本账户权限（`symlink creation not permitted on this account`）——越界 symlink 的规范化拒绝已由单元断言覆盖（resolve_public_reference 对外链路径返回 None 的直接测试因无法建链而 skip） |
| 矩阵覆盖 | 教师 A/B、共享 teaching_maps、A/B 私有数据、outputs 跨项目、admin、未知/已删除对象、规范化等价与穿越形态、嵌套 project_id 注入、跨项目 upload 引用、worker 绝对路径、_grant_response_files 形似字符串不产生授权 |
| 相邻回归（auth/workflow/qgis/lesson/question-bank/datasets 等 11 文件） | 142 passed, 3 skipped（QGIS 未配置）, exit 0 |
| 文件规模 | 全部为 pytest 沙箱内生成的小型无害夹具（<1KB 文本/PNG 头） | PASS |

## T3 公共健康信息、语音 WS 与入口预算 — PASS

改动：/health 最小化；/ui/capabilities（公开、脱敏、含前端所需全部字段）；/diagnostics（admin-only，含 build info）；BodySizeLimitMiddleware（接收字节流计数，先于反序列化）；read_upload_limited 分块上限（dataset 512MB / kb 50MB / ppt 50MB，可配置）；AdmissionGate（QGIS 队列上限+超时→QGIS_BUSY 友好报错）；语音 WS Origin 白名单、4407 改密一致、4429 并发上限、1009 帧上限、1000 时长上限、异常文本脱敏；App.tsx 切换 /ui/capabilities。

| 命令 | 结果 |
|---|---|
| `pytest backend/tests/test_phase1_health_voice.py backend/tests/test_phase1_request_limits.py -q -ra` | 20 passed, exit 0 |
| `pytest test_main_security test_auth_api test_voice_asr test_voice_tools test_voice_ws_endpoint test_agent_harness -q` | 84 passed, exit 0 |
| `npm test -- --run`（frontend） | 58 files / 413 tests passed, exit 0 |
| `npm run build`（frontend） | built in 5.26s, exit 0（chunk 体积警告为既有状态，非本轮引入） |
| 既有测试契约更新 | test_voice_ws_endpoint.py：patch 目标改名 `_websocket_user`；load_failed detail 由异常文本改为固定标签 `voice_model_load_failed`（审计要求：公共响应不输出异常堆栈） |
| 无 Content-Length（伪造 Content-Length=10 的 518B 载荷）| 413，先于解析（中间件计数路径单测覆盖） | PASS |

## T4 课堂报告证据口径 — PASS

改动：会话经过时长语义 + 有效教学时长显式未知（null+原因）；超长 running 会话 anomaly 标注（不改原始记录）；选择题 correct_rate 分母改为有效作答（valid_count），文本/无效/空提交单独计数；参与者昵称去重口径备注；观察次数/有效作答数/进入环节与计划分开显示（进入≠完成）；data_source 来源标注（旧记录 unknown）；每条建议带 evidence_refs 或"设计建议（证据不足）"；LLM 载荷改为纯汇总（作答原文、教师备注原文、昵称、participants 列表一律不出服务端）；修复 naive/aware 时间比较崩溃。

| 命令 | 结果 |
|---|---|
| `pytest backend/tests/test_phase1_report_evidence.py backend/tests/test_report_evidence.py backend/tests/test_class_sessions.py -q -ra` | 29 passed, exit 0 |
| 隐私断言 | fake client 捕获的 user 载荷不含昵称/作答原文/观察备注；仅含 counts、option_counts、correct_rate、verdict/tag 计数 | PASS |

## T5 全量回归与真实环境场景

| 项 | 状态 | 说明 |
|---|---|---|
| 全量 backend pytest（本工作树，排除需真实语音模型下载的 test_download_voice_models） | 见交付时记录 | 后台执行；结果与 skip 原因如实附于交付说明 |
| 真实 QGIS worker 用例 | **NOT_RUN** | 本机 D:\QGIS 不存在（`ls /d/QGIS` exit 2）；QGIS_ROOT 门控测试按仓库既有逻辑 skip，未当 PASS |
| 隔离浏览器 E2E（教师 A/B / 完整课堂流 / 失败降级） | **BLOCKED** | 需浏览器验收授权与真实服务；未执行，不以健康页/单测替代 |
| 真实设备（真麦克风中文/否定句/触控） | **BLOCKED** | 需真人设备授权 |
| 人工无障碍 | **BLOCKED** | 需人工参与；不宣称 WCAG 合规 |
| 线上只读/登录/写操作 | **BLOCKED** | 当前线上 SHA 无法确认（无 release 产物）；未执行任何线上验证 |
| quality-gate.yml | 零改动 | backend job 已运行 `pytest backend/tests -q`，新增测试自动纳入；未添加部署步骤 |
