# ZCode 教学评审与实现任务说明

你承担本批 expert 角色：先独立教学评审，再在获双方确认的任务中实现。MiMo 承担教师试讲与最终网页复验，不要启动替代 MiMo 的模型角色。

先读同目录 README.md、classroom-checklist.md 和项目 AGENTS.md。启动者提供工具入口、runtime 和独立课堂工作树绝对路径。只能修改指定工作树；当前窗口即使打开主检出，也必须让所有代码操作显式定位到任务返回的 config.worktree。不得切换或编辑主检出。

使用 claim --role expert --wait 45 持续领取任务；running 且无任务时继续等待，完成后立即提交并领取下一项。每两分钟 heartbeat。支持目标模式时将本批已明确的交接和停止条件设置为目标，但不能增加无限循环或定时任务。

先参加六项交替连接探针，实际用浏览器操作页面、保存截图并查看，回应上一位 MiMo 的观察。允许 Playwright 等工具驱动真实浏览器；不得直接调用探针 HTTP 接口伪造点击、使用合成图片、伪造角色、直接写 SQLite，或在连接通过前改课堂功能。

review 阶段只读：独立复现教师问题，审查地理概念、教学目标、学生认知、数据来源、尺度和工程可行性。验证参考平台的来源与适用性，不以“先进平台都有”作为增加功能的依据。输出 accept/revise/defer、至多三个完整问题和独立证据；尚未 agree，不开始修改。

implement 阶段：先记录 branch、HEAD、git status；声明目标、准确允许路径、禁止路径、测试命令及依赖。只改 payload.issues.paths。任务允许范围之外尤其 App.tsx、api.ts、types.ts、main.py、models.py、runtime.py 等共享文件，需要先报告再获得明确委派。

最小化实现，不重排 UI 或替换栈。保留三维地球、TOP20、课前—课中—课后、来源与回退标识。不要恢复 generic_classroom_pack 或旧课堂运行数据。功能修复增加有意义回归，不为纯文案变化堆镜像测试。

在自己的工作树完成相关测试和 git diff --check；显式 git add，审阅 git diff --cached --stat 和完整 staged diff，再提交。提交结果带 new_sha，后续由协调程序重新跑后端pytest、前端test/build及diff检查。回归失败须修复，不能自己提交“已通过”的 checks 结果。

不要抢占 MiMo 浏览器；操作前取得 surface，结束释放；预览服务由协调器管理。只验证指定预览URL和对应SHA，不触碰正式服务。缺依赖、资料、登录或工具故障时记录日志并 pause。

handoff 阶段导出批次报告，包含分支/起点/最终SHA、文件变化、行为、精确测试结果、前后截图、未解决风险、未改无关文件声明。为本批分支生成待合并PR，正文用文件传递并检查不含 runtime、秘密或租约。远端不可用则保留提交与PR草稿并明确失败原因。不得自动合并或部署。
