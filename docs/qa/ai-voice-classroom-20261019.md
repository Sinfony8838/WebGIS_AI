# AI 助教与实时语音操控：核查与首轮改进

日期：2026-10-19。用户优先级：实时语音操控，关注连续对话、打断、地图操作与结果反馈。

## 任务范围

分支：codex/ai-voice-classroom-20261019。
起点：c9136df205d58372bfd07ef9aa38aaea7932799f。
独立工作区从刷新后的 origin/main 创建，开始时干净。

目标：改善现有课堂语音链路，形成后续连续操控方案。本轮完成语音启动取消、播报所有权、唤醒停止播报与重复指令去重；完整自由插话、执行中任务取消与跨轮指代规划仍待实施。

允许路径：frontend/src/voiceSession.ts、voiceStream.ts、voiceGate.ts、speechSynthesis.ts、components/CopilotWidget.tsx、五个对应测试文件和本报告。
禁止路径：共享集成入口 App.tsx/api.ts/types.ts、后端入口与运行装配、.env、模型配置、既有 backend/data、生产目录和其他工作区。
依赖：现有本地 ASR、浏览器 TTS、MiniMax 规划与工具执行器。没有引入新模型或执行外部收费调用。

## 产品目标

建立“理解当前课堂状态、接受自然指令、操作受控工具、观察结果并允许纠正”的地理课堂智能体。“AGI 式”可以描述交互体验，当前实现与本轮验证不能支持通用 AGI 的能力宣称。

~~~mermaid
flowchart LR
  A[教师语音] --> B[流式转写与意图门控]
  B --> C[课堂状态与近期操作上下文]
  C --> D[受限规划与权限检查]
  D --> E[地图和课堂工具]
  E --> F[实际状态与界面回执]
  F --> G[简短播报与追问]
  G --> A
  F --> C
~~~

“界面回执”和“近期操作指代”是后续设计，不能把后端执行完成当作地图已渲染完成。

## 最新主线的能力核查

| 能力 | 源码与证据 | 判断 |
| --- | --- | --- |
| 教学助教 | session_engine.py 的 IntentRouter、KnowledgeService、ConversationMemory、PromptRegistry；test_assistant_v2.py | 已有检索、地图/识图、教学问答和历史压缩；真实外部模型质量本轮未测 |
| 地图操控 | assistant.py::plan_interaction_actions、llm_planner.py::_plan_interaction | 高频规则优先，未匹配交给 MiniMax；应继续复用 |
| 参数与权限 | session_engine.py::ToolExecutor、确认计划与重校验；test_voice_tools.py、test_interaction_regressions.py | 已有白名单、高风险确认与参数验证 |
| 执行预算与轨迹 | agent_harness.py::AgentRunContext / HarnessPolicy；test_agent_harness.py | 已有动作数、重复动作、时间、失败上限和脱敏事件；不应沿用旧审查中“没有预算”的判断 |
| 语音识别 | voiceStream.ts → WebSocket → voice_asr.py | 本地 sherpa-onnx 流式识别与重连；本轮未更换引擎 |
| 播报与轮次 | App.tsx::subscribeToJob、voiceSession.ts、speechSynthesis.ts | ASR→规划/执行→TTS；尚非原生语音到语音对话 |
| 连续追问 | 教学问答使用历史；操控 _interaction_context 主要传项目、地图、工具和模板，_interaction_messages 未直接加入近期对话 | 连续轮次已存在；“它/刚才那里/再淡一点”不能视为已可靠支持 |
| 结果确认 | App.tsx::handleAssistantUiActions 应用 ui_actions，其余动作刷新项目 | 缺少与实际渲染完成绑定的通用回执 |
| 结果依赖任务 | llm_planner.py 明确不得猜测未观察的查询结果，已有动作预算 | 应补受限 observe→replan，不能靠一次性动作列表假装完成依赖查询的任务 |

## 本轮已完成

### 语音启动可取消

旧逻辑只在取得 handle 后递增 epoch，等待权限或连接时的旧回调可能越过暂停/离开操作。

现在每次 teardown 都使旧回调失效；启动前持有 AbortController，禁止同一代重复启动；createVoiceStream 接收可选 AbortSignal，取消时关闭传输并结束启动 Promise。浏览器若随后才返回麦克风授权，立即停止迟到的媒体轨道，不继续加载采集。

手动暂停仍放弃半句话，不把它 flush 成操作指令。

### 播报状态与实际声音一致

旧逻辑等 onstart 才通知收音控制器，保护超时只发送结束信号而未停止实际声音。

现在从排队起持有播放状态，新订阅者得到当前状态；替换前先使旧代事件失效；旧 end/error 不会解除下一条播报的状态。30 秒保护时限到达后先取消实际声音，再释放收音，并按异常结束处理。空回复、停止按钮、替换与引擎异常都会清理播放计时器。

### 可选择的唤醒停止播报

新增“允许唤醒打断播报”设置，默认关闭，沿用现有本地设置机制。

开启后，播报期间保留或重建本地 ASR。只接受“小智，停止播报”“小志，请停一下”等唤醒停止短句，仅调用本地 cancelSpeech，不提交 AI 请求或地图工具。停止后可继续说下一条完整地图指令。

普通地图命令、无唤醒词停止、否定、引用和复合命令不会从播报阶段进入工具执行。播报自然结束或被打断时，会放弃当时的采集连接并重新聆听，避免迟到的播报转写成为新命令。手动暂停、后台页面、失焦和执行中的忙状态仍优先。另有独立“停止播报”按钮，只停止当前回复，不关闭后续回复播报。

边界：本轮是明确唤醒停止后再发新指令；不是任意插话替换任务。浏览器识别备用路线没有新增同等常开唤醒打断能力。真实效果仍依赖 ASR、麦克风、外放与回声抑制，必须实测。

### 按实际命令去重

剥离唤醒词后比较重复命令，避免同一条“小智，切换到三维地球”在快速执行结束后重复提交。超过既有去重窗口后，教师仍可主动重复同一指令。

## 验证结果

| 检查 | 命令/方法 | 结果 |
| --- | --- | --- |
| 修复前负向对照 | npm test -- src/__tests__/voiceSession.test.ts src/__tests__/voiceStream.test.ts src/__tests__/speechSynthesis.test.ts | 9 failed / 24 passed，证明用例触发旧问题 |
| 完整前端 | npm test | 94 文件、740 tests passed；127.69 秒 |
| 后端相关范围 | Python312 -m pytest backend/tests/test_voice_tools.py backend/tests/test_interaction_regressions.py backend/tests/test_assistant_v2.py backend/tests/test_agent_harness.py backend/tests/test_voice_ws_endpoint.py -q | 67 passed, 5 subtests passed；76.03 秒 |
| 生产构建 | npm run build | PASS；TypeScript 与 Vite 通过；仍有大 chunk 提示 |
| 差异 | git diff --check | PASS |
| 浏览器界面 | 隔离组件预览；关闭自动收音、模拟 TTS、未连接后端；1280×720 | 新按钮和设置完整显示；开关可选；停止后按钮消失，回复播报设置保持开启 |
| 保留性静态核查 | App.tsx 的 Map3DGlobe；main.py 的 /health、/class-sessions 和报告端点；现有 TOP20 测试 | 入口保留，未修改这些文件 |
| 真实外部模型 | 本轮没有调用真实 MiniMax/视觉或收费服务 | UNRUN |
| 真实语音与地图渲染 | 麦克风、教室外放、已登录课堂、实际地图应用回执与端到端延迟 | UNRUN |
| 全量后端 | 后端源码未改，仅运行上述相关范围 | UNRUN |

实际验证命令（在独立工作区）：

~~~powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest backend/tests/test_voice_tools.py backend/tests/test_interaction_regressions.py backend/tests/test_assistant_v2.py backend/tests/test_agent_harness.py backend/tests/test_voice_ws_endpoint.py -q
Push-Location frontend
& "C:\Program Files\nodejs\npm.cmd" test
& "C:\Program Files\nodejs\npm.cmd" run build
Pop-Location
git diff --check
~~~

前端全量覆盖课堂流程、TOP20、报告和地球图层。隔离预览中的完成文本是布局夹具，不能当作实际地图操作证据；后端测试也不能证明本机真实 ASR 与 LLM 的端到端表现。

## 后续优化顺序

### P1：连续指代与纠正

示例：“打开人口密度图层”→“把它再淡一点”→“回到刚才那里”。

保存近期成功操作的工具、目标 layer_id、项目/课堂标识、实际结果与版本，向操控规划器提供精简上下文。只允许指代当前项目仍存在的目标，项目切换/课堂结束/目标删除后失效；多目标歧义时问一次具体问题。先加多轮评估，再接入规划器。

涉及 session_engine.py / App.tsx 等共享入口，需由集成负责人分配；本轮未越界修改。

### P1：界面应用回执

为 ui_actions 增加 action_id 与项目、会话、轮次绑定的回执。地图模式、面板、图层刷新与定位报告 applied / failed / stale。只有实际应用后才说“已经切换/已经定位”；等待时说明正在处理。不能以计划文案充当成功结果。

### P2：依赖真实结果的受限多步任务

示例：“查人口前20个城市，把第一名定位出来，再解释分布”。

查询完成后读实际 rows，再解析目标并定位，观察后简短解释。复用动作、时间、失败与重复动作预算，先限制到少量重规划回合。依赖步骤失败时停止后续操作，不能猜测查询结果。

### P2：区分停止声音和取消任务

本轮停止播报只控制声音。执行中取消需要服务端协作取消、任务幂等及已执行动作说明。清空聊天、关闭 SSE 或停止 TTS 都不能视为操作已撤销。

### P2：语音操作与助教解释协调

保留教学解释和系统控制的权限边界，可以统一用户入口，再路由到“操作”“基于结果追问”“知识问题”“纠正/取消”。当前地图的解释必须依赖实际图层和查询结果，回答保持自然中文，内部轨迹不暴露给教师。

先建立现有链路的真实延迟与识别质量基线，再决定是否评估其他实时语音模型。模型更换不能替代对象绑定、权限、真实结果与取消协议。

## 待执行的实机验收

以下用例和要求尚未验证，不是已达成指标。

1. 隔离测试课堂中连续运行不少于30分钟，至少40条真实指令，覆盖二维/三维、面板、定位、透明度、环节和查询。
2. 开关关闭时播报期间不收音，真实结束后恢复；开启后说“小智，停止播报”，确认声音停止且下一条地图指令可执行。
3. 普通命令、引用、否定、学生讨论与系统自身声音不能在播报阶段提交地图工具；分别测试耳机与教室外放。
4. 权限弹窗中暂停/切页/离开再返回，随后授权，检查旧连接不采集、不提交且无媒体轨道残留。
5. 忙状态、手动暂停、后台和失焦不接收新操控；恢复后不重放旧 final。
6. 规划超时和网络断线明确说明未完成；按原任务编号续查，不自动重放变更。现有 VOICE_LLM_TIMEOUT_SECONDS 为12秒，不能当作实测延迟。
7. 教师核对实际地图，同时验收3D/UI shell、lesson→session→report、TOP20与健康入口。
8. 分段记录音频结束→final、规划、工具、界面应用和首段播报的 p50/p95，再定性能目标。负向误执行和单轮重复执行要求为0，目前未完成声学验证。

## 集成交接

源文件：voiceSession.ts、voiceStream.ts、voiceGate.ts、speechSynthesis.ts、components/CopilotWidget.tsx。
测试：voiceSession.test.ts、voiceStream.test.ts、voiceGate.test.ts、speechSynthesis.test.ts、CopilotWidget.test.tsx。
文档：本报告。

没有修改主目录的 docs/README.md、未跟踪资料、其他工作区、共享入口、后端源码、既有运行数据、模型凭证或生产环境。测试产物仅生成在独立工作区的忽略目录，未与生产建立数据 Junction。
独立 PR 交集成负责人审查；本轮测试和隔离截图不能作为上线或课堂语音验收完成的证明。

## 规范参考

- [Web Speech API：SpeechSynthesis.cancel](https://webaudio.github.io/web-speech-api/#dom-speechsynthesis-cancel)：取消队列并停止当前播报；超时保护据此先停止实际声音。
- [Media Capture and Streams：echoCancellation](https://w3c.github.io/mediacapture-main/#dom-mediatrackconstraintset-echocancellation)：true 由浏览器决定处理哪些回声，配置该约束不能替代教室外放实测。


## 2026-10-20：智能交互界面精简

本轮起点：9af6e91f79a15770abc921948865da4f2bd0ac26；继续使用同一独立工作区和 codex/ai-voice-classroom-20261019 分支，更新同一 PR #87。开始时工作区干净，origin/main 仍为 c9136df。

目标：解决默认视图文字堆叠和左下角两行重复提示。允许改动 CopilotWidget.tsx、styles.css、CopilotWidget.test.tsx 与本报告；禁止修改语音执行逻辑、共享集成入口、后端、运行数据和其他工作区。

变更：
- 智能交互头部缩为 GeoBot 与播报、停止、设置、最小化图标；图标保留可访问名称和开关状态。
- 自动聆听、语音打断、唤醒后执行收进默认折叠的语音设置，展开/收起不会改变聆听选择。
- 将既有系统初始说明的显示压缩为“说出指令，我来操作地图。”；原始对话记录和实际回复保持原样。
- 缩短输入占位与发送按钮文案，减少输入区高度，工具和发送按钮保持同一行。
- 本地 ASR、备用浏览器识别、实时转写共用一个状态区；实时转写替换当前状态，不再附加第二行。
- 智能交互不再额外显示“最近转写”和常驻环境声音计数。错误原因和重试入口保留；教学助手界面保留原行为。
- 简洁状态优先显示当前实际识别路线，避免本地识别可用时又显示浏览器识别不支持的错误提示。

验证：
- 在 frontend 执行 npm test：94 文件、743 tests passed，30.66 秒；其中 CopilotWidget 48 项通过。
- npm run build：TypeScript 与 Vite PASS，8.02 秒；原有大 chunk 提示仍存在。
- git diff --check：PASS。
- 前端全量仍覆盖 3D 图层、TOP20、lesson-session-report；相关后端健康端点和共享入口未改。
- 浏览器截图与窄屏实显：UNRUN。浏览器验收运行环境因 CreateProcessSecurityEnvironment / 0x80070020 启动失败，重置后重试仍失败，未把单元测试或历史截图视为本轮视觉验收。
- 后端未改，本轮未重跑后端测试；此前后端结果仅适用于前一轮对应源码。

未修改无关工作区内容、主目录已有改动、既有运行数据或生产配置；本轮未合并或部署。待跟进项为新的实屏截图与窄窗口验收。
