# PR 说明（草案——本轮不创建、不推送）

**分支**：`claude/phase1-hardening`（基线 `a890b527` = origin/main）
**规模**：18 提交（第一阶段 8 + 收尾轮 10），约 +3,300/−150 行，含 10 个新测试文件与 3 份审计文档
**无部署步骤**；quality-gate 零改动（新测试自动纳入既有 `pytest backend/tests -q`）

## 动机

第一阶安全审计确认的边界缺陷：标准测试入口会打开当前检出的数据实例；文件授权可被“改派”（管理员预览即锁死教师资源）；/health 泄露绝对路径与模型目录；语音 WS 无 Origin/改密/时长/并发防线且静默客户端可无限占用；除注册外无请求体预算（多处整读入内存）；LLM 出站无并发上限；uvicorn 访问日志把语音 legacy token 完整落盘；课堂报告口径（时长语义/正确率分母/证据可溯/LLM 隐私载荷）需对齐证据边界。

## 改动分组（按提交序列）

1. **T0/T5 审计文档**：docs/audit/phase1/{baseline,acceptance,rollback,open-items,acceptance-integration}.md + scripts/qa/phase1/check_isolation.py
2. **T1 数据根统一**：`resolve_data_root()` 单点解析（默认布局不变）；worker 回退错落修复；builtin 与数据根解耦；测试沙箱辅助
3. **T2 资源授权**：resource_access.py（规范化引用/共享目录/授权根）；/files 规范化判定；_grant_response_files 允许根收口（13 调用点）；workflow 服务端项目上下文注入；worker upload 项目绑定 + workspace 内绝对路径白名单；API 预检同边界
4. **T3 健康与预算**：/health 最小化 + /ui/capabilities（脱敏白名单）+ /diagnostics（admin）；BodySizeLimit 中间件；分块上传上限（dataset/kb/ppt/image-library/题库/timeline）；语音 WS Origin/4407/4429/1009/1000 + 等待期双预算；QGIS AdmissionGate；前端切换 capabilities 契约
5. **T4 报告口径**：会话经过时长语义 + 有效教学时长显式未知；异常 running 标注；正确率有效分母；计数拆分；data_source 标注；evidence_refs 可定位；LLM 载荷纯汇总
6. **收尾轮**：标准入口 conftest 守卫；grant_file 首授即定；capabilities 正式契约接入；语音前端终态处理；剩余上传入口上限；QGIS 闸一致性测试；错误码白名单补齐；LLM 出站闸；访问日志 query 剥离；报告复验补强；真实 QGIS buffer 用例

## 验证摘要（详见 docs/audit/phase1/acceptance*.md）

- 后端全量 pytest（含 QGIS_ROOT 真实 worker）：见最终回归记录
- 前端 `npm test` 414/414（一次满负载并行下 RehearsalPanel 时序 flake，单跑与复跑全绿——已知 flake，未以删断言/扩 mock 换绿）；`npm run build` 通过
- 真实浏览器合成环境：登录→教案（规则初稿→九步确认→预演→发布）→开课→环节/提问/观察/截图→结束→报告全链路；重登/服务重启恢复；AI/QGIS 不可用明确降级；窄屏响应式
- 真实 QGIS 四工作流（choropleth/buffer/hu_line 34 省拆分/classify）REAL_QGIS_PASS
- 回滚：按任务可独立 revert（T4 已演练）；T3 前后端需一起回退

## 兼容性说明

- `/health` 收窄是**故意破坏性变更**：前端同分支已切换至 `/ui/capabilities`；若有第三方监控依赖旧字段需迁移（运维注意）
- 历史授权行继续有效（未清洗生产表）；新授权行为收紧
- 新配置项均有默认值（WEBGIS_AI_MAX_*、WEBGIS_AI_VOICE_IDLE_TIMEOUT_SECONDS、WEBGIS_AI_LLM_MAX_CONCURRENT 等），默认部署零配置可跑
- 多进程部署需按进程设置 LLM/QGIS 并发限额（单进程语义已声明）

## 审查建议重点

1. `get_public_file` / `_grant_response_files`（授权语义变化面最大）
2. `runtime.submit_workflow` 项目上下文强制（嵌套 project_id 拒绝）
3. `BodySizeLimitMiddleware` 的 ASGI 排空语义（starlette 兼容性）
4. 语音 WS 关闭码契约（4429/4407/1009/1000 + 前端终态映射）
5. `reports.py` 口径变化对既有报告消费方的影响（statistics 新增字段均为增量）
