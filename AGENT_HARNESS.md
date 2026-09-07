# WebGIS 教学智能体 Harness

当前实现版本为 `webgis-teaching-agent/3.0`。这里的 harness 指模型外部、负责把推理连接到上下文、工具、安全策略和运行状态的程序层，不是模型提示词，也不是评测框架。

截至 2026 年 9 月，业界尚不存在一份所有项目共同遵循的单一 harness 标准。本项目采用 2026 年 7 月对 11 个生产级开源/公开 coding-agent harness 的源码研究所归纳的七子系统框架，并用 OpenHands、OpenAI Agents SDK、LangGraph interrupt 和 MCP 的一手实现/规范校准运行状态、确认恢复、追踪和扩展边界：

- [Harness Engineering: A Source-Code Study of Eleven Systems](https://arxiv.org/html/2609.00006)
- [OpenHands conversation state](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/conversation/state.py)
- [OpenAI Agents SDK tracing](https://github.com/openai/openai-agents-python/blob/main/docs/tracing.md)
- [OpenAI Agents SDK guardrails](https://github.com/openai/openai-agents-python/blob/main/docs/guardrails.md)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Model Context Protocol specification](https://modelcontextprotocol.io/specification/2025-06-18)

## 七个子系统在本项目中的落点

| 子系统 | 本项目实现 |
| --- | --- |
| Agent loop | 单次请求采用线性“路由—规划—校验—执行—验证—停止”流程；所有 assistant 模式统一经过同一 harness，不再从旧 worker 绕过策略。 |
| LLM integration | 保留 MiniMax 原生客户端与确定性规则预检；模型只返回结构化动作计划。 |
| Tools & actions | 18 个工具使用集中式 JSON-Schema 子集定义；模型侧按请求延迟暴露少用工具，执行侧仍按完整白名单和相同契约二次校验。 |
| Memory & context | 沿用项目级会话、任务记忆、地图 grounding；超过阈值后增量合并摘要，并原样保留最近 8 条消息。 |
| Safety & permissions | 输入契约、模式可见性、风险分级、允许/询问/拒绝策略、动作/重复/失败/时间预算在工具副作用发生前阻断。 |
| Orchestration | 有意保持单智能体；当前课堂操作没有可证明收益的独立并行任务，不引入多智能体共享写状态。 |
| Extensibility | 内部工具注册表和输入契约是当前扩展面；需要接入外部进程或第三方工具时，优先在 MCP 边界增加能力协商、进度、取消和错误映射。 |

## 运行契约

每个 assistant job 产生一个 `result.harness`：

- `run_id`、`parent_run_id`：关联原始运行与确认后的恢复运行。
- `status`：`completed`、`waiting_for_approval` 或 `failed`。
- `stop_reason`：`completed`、`approval_required`、`policy_blocked`、`needs_clarification`、`rejected` 或 `error`。
- `policy`、`usage`：本次生效的预算和已规划/执行/失败/阻断计数。
- `events`：阶段、计划、工具、审批、验证事件；包含顺序、状态、耗时和单次运行加盐指纹。
- `verification`：停止前检查最终输出类型、确认 ID 与“待确认时不得已经执行”等不变量。

追踪默认不保存原始问题、对话历史、工具参数、工具输出、文件路径、错误消息或密钥。需要在单次运行内关联时只写入加盐、截断的 SHA-256 指纹；盐不随 trace 输出，避免低熵参数被预计算字典还原。人类可读的课堂过程仍由现有 job stage 和 conversation 数据负责，两者不要混用。

## 工具与确认边界

模型默认只看到 12 个核心地图工具。以下能力按需加入当前模型回合：

- 人口/统计意图：`run_visual_query`。
- 教材地图意图：`toggle_teaching_map`。
- 素材/视频意图：`open_material`。
- 明确图片生成意图：`generate_image`。
- 正在进行的班课且存在学情/提问意图：`record_observation`、`launch_question`。

模型输出之后，执行器不信任该目录筛选结果，而是重新检查工具白名单、`tool_params` 契约、当前 assistant 模式、地图/班课状态和权限决策。

高风险动作先冻结序列化计划、计算计划指纹并返回 `approval_required`，此时不执行工具。批准后创建子运行，重新检查过期时间、活动确认、计划指纹、工具契约和权限，再执行副作用；拒绝则产生 `rejected` 子运行。这样可以避免把“规划成功”误报成“外部操作已经成功”。

## 策略配置

| 环境变量 | 默认值 | 配置钳制范围 | 含义 |
| --- | ---: | ---: | --- |
| `WEBGIS_AI_AGENT_MAX_ACTIONS` | 8 | 1–32 | 单次计划和工具调用上限 |
| `WEBGIS_AI_AGENT_MAX_IDENTICAL_ACTIONS` | 2 | 1–5 | 相同工具名与参数可重复次数 |
| `WEBGIS_AI_AGENT_MAX_TOOL_FAILURES` | 1 | 1–8 | 单次运行可容忍的工具失败次数 |
| `WEBGIS_AI_AGENT_MAX_SECONDS` | 180 | 5–900 | 单次运行的软墙钟时间上限 |
| `WEBGIS_AI_AGENT_MAX_TRACE_EVENTS` | 64 | 16–256 | 内嵌追踪保留的最大事件数 |

预算属于代码配置，不写进模型提示词。改动这些值后应重启后端，并用 `result.harness.policy` 核实实际生效值。

## 已知边界

- 墙钟上限在阶段和工具边界检查，不能强制中断一个已经进入阻塞状态的第三方网络调用；具体 provider 仍必须设置自己的请求超时。
- 追踪目前随 job 结果持久化，没有接入外部 trace collector，也不会证明真实浏览器或第三方服务已经执行成功。
- 会话压缩按消息数量和字符长度工作，不是精确 token 预算；若未来上下文规模显著增长，应升级为 provider-aware token 阈值。
- 当前没有多智能体编排。只有在任务可以隔离状态、并发收益经评测成立时再引入。

## 验证

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest backend/tests -q
Push-Location frontend
& "C:\Program Files\nodejs\npm.cmd" test
& "C:\Program Files\nodejs\npm.cmd" run build
Pop-Location
git diff --check
```
