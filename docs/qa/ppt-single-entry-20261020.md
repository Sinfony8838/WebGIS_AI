# PPT 单图标入口与直接预览验收

## 任务与边界

- 分支：`codex/ppt-single-entry`；起点：`8f27bb72846114f490d2c857c7b6247e935964ba`（实施前与远端 main 核对）。
- 工作树：独立的 `ppt-single-entry/WebGIS-AI`；主工作区原有的文档修改和未跟踪文件均未修改、暂存或移动。
- 目标：顶栏仅保留一个 PPT 图标，点击直接预览；首次无课件时选文件，放大进入原生 PowerPoint，更换课件在悬浮图标右键菜单。
- 允许范围：顶栏接入、PPT 控件与相关样式、本机连接器、对应测试及本文档；由同一负责人顺序修改共享 App 接入。
- 禁止范围：生产数据、原始课件、其他工作树、环境文件、原有缓存与历史验收记录。新依赖仅安装在本工作树。
- 依赖：教师端 Windows、已安装的 PowerPoint、声明 `preview` 能力的新版连接器；网页和连接器需同步更新。

## 行为与接口

- 移除顶栏“打开 PPT”“切回 PPT”“页面预览 PPT”；36px 图标与相邻控件对齐，去除切换角标。
- 新增本机 `preview` 操作及能力声明，保留旧 `open` / `focus` / `switcher`；内部更换文件动作不对浏览器开放。
- 一次操作覆盖窗口解析、可选的原生文件选择、打开和预览；Tk 只执行短 UI 回调，选文件在原操作工作线程内完成，不嵌套申请操作锁。
- 已绑定窗口优先复用；多窗口需明确选择；PowerPoint 启动页不当作课件。取消安静结束，故障不自动重新提交。
- 首次选文件后尝试返回原有效 WebGIS 窗口；实际进入目标应用仍通过预览窗的“放大”。窗口身份验证、原生缩略图、页码和笔迹保留机制沿用。
- 旧网页预览组件及渲染 API 保留，本入口不会自动调用网页渲染。

## 自动与浏览器检查

| 检查 | 结果 |
| --- | --- |
| 前端 `npm test -- --maxWorkers=2 --minWorkers=1` | 93 文件、714 测试通过 |
| 前端 `npm run build` | 通过，保留现有大包体积提醒 |
| 后端完整测试 | 1449 通过、8 跳过、190 subtests 通过；1 项受临时放行变量影响，移除变量后独立复验通过 |
| 最终 PPT 连接器专项 | 100 项通过，包含末次审阅新增的无 WebGIS 绑定负向用例 |
| `git diff --check` | 通过 |
| 顶栏布局 | 1920、1366、1280 三个物理宽度，各 100%、125%、150% 浏览器像素比例及对应 CSS 视口，9/9 通过 |
| 页面行为 | 真实 App 中仅一个图标；旧连接器先提示更新；模拟连接器只收到一次 preview POST，取消不打开网页预览 |
| 隔离健康检查 | `/health`、`/ui/capabilities` 均 HTTP 200 |
| 三维外壳 | 实际 App 的 Cesium 画布存在；外部影像瓦片保真未据此宣称通过 |

布局使用本工作树前端 5831 和隔离后端 18661，运行时数据在新临时目录，未接生产目录。连接器行为的浏览器检查显式模拟了本机响应，未操作生产连接器。缩放是浏览器设备比例与 CSS 视口模拟，不能替代 Windows 实际混合 DPI 验收。

修复前，1280/150% 下旧课堂菜单规则会强制换行，菜单顶端超出页顶且与搜索区重叠。现改为有界单行横向滚动，PPT 图标可见可达，品牌、功能区、搜索区互不重叠；详细尺寸见 [layout-results.json](ppt-single-entry-20261020/layout-results.json)。

![1920 顶栏](ppt-single-entry-20261020/header-1920.png)
![1366 顶栏](ppt-single-entry-20261020/header-1366.png)
![1280 顶栏](ppt-single-entry-20261020/header-1280.png)
![1280 / 150% 顶栏](ppt-single-entry-20261020/header-1280-scale150.png)

## 实机与发布限制

- **UNRUN：真实 PowerPoint 与 WebGIS 连续往返、实际页码/原生笔迹保留、实机拖动贴边和混合 DPI**。Computer Use 的 Node 内核启动因 `CreateProcessSecurityEnvironment failed (HRESULT = 0x80070020)` 失败，未据自动测试宣称实机通过。
- 首次全量后端测试在约 47% 处，未改动的 `sherpa_onnx` 语音模型异步预热发生原生栈溢出，未产生成功汇总；同期间首次前端构建也因系统提交内存不足失败。进程退出并释放内存后，前端构建通过。
- 初次完整前端测试为 713 通过、1 项新测试断言不兼容 Vitest 2；修正断言后完整重跑为 714/714。
- 后端首次完整运行生成的本工作树 `backend/data` 已核对为普通目录、无 Junction，创建时间与测试一致。完整重跑仅为这个测试目录设置 `WEBGIS_AI_ALLOW_EXISTING_DATA=1`。该变量被负向保护测试的子进程继承，使其本应拒绝的收集操作通过，造成唯一失败；移除变量后该测试独立复验为 1 passed（2.80s）。测试数据在核对绝对路径与非链接属性后，保留移至本工作树 `.pytest_cache/ppt-single-entry/backend-data`，未删除或连接生产数据。
- 当前只交付 PR，不合并、不部署、不重启生产连接器。上线时先完成实机验收，再同步发布网页与教师端连接器；回滚仅恢复对应代码，不还原课堂数据。


## 最终检查命令

```powershell
# 完整后端重跑：空的语音模型搜索目录，避免使用本机实际模型
$env:WEBGIS_AI_ALLOW_EXISTING_DATA = '1'
$env:WEBGIS_AI_VOICE_MODEL_STABLE_ROOT = Join-Path $env:TEMP 'webgis-ppt-empty-voice-models'
& "$env:LOCALAPPDATA/Programs/Python/Python312/python.exe" -m pytest backend/tests -q
# 1449 passed, 8 skipped, 190 subtests passed, 1 failed (guard env inheritance), 301.39s

# 归档本轮测试数据并移除临时放行变量后
& "$env:LOCALAPPDATA/Programs/Python/Python312/python.exe" -m pytest backend/tests/test_standard_entry_isolation.py::test_collection_refuses_when_live_instance_markers_exist -q
# 1 passed, 2.80s
& "$env:LOCALAPPDATA/Programs/Python/Python312/python.exe" -m pytest backend/tests/test_desktop_switch_window.py backend/tests/test_desktop_powerpoint.py -q
# 100 passed

# frontend 目录
& 'C:/Program Files/nodejs/npm.cmd' test -- --maxWorkers=2 --minWorkers=1
# 93 files, 714 passed, 83.02s
& 'C:/Program Files/nodejs/npm.cmd' run build
# success, 506 modules transformed
```

临时后端 18661 与前端 5831 均已结束，监听端口检查未返回占用者。生产连接器 18998、生产网站和 PowerPoint 未修改或重启。
