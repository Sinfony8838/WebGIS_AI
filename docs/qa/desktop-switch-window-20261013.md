# 圆形 PPT / WebGIS 悬浮切换：候选版本核对

状态：实现与验收中，尚未合并或发布。不能将专项测试通过视为桌面双向切换已完成验收。

## 任务与范围

- 分支：`codex/desktop-switch-window`；起点：`ad9ec5f78c047d7a51cb47033918031824669a48`。
- 允许范围：教师端 PowerPoint 连接器、桌面悬浮球、网页入口、对应检查与使用说明。
- 未修改：地图与 GIS 运算、课堂状态、模型调用、账号库、部署配置、生产数据、其他工作树和主目录原有修改。
- 依赖：教师登录的 Windows 桌面、已安装的 Microsoft PowerPoint、现有 Python/Tk。独立浏览器窗口用于返回 WebGIS。

源码路径：

```text
backend/app/desktop_powerpoint.py
backend/app/desktop_switch_window.py
backend/tests/test_desktop_powerpoint.py
backend/tests/test_desktop_switch_window.py
deploy/desktop-powerpoint/Open-PowerPoint.ps1
deploy/desktop-powerpoint/README.md
frontend/src/components/DesktopPptControls.tsx
frontend/src/components/DesktopPptControls.css
frontend/src/lib/desktopPowerPoint.ts
frontend/src/__tests__/DesktopPptControls.test.tsx
frontend/src/__tests__/desktopPowerPoint.test.ts
docs/qa/desktop-switch-window-20261013.md
```

临时验收页面、依赖副本、构建文件、日志、截图与合成测试数据不进入提交。

## 用户行为与约束

圆形 PPT 图标单击展开 Windows 实时预览，点击“放大”进入原 PowerPoint 窗口；进入后球体显示 WebGIS Logo，按同样流程返回原浏览器窗口。点击收起或 Esc 只关闭预览。拖动只移动，右键提供预览、重新选择窗口和隐藏；网页图标可召回。

原生窗口优先于 Office 自动化连接：已有课件/放映可直接预览，不再因 COM 未连接而启动另一份 PowerPoint。只有没有可用窗口且没有 PowerPoint 进程时，才启动软件起始页；多个窗口需要选择，窗口句柄使用前再次核对进程身份。放映使用原来的放映窗口，不自动保存或关闭文件。

Windows DWM 直接将源窗口合成到本机预览小窗，没有图片回读、上传或逐页 PPT 转换。窗口最小化时预览可能暂停，界面说明限制；预览不可用时明确提示。放大仅操作已校验的原窗口，核实实际前台后换图标。网页悬浮球入口只召回球体，不能传入文件路径、句柄、程序或网址。

原“打开 PPT／切回 PPT”保持兼容；“打开 PPT”是显式选文件入口。独立浏览器网页通过可见标题识别，标题识别不是网站认证检查。没有匹配窗口时，只有点击本机按钮才打开固定正式网址，不自动登录。Codex 侧边网页不属于独立教师浏览器窗口。

## 独立源码复核

已修正：冷启动未完成时“选择窗口”可绕过 pending 保护；右键菜单改为复用同一实例，避免累积；外部窗口放大改用 ShowWindowAsync；同一浏览器句柄内换回 WebGIS 标签时重新识别标题。

关于菜单销毁后可能立即消失的审查疑虑已撤回：Windows Tk 使用原生菜单模态循环，不作为已证实缺陷。

## 已取得的检查记录

| 检查 | 实际结果 |
|---|---|
| 最新前端完整 `npm test -- --run` | 93 文件 / 711 项通过，41.25 秒 |
| 最新前端 `npm run build` | 成功，Vite 构建 8.59 秒；保留已有大资源包提示 |
| 连接器、窗口与图片绑定专项检查 | 75 通过 / 1 跳过，35.18 秒；该记录先于最后的球体焦点调整 |
| 最终预览连接器与窗口专项检查 | 66 通过，9.56 秒；覆盖菜单复用和同句柄切标签 |
| 完整后端第一次 | 1 失败 / 1347 通过 / 8 跳过 / 190 subtests；合成助手任务等待超时 |
| 完整后端第二次 | 1 失败 / 1352 通过 / 8 跳过 / 190 subtests；nonce 拒绝检查中本机 TCP 连接意外中断（WinError 10053） |
| 已发布起点的独立图片绑定检查 | 30 通过 / 1 跳过，31.28 秒 |
| 已发布起点的独立连接器检查 | 18 通过，8.68 秒 |
| 完整后端第三次 | 1355 通过 / 8 跳过 / 190 subtests，667.13 秒；独立保存 JUnit 回执。随后的小范围窗口隐私与拖动阈值调整用最终专项检查覆盖 |
| 新预览版完整后端 | 1372 通过 / 8 跳过 / 190 subtests，866.43 秒；之后两项小修以最终 66 项专项覆盖 |
| 平台模拟方式补充复验 | 窗口模块 46 通过，0.66 秒；Linux 实际执行待 CI |
| PowerShell / C# 辅助脚本 | PowerShell 语法错误 0；C# 编译成功，未调用任何原生方法 |
| `git diff --check` | 通过 |

前两次失败均保留记录，不删除检查、不放宽断言、不改变生产配置。单独重跑通过不足以解释完整检查失败的全部原因。

## 真实桌面记录

使用实际 Windows PowerPoint 与三页合成课件，未使用原教学文件。R9 已验证：

- PPT 图标展开真实编辑窗口预览；已有多个 PowerPoint 窗口时选择明确目标，没有新增文件选择框或再次启动。
- 放大进入原课件，球体改为 WebGIS Logo；网页预览可见，放大返回原 Chrome 窗口，球体再改为 PPT 图标。
- 在合成课件第 2 页启动放映，往返网页后继续原放映；两个红色点状标记仍可见。桌面工具拖动未产生完整线条，因此不声称完整手写线条验收通过。
- 原 PPT 文件 SHA256 前后相同，没有保存；预览截图、往返前后截图只保留在本机证据目录。
- 本轮公网返回 530/1033，网页预览准确呈现了该错误页。这证明窗口切换，不能当作正常课堂页面验收。

公网独立核对：18999/18080 health 均 200；cloudflared 服务 Running，但 ready=503、有效连接数为 0。尝试只重启 cloudflared 时 Windows 服务权限拒绝，已请用户在管理员终端执行。没有停止后端、恢复或覆盖数据。生产 runtime.json 与主目录既有 docs/README.md 的任务前后哈希不变，主目录 7 项变更保留。

R10 已验证小范围拖动：球体从屏幕坐标 (80, 80) 移至 (126, 114)，未触发预览；右键菜单可见且可选择隐藏；隐藏后目标窗口不再可见；实际网页组件调用测试连接器成功召回并显示完成提示。桌面工具的大范围拖动越界受限，未作为产品失败。R11 已加载最终源码，再次选择原第 2 页放映、显示实时预览并以异步方式放大成功，悬浮球正确变为 WebGIS Logo。源码的同句柄切标签补充场景以模拟检查覆盖。

## 合并与发布前仍需通过

1. 完整门禁、最后专项及最终源码真实异步放大复验已通过。新增测试的 Linux 运行结果仍需 GitHub CI 确认；模拟 WinDLL 的测试不要求系统提供真实 WinDLL。
2. 公网隧道恢复后，用正常 WebGIS 页面补齐课堂验收；错误页的往返不能代替。
3. 完整手写线条、冷启动、Office 提示框以及跨屏/混合 DPI 仍属于未完成的真实场景；关闭/回收句柄保护已做模拟检查。
4. 源码独立评审、合并到 main；按既有维护规范停写备份后发布并复核公网入口。未完成这些步骤不得记录为已上线。

代码回退使用起点提交，保留新产生的教学数据。停止连接器不会退出 PowerPoint；本次不需要恢复课堂数据。

## 网页内 PPT 方案参考

[ONLYOFFICE 官方集成说明](https://api.onlyoffice.com/docs/docs-api/get-started/how-it-works/)采用独立文档服务与宿主存储的集成方式；引入它需要单独评估部署、权限与许可证，不是更换一个网页预览组件即可完成。

[pptx-renderer 作者仓库](https://github.com/aiden0z/pptx-renderer)明确列出动画播放、页间切换和部分高级内容的限制。没有依据承诺任意旧课件在网页中完整还原。本任务保留已有页面预览作为可选入口，优先实现系统 PowerPoint 的实际教学切换。

上述结论与验收范围均限于本任务；没有改动无关工作区、原课堂和原课件。
