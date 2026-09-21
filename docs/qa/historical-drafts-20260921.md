# 四个历史工作树草稿处置

用户授权逐项判断删除或完善提交。本轮在 `codex/historical-drafts-20260921`
工作树实施，起点 `bf3359b8f994378ce9bed11f10289e5425ddbdac`。
ZCode 对应审查任务已完成；未发现它继续写入这些草稿。

## 判断与结果

| 原工作树 / 起点 | 草稿内容 | 处置 |
| --- | --- | --- |
| `codex-release-hardening-continuation` / `7b449b6` | `LessonWorkflow.test.tsx` 只删除末尾空行 | 无行为价值，备份后恢复原提交 |
| `claude-release-hardening-20260822` / `a94e970` | 图片上传/生成的项目权限、图片意图排除地图操作、人口源错误路径脱敏 | 当前 main 已包含全部语义且进一步增加限额、付费确认与路径校验；备份后移除重复草稿 |
| `claude-task-trajectory-evals` / `b01fe8f` | 11 个修改文件、2 个新 JSON、旧调试输出；依赖未合并的旧评测框架 | 不引入旧框架，保留有效业务场景到标准 pytest；原稿、输出与源代码快照在仓库外归档后清理 |
| `codex-public-webgisai` / `700f090` | `Stop-PublicWebGIS.ps1` 的 UTF-8 BOM | 保留并以 `e8d5dc9` 提交、推送原运维分支；其 8 个正在使用的部署文件经审查进入本次主线候选 |

备份目录名 `drafts-20260921-175739`，位于仓库同级 `WebGIS-AI-backups/`。
`manifest.json` 记录各工作树、起点、原始文件、字节数及 SHA256，90 个文件逐一校验。
被移出的 `.runs/`、`scratch/` 和两个 JSON 另保存在备份中的 `retired/`。
备份包含本地运行材料，未提交 Git。原有历史提交和分支保留，没有强推或删除分支。

## 旧评测草稿不合入的依据

- 直接导出检查仅比较两次异常类别，重复 `AttributeError` 等也会通过；成功响应只比较截断的前 400 字符，未验证实际试卷。
- 报告二次生成仅检查少数指标，失败任务可能以两组空数据得出一致。
- `is_busy()` 的 JavaScript 返回函数而未调用；刷新检查没有比较期望项目与实际项目。
- 浏览器输入路径放弃 harness/action 断言；缺少浏览器时又降级为 API，不足以证明原来的页面契约。
- 旧文档的通过率与样本分母不一致，基线缺陷和模型结果来自旧版本，不能当作当前发布证据。
- 整个框架尚不在 main，直接恢复会引入大量未完成评测基础设施。保留的检查复用现有业务服务和 CI，无新的浏览器控制层或付费模型流程。

## 保留的有效场景

`backend/tests/test_classroom_repeated_operations.py` 在临时数据中检查：

1. “下一环节”经当前规则规划和实际执行，保存上海导入→概念→上海探究的状态与事件。
2. 按当前实际图层名隐藏顶层专题图，重读状态后确认底层可见、上下次序保持。
3. 已结束课堂两次成功生成报告，完整统计一致，原课堂证据不变，无作答仍为未采集。
4. 两次实际导出非空学生卷与教师卷，选题一致、DOCX 正文一致，课堂记录不变。
5. 无可用作业明确抛出指定业务错误，未创建导出任务或空白 DOCX；此场景是拒绝路径测试，不计作成功导出。

旧夜光概念题场景由现有 `test_population_assistant.py` 的上下文隔离检查覆盖。
3D 页面契约继续由现有前端测试和发布时浏览器验收负责，不以后台 UI 指令代替页面完成。

## 运维文件完善

保留现有 Cloudflare→Caddy→FastAPI 架构与数据目录。五个 PowerShell 脚本统一
UTF-8 BOM，兼容 Windows PowerShell 5.1。启动脚本从实际 `-RepoRoot` 绑定
数据目录、账号库和 Git SHA，避免继承隔离预览的环境变量；管理员修复进程使用隐藏窗口。
手册改为管理员 `/diagnostics` 获取运行路径，公开 `/health` 仅表示存活。
`.gitignore` 增加 `backend/data/public-runtime/`，运行日志与 PID 不入库。

允许改动：上述测试、`deploy/public-windows/`、`.gitignore` 和本记录。
旧工作树只处理备份清单中的草稿路径。生产库、原教案、其他应用源码及无关改动未修改。

## 验证

- 新增五项真实业务回归：`5 passed`，2.42 秒。
- PowerShell 7 与 Windows PowerShell 5.1：五个脚本均通过语法解析。
- 完整后端：`939 passed, 2 skipped, 154 subtests passed`，303.14 秒（本机 QGIS 3.40.10）。
- Windows PowerShell 5.1 在空临时目录执行停止脚本成功；运行中的正式实例触发备份拒绝保护，未写入数据。
- 四个指定旧工作树最终 `git status --porcelain` 均为空；`git diff --check` 通过。
- 候选 CI、合并与正式发布在以上验收后进行；精确最终提交、资源及启动时间以 GitHub PR 和发布实例的 `release.json` 为准。

这些测试使用合成数据；没有新的外部模型调用，不声称验证真实教师课堂或麦克风。
