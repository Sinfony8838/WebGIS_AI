# Phase 1 回滚说明

## 补丁切分

`claude/phase1-hardening` 分支上按任务提交，可独立回退（`git revert <sha>` 或按范围摘除）：

| 任务 | 提交主题 | 涉及面 |
|---|---|---|
| T0 | docs(audit): T0 phase-1 baseline and evidence inventory | docs only，无运行时影响 |
| T1 | feat(config): unify data-root resolution across main process and pyqgis worker | backend/app/config.py、pyqgis_worker/handlers/_common.py、tests |
| T2 | fix(security): derive resource authorization from normalized registered resources | backend/app/main.py、runtime.py、services/resource_access.py（新）、workflow_executor.py、_common.py、tests |
| T3 | feat(security): minimize public health info, harden voice WS, add request budgets | backend/app/main.py、runtime.py、config.py、services/request_limits.py（新）、workflow_executor.py、frontend/src/App.tsx、tests |
| T4 | feat(reports): evidence-boundary metrics and LLM payload minimization | services/reports.py、tests |

依赖顺序：T2 依赖 T1 的 config 解析点；T3 的 executor 准入闸叠在 T2 的 executor 改动上；T4 独立。回滚时**逆序**执行（T4→T3→T2→T1）。

## 回滚原则

- 只回退代码/构建产物，不触碰任何数据目录：不还原旧 runtime.json 覆盖新课堂记录、不替换/删除身份库 auth.db、不清空 uploads/outputs/workflows。
- 第一阶段无 schema 迁移、无不可逆数据变更；回滚后旧代码读写现有数据目录无需转换。
- 接口兼容性说明：`/health` 收窄与 `/ui/capabilities` 新增同属 T3——若只回退后端不回退前端，教师首屏能力配置加载会失败（init 报"能力配置加载失败(404)"）。因此 **T3 必须整体回退（前后端一起）**；仅回退前端不回退后端则 /health 多余字段被忽略，无害。
- 若回退 T2/T3 会重新暴露已确认的授权缺口（跨项目 upload 引用、_grant_response_files 宽授权）或公共路径泄露（/health 绝对路径、语音 WS 无 Origin 校验），应优先停用受影响入口（如暂时下线 /files 跨项目服务、限制 WS 握手）而不是把不安全版本直接重新开放。

## 备份/恢复

本轮全部测试在 pytest 沙箱（tmp 目录，已销毁）内执行，未生产任何需要恢复的状态。一致性备份需同时覆盖身份库、state（含外置 layer_data）、uploads、outputs、workflows 与产物引用；生产备份/恢复演练须单独授权，本轮未执行。
