# 教师电脑 PowerPoint 打开与切回

- 起点：095ddda959b6bf8976b924fb0536065cc0926b48，origin/main。
- 分支：codex/desktop-powerpoint-open；草稿 PR83。
- 独立工作树：desktop-powerpoint-open/WebGIS-AI；没有生产数据 Junction。使用版本一致的独立 node_modules 副本，没有安装依赖。
- 范围共11文件：PPT工具栏、新增本机请求/按钮及测试，独立连接器、Windows工作脚本/启动器和说明。没有改动GIS数值、持久化格式、模型调用、项目权限或原课堂文件。

## 最终行为与真实修复

“打开 PPT”启动/复用教师电脑的 PowerPoint，由 PowerPoint 自带 FileDialog 选择文件，再验证路径与后缀、匹配完整路径并复用课件。“切回 PPT”返回已选择或当前活动课件。原“页面预览 PPT”及其笔迹与失败流程保留。

实测确认隐藏控制台中的 WinForms ShowDialog 持续等待、选择框不可见，不能确定其底层 Windows 原因。改用 Office 自带选择框后已实际显示并选取合成课件。随后发现本机 Office 的 Application.HWND、DocumentWindow.HWND 为空，打开成功但切换报错。最终使用当前用户会话内、由 POWERPNT 持有的唯一匹配 PPTFrameClass 窗口；按 Office 窗口标题匹配，歧义时拒绝切换，不猜测窗口。放映使用已有 SlideShowWindow.HWND。仅最小化时恢复，不自动保存、关闭或重置页码。

连接器只绑定127.0.0.1，只接受open/focus；路径由本机选择框引入，不接受网页传入路径/文件。严格校验Origin、Host和本机随机校验值，拒绝代理和并发原生操作。不会读取项目配置、登录cookie、模型密钥、认证数据库或教学数据。

打开遵循已有Office信任中心策略，已有ForceDisable保持，finally恢复原自动化模式；不接受安全/授权提示。[Microsoft AutomationSecurity](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.application.automationsecurity)；[PowerPoint FileDialog](https://learn.microsoft.com/en-us/office/vba/api/powerpoint.application.filedialog)。

## 检查与证据边界

- 基线10b6ea815c0af2f14ba845e8a1ba630dea27fac7：完整前端93文件707测试通过（23.64秒），TypeScript/Vite构建通过（4.04秒）；完整Windows后端1321 passed、8 skipped、180 subtests passed（450.30秒）。这些检查不能代替后续Windows原生改动验收。
- 同一基线CI38040616675的Backend tests与Frontend tests and build均成功。最终原生修复提交须独立检查CI。
- 后续连接器定向回归：18 passed（8.41秒）。首次重复运行被既有测试数据标记保护拒绝、未执行测试；确认专用工作树backend/data是独立普通目录，既有标记来自本任务验收，再仅对此测试子进程显式设置WEBGIS_AI_ALLOW_EXISTING_DATA=1。未删除或读取标记文件内容；本组测试使用独立HTTP服务和fake runner，不打开业务存储。
- PowerShell语法解析及diff检查通过；C#窗口定位代码已由真实连接器编译并执行。
- 合成课件QA_20261008_three_pages-r2.pptx为3页，SHA256 E9A1102B47369C1D2A9BDBE821E8A683B0D224E1E2A1B7DE33D2861C82F85342；实际打开、翻页、重复选择之后哈希一致。没有打开私人原课堂文件。

真实浏览器环境是独立19009后端/5173前端、本机管理员、合成数据和stub模型，不能称为公网Demo或正式部署验收。通过computer-use观察实际PowerPoint，未执行模型或GIS任务。

| 场景 | 已观察结果 |
|---|---|
| 页面入口/连接失败 | 打开、切回、页面预览三个入口存在；中文断连提示不自动重发POST。720p完整对话框、关闭按钮焦点与Esc关闭已实测。 |
| PowerPoint已有实例，打开课件 | Office选择框可见，合成3页课件实际打开；最初句柄错误已修复。 |
| 最小化后切回 | 真实结果focused、foreground=true；课件恢复，仍为第2页。 |
| 重复选择同一完整路径 | 原窗口id未变，仅一个课件窗口，仍停第2页；没有重复打开。 |
| 取消选择 | Esc关闭Office选择框，原课件和第2页保留；网页按钮恢复。 |
| PowerPoint未运行 | 关闭本次合成验收窗口后核实没有POWERPNT进程；从网页自动启动新进程并显示Office选择框。新窗口模态输入受桌面工具定位限制，完整首次选取后的打开结果尚待完成。 |
| 放映/实际笔迹保留 | 未完成，不计通过。 |

Windows非交互桌面不能作为不可见选择框的已证实根因。桌面工具禁止操作PowerShell等终端，本机连接器由用户手动启动；没有绕过限制。只结束经PID、父进程、创建时间及执行阶段核对的本任务不可见选择工作进程。computer-use直接启动/关闭的Office窗口仅为本次合成课件验收，不是连接器自动关闭行为。

临时执行阶段和异常诊断已从源码移除，诊断与截图只留本机scratch/验收目录，不提交。现有大分块警告保持。

## 发布与剩余门槛

用户确认正式目录没有迁移。沙箱外只读核实历史public-teacher-release/WebGIS-AI目录及Git登记已缺失，主目录backend/data为空，18999/18080未监听；Cloudflared服务仍运行。删除执行者和底层原因未知，不从时间戳或旧聊天推断。最近已知备份仅完成文件存在性与大小核对，尚未做哈希校验或恢复，后续恢复需确认恢复点及备份之后的数据差异。

原生首次完整打开、放映/笔迹保留、最终提交CI及正式环境恢复边界仍须完成。保留草稿，不合并、上线或启动空生产环境。保护视图、宏安全、不同Office版本/显示器、Windows拒绝前台切换及重名窗口歧义尚未现场复现，不以mock测试充当证明。
