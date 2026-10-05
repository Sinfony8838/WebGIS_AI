# 第 0 阶段备份与隔离恢复

任务：补齐恢复边界，不修改课堂、地图、助手、API 或数据读取路径。
分支：`codex/stage0-backup-recovery`。
起始提交：`01d31fba7c4d6a4bf9c020f397407dfb1806c335`；专用工作树由该提交建立，随后 fetch 核对主线未变化。

允许路径：备份/恢复及合成验收脚本、此验收记录、运维说明、专用 Windows 恢复 CI。
禁止路径：前后端业务源码、认证库/运行时数据、生产构建、主目录未提交文件、原 DOCX。
依赖：Windows PowerShell 5.1 或 PowerShell 7；测试使用临时目录中的合成字节，不要求 Python、QGIS、Office 或用户登录。

修改文件：

- `deploy/public-windows/Backup-PublicWebGISData.ps1`
- `deploy/public-windows/Recovery.Common.ps1`
- `deploy/public-windows/Restore-PublicWebGISBackup.ps1`
- `deploy/public-windows/Test-RecoveryTools.ps1`
- `deploy/public-windows/MAINTENANCE.md`
- `.github/workflows/recovery-tools.yml`
- `docs/qa/stage0-recovery-20261005.md`

## 交付行为

- `Backup-PublicWebGISData.ps1 -InventoryOnly` 输出名称、大小及白名单构建元数据，不哈希数据库或创建文件。
- 实际备份保留旧数据布局，增加知识目录、教学地图及芬兰人口资源，记录真实数据路径、SHA、前端资源名、可选上一版本和外部依赖边界。
- 完整 v2 清单仅在复制和哈希核对成功后写入；查询监听状态失败即拒绝备份，明确的在线备份仍标记为不保证一致。
- 隔离恢复只接受完整 v2 清单，校验全部文件后恢复到全新目录；拒绝覆盖、路径穿越和指向源数据的 Junction。
- 不迁移知识目录，不恢复或启动生产实例；v1 备份继续按运维说明人工恢复。

## 验收方式

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy/public-windows/Test-RecoveryTools.ps1
pwsh.exe -NoProfile -File deploy/public-windows/Test-RecoveryTools.ps1
git diff --check
```

每次运行建立唯一临时夹具，保留 `acceptance.json`、备份和隔离恢复回执便于核查。

2026-10-05 本机结果：

| 检查 | 结果 |
|---|---|
| Windows PowerShell 5.1，`-NoProfile -ExecutionPolicy Bypass -File` | 19 PASS、0 FAIL，退出码 0 |
| PowerShell 7，`-NoProfile -File` | 19 PASS、0 FAIL，退出码 0 |
| 四个 PowerShell 脚本静态解析 | 0 个解析错误；均为 UTF-8 BOM，兼容 Windows PowerShell 的中文夹具路径 |
| `git diff --check` | 退出码 0 |

实际解释器分别为 `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` 和
`C:\Users\zcyxn\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe`。
对应的本机证据文件：

- `C:\Users\zcyxn\AppData\Local\Temp\webgis-recovery-test-500f0061dc97487bbe24e83ac18433ac\acceptance.json`
- `C:\Users\zcyxn\AppData\Local\Temp\webgis-recovery-test-e346ebeb1e2e45cf8b3b1e62b34a25a0\acceptance.json`

19 项覆盖完整复制、补充资源、空目录、源数据根 Junction、目标祖先 Junction、嵌套链接拒绝、损坏和穿越清单、
重复/漏列文件、已有目标保护、WhatIf、旧清单拒绝、监听查询失败、复制期间后端出现及在线备份标记。
新增 Windows CI 复用上述合成脚本；此记录不将尚未执行的远程 CI 视为已通过。

夹具包含伪认证文件、项目状态、外置图层、题库图像、报告、Workflow、人口包、模型占位和教材资源；不含真实账户或凭据。
监听状态和失败权限使用受控替身；文件复制、SHA-256 和 Junction 操作使用真实文件系统。

需要区分：文件系统验收不是 SQLite 内容正确性、应用完整启动、真实服务停写、公网或课堂验收。
不运行业务全量测试、模型、QGIS、COM 或浏览器：此次没有修改这些业务模块。
后续第 1 阶段先处理资源绑定，第 2 阶段再处理数据加载等问题；本任务止于第 0 阶段。

## 本机只读清单核对

从实际发布工作树执行 `-InventoryOnly`，得到代码 SHA `01d31fb…`、前端资源 `assets/index-4D9ECoLu.js`，
知识目录、教学地图和芬兰人口资源三项均存在；合计 478 个文件、582,922,338 字节，无缺失资源警告。
数据的真实目标仍为主目录生产 `backend/data`；本次只读取文件系统元数据，不执行真实备份或恢复。
上一版本候选 `63557e97d8a0` 来自既有发布前备份记录，不代表本轮做过该版本的业务验收。

未修改主目录未提交变更、生产数据、依赖、构建、原始 DOCX 或业务源码；未安装依赖、启动/停止服务、部署或调用真实模型。
工具代码的撤回仅涉及上述文件；不删除已经生成的备份或恢复数据。部署与生产恢复须由集成负责人另行安排。
