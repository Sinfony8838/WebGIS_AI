# 教师电脑 PowerPoint 打开与切回

- 起点：095ddda959b6bf8976b924fb0536065cc0926b48，origin/main。
- 分支：codex/desktop-powerpoint-open。
- 独立工作树：desktop-powerpoint-open/WebGIS-AI；没有生产数据 Junction。使用本项目已有、版本一致的 node_modules 的独立副本，没有安装依赖。
- 范围：PPT工具栏、新增本机请求/按钮模块及测试，独立标准库连接器、Windows PowerPoint工作脚本/启动器和说明。没有改动GIS数值、持久化格式、模型调用、项目权限或原课件。

## 行为

“打开 PPT”在教师电脑选择原文件并使用 PowerPoint 打开；匹配完整文件路径后复用现有课件窗口。“切回 PPT”复用已选择课件或当前活动课件。窗口最小化时才恢复；不重置页码、视图、笔迹或放映。“页面预览 PPT”保留原网页渲染与笔迹链路，原预览失败流程仍需教师明确选择简易预览。

本机连接器独立于FastAPI、Store与生产数据根，只接受open/focus操作；拒绝路径/文件上传、未知来源、DNS rebinding Host、代理头、缺少本机随机校验值及同时进行的第二个原生操作。不自动保存/关闭PowerPoint，不修改Office信任中心或Windows电源设置。PowerPoint COM默认自动化宏策略为Low；本次程序化打开暂用已有信任中心策略，已有ForceDisable保留，finally恢复先前模式。[Microsoft AutomationSecurity说明](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.application.automationsecurity)

## 已完成检查

- 本机连接器测试：18 passed，8.37秒。
- 前端定向检查：3文件7测试通过，包括原PPT预览失败提示。
- 完整前端：93文件707测试通过，25.82秒；TypeScript/Vite构建通过，3.19秒。现有大分块警告仍存在。
- 完整Windows后端：1321 passed、8 skipped、180 subtests passed，450.30秒。
- Windows PowerShell语法解析通过；无已打开课件时focus返回明确失败提示，不启动空PowerPoint。
- 合成文件沿用QA_20261008_three_pages-r2.pptx，3页，SHA256 e9a1102b47369c1d2a9bdbe821e8a683b0d224e1e2a1b7de33d2861c82f85342。没有读取或修改私人原PPT。

## 待完成及环境限制

真实网页按钮已经在独立19009后端/5173前端出现，并触发本机异步操作；首次自动化验收没有发现可操作的文件选择窗口。检查进程窗口站/桌面为WinSta0/Default，不能将此现象确定归因为Windows非交互会话。随后移除了选择框的不可见Form所有者，改用独立顶层文件选择框，尚待复验。桌面工具明确返回“product policy blocks this app”并拒绝启动PowerShell；没有改用其他UI方法绕过该限制。仅结束经PID、父进程和创建时间核对的本任务测试选择工作进程及连接器，确认当时没有PowerPoint进程；未结束任何原有服务。已请求教师在交互桌面手动启动连接器。

首次打开、同一文件重复打开、后台切回、取消选择、实际窗口/页码/笔迹保留及原文件哈希复查必须在交互桌面实测后分别记结果，目前不计通过。网页预览旧链路的单元回归通过不代替本机PowerPoint验收。

之前的public-teacher-release工作树现已不存在，原18999/18080端口未监听；当前正式运行路径等待用户确认。没有根据旧聊天记录重建生产环境或恢复教学数据。合并/上线状态须在实际完成后记录，不以本机开发页替代正式部署。
