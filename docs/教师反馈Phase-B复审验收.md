# 教师反馈 Phase B 复审与验收（2026-10-02）

## 基线与范围
- 起点：origin/main 3fe60c6（Phase A / PR #51），承接 ZCode f1c8e42、2aef437。
- 集成分支：codex/teacher-feedback-b-finish；独立工作树 codex-b。
- 任务：同一测线的人口/地形独立窗、课前剖面预设与课堂快照。

## 复审修复
1. HTTP更新模型补 profile_preset；此前普通模拟测试更新也可能500。
2. 无效测线过滤后重映射窗口索引；保存明确空列表可移除旧预设。
3. 单线清除同步删除OpenLayers几何与其图窗；恢复测线保留稳定ID。
4. 空预设环节清理上一环节；缓存键包含项目/课堂/环节，同课重开重新恢复。
5. 恢复预设切入2D并定位测线，修复刷新和开课时窗口不可见。
6. 模拟测试面板移至左侧，剖面窗初始位置避让；降低图窗层级以保留编辑控件可操作性。
7. 修复Phase A素材编辑区被表格64px网格挤窄，视频控件重新可见。
8. QA脚本可配置隔离站点，预设测试每次新建项目，等待全部异步剖面结果。
9. 图片库测试禁用外部模型凭据，保留视觉服务stub的确定性。

## 验证证据
- 前端全量初次499 passed /72文件；最后提交门禁见PR记录。
- 最新生产构建通过，git diff --check通过。
- 后端完整干净入口：1035 passed、6 skipped、162 subtests passed；既有QGIS取消时序项在并发负载下1次失败，单项复验1 passed（61.06s）。最终集成仍需完整门禁；没有把这次全量写成全绿。
- profile preset + rehearsal HTTP专项6 passed；图片库11 passed。
- scripts/qa/phase_b_walkthrough.py：11/11，真实绘制两线、四窗加载（人口2/地形2/脚注4）、拖动、缩放、单窗关闭、暂收恢复、清除测线。
- scripts/qa/phase_b_preset_walkthrough.py：8/8，API准备教案后真实UI保存预设、刷新、模拟发布、开课；布局偏差0；1366x768完整可见并可拖动。
- 真实数据来自本地WorldPop包与在线Mapzen地形；本地人口范围外显示无数据，不插值伪造。
- browser测试使用5825/18645和独立数据目录；没有用组件测试冒充实际鼠标操作。

## 限制与后续
- Phase C工具栏、Phase D投影排版及最终1920x1080全链路验收分阶段交付。
- 本轮线上数据恢复点为9月30日已校验备份；其后记录未确认找回。WorldPop源与格网锁定SHA完全匹配。运行数据不入Git。
- 未修改主检出的未跟踪资料、planner回归基线、workflow白名单或generic_classroom_pack。
