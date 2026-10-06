# S1 助手会话与项目绑定

- 分支：`codex/stage1-session-binding`。
- 起点：`388285f8728323ba88e1877b170b2fa44f0fa5dd`（已合并的第 0 阶段）。
- 范围：`backend/app/runtime.py`、`backend/app/services/session_engine.py`、`backend/tests/test_assistant_session_binding.py`、本记录。
- 禁止：主目录未提交文件、生产用户数据、真实模型调用、前端/API 格式、课堂上下文与附件引用的顺带重构。

## 行为

会话读取增加只读的项目关联校验。Runtime 在附件解析、创建 Job 和线程前拒绝不匹配的会话；内部会话记忆入口也在写入、压缩或历史附件复用前校验。确认的批准和拒绝同样在创建 Job、过期处理、工具执行或记忆更新前校验会话所属项目。

合法的同项目复用、空引用新建及旧确认的空会话引用保留。显式非空但不存在的会话现在返回既有 404 错误路径，避免静默创建替代会话；跨项目引用走既有 400 错误路径。不改公开端点、正常响应、终态枚举或持久化格式。

## 本机验证

工作树从无 `backend/data` 的状态开始，未连接生产 Junction；每个新增测试的 Runtime 均使用 pytest 临时目录及合成状态。环境中的生产 data/auth 覆盖、模型密钥及 QGIS 覆盖在测试子进程中清除。

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest backend/tests -q
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest backend/tests/test_assistant_session_binding.py -q
git diff --check
```

首次全量：1073 passed、6 skipped、176 subtests passed，2 failed，378.09 秒。
两次失败均为新增测试错误断言 `decision` 字段；已改为既有 `planner=confirmation_rejected` 和空执行列表。业务修改未再变化。修正后的专项：20 passed。首次测试生成的合成 data 保留在此专用工作树的 scratch 中，重新测试仍经过标准入口隔离门禁，未使用生产数据或豁免该门禁。

专项覆盖跨项目零副作用（合成 state 字节不变、无 Job/线程/附件解析/工具/模型调用）、不存在引用、压缩前拒绝、直接内部调用、批准/拒绝确认、合法同项目请求、新建会话及历史消息复用。完整提交须另经远程 Quality gate 后才合并。

## 第 0 阶段已发布证据

- PR #61 已合并，发布目录为 `public-teacher-release/WebGIS-AI`，SHA `388285f8728323ba88e1877b170b2fa44f0fa5dd`。
- 发布前备份：本机 `WebGIS-AI-backups/20261006-191506-026-01d31fba7c4d`，478 个文件、582,922,338 字节、完整 v2 清单、3 组补充资源齐全。
- 实际监听源站身份核实后修正了两份失效 PID 记录；cloudflared 断连恢复仅重启既有服务，未修改隧道配置或令牌。
- 巡检 12 项、0 failed、1 warning；警告为本机代理 Fake-IP。公网首页与健康均为 HTTP 200。
- 本机与公网 `assets/index-4D9ECoLu.js` SHA-256 同为 `60F3802A04B268BFBEE1CD8F5E7A6B90AA04AE1445B34FC84F461AE5E924307F`。
- HTTP 与静态资源一致不等于真实登录、独立网络、地图、课堂、QGIS、Office 或模型已验收。

## 发布与回退边界

S1 只在同一主线测试通过后发布；发布前保留完整数据/外置资源备份，并在已有发布工作树切换精确主线提交。主目录脏工作区不更新、不暂存；生产数据不回滚或初始化。

S1 的安全校验回退不得重新开放已修复的跨项目引用。若上线核心流程异常，应保留当前用户数据，使用新修复提交调整兼容性；任何临时停止入口或版本切换必须明确记录。

S2 课堂上下文及 S3 附件引用仍待分别处理，不以此次校验宣称全部助手资源边界已修复。未运行真实模型、QGIS、Windows COM 或浏览器课堂验收；未读取生产认证数据库内容或打印任何秘密。未修改其他工作区文件。
