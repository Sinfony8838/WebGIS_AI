# WebGIS-AI 网站运维与版本发布规范

本规范适用于 `https://webgisai.com` 的低成本 Windows 单机发布。目标是在不破坏教师账号、教案、上传文件、GIS 产物、离线语音模型和 QGIS 环境的前提下，可重复地完成日常巡检、版本更新、故障恢复和回滚。

## 1. 生产架构与责任边界

```text
GitHub main（唯一代码来源）
  -> 本机生产构建 frontend/dist
  -> Caddy 127.0.0.1:18080
       -> 静态前端
       -> FastAPI 127.0.0.1:18999
  -> cloudflared Windows 服务
  -> Cloudflare HTTPS
  -> https://webgisai.com

持久数据：backend/data（不进入 Git，不随代码更新覆盖）
外部能力：QGIS、MiniMax、高德、天气等（分别验证，不由 health 单独证明）
```

当前方案适合个人展示、答辩和小规模试用，不是高可用云服务。电脑关机、休眠、断网，或本机后端/Caddy 停止时，网站会离线。

## 2. 六条强制原则

1. **只发布 `origin/main` 上经过测试和评审的完整提交。** 不直接发布聊天结果、未提交文件或临时功能分支。
2. **代码与数据分离。** Git 更新不得删除、替换或初始化 `backend/data`；其中的账号库、状态、上传文件、输出、工作流和语音模型都属于生产数据。
3. **先验证，后切换。** 测试和审查在专用工作树进行；生产切换安排短维护窗口。
4. **每次发布可追溯。** 记录完整提交 SHA、前端资源名、发布时间、备份位置、验证结果和已知限制。
5. **失败优先回滚。** 线上核心流程异常时，先恢复上一已知良好版本，再在新分支修复，不在生产目录中临时改代码。
6. **不夸大验收。** `/health` 成功不等于真实登录、外部 AI、麦克风、QGIS 工作流、文件下载和不同网络浏览器均已通过。

## 3. 目录与机密管理

| 内容 | 位置 | 管理规则 |
|---|---|---|
| 代码 | Git 仓库 | `main` 为唯一集成源；功能改动使用独立分支和工作树 |
| 生产数据 | `backend/data/` | 不提交 Git；更新前停机备份 |
| 生产前端 | `frontend/dist/` | 由固定提交重新构建；不得手工修改 |
| 运行日志与 PID | `backend/data/public-runtime/` | 可删除后重建；故障时先保留日志 |
| API Key | Windows 用户/服务环境变量 | 不写入 Git、文档、截图或聊天 |
| Tunnel Token | cloudflared Windows 服务配置 | 不复制到 Git、日志或公开渠道 |
| 本地备份 | 仓库同级 `WebGIS-AI-backups/` | 含敏感数据，不同步到公开仓库 |

建议启用 Windows 磁盘加密，并对备份目录设置仅本人可读权限。需要异地备份时，应先加密，再复制到受控存储。

## 4. 日常巡检

每次演示前、版本更新后和故障恢复后运行：

```powershell
.\deploy\public-windows\Test-PublicWebGIS.ps1
```

若脚本位于独立部署工作树，而生产代码/数据在另一目录，可显式指定：

```powershell
.\deploy\public-windows\Test-PublicWebGIS.ps1 `
  -RepoRoot "C:\Users\zcyxn\Desktop\WebGIS-AI"
```

巡检至少覆盖：

- `cloudflared` Windows 服务处于 `Running / Automatic`；
- 后端和 Caddy PID 对应正确进程；
- `18999` 后端、带公网 Host 头的 `18080` 代理均返回非空内容；
- 公网 `/health` 与首页返回非空内容；
- 公网首页引用的版本化 JS 与本机构建一致；
- 当前浏览器能登录，地图能加载，控制台无阻断性错误；
- 真实 QGIS 工作流、产物打开、AI、语音分别按本次用途抽检。

本机代理的 TUN/Fake-IP 可能把域名解析为 `198.18.*`、`198.19.*` 或 `28.*`。脚本会给出警告；此时必须再用关闭代理的浏览器或手机流量访问公网链接，不能仅凭本机失败判定网站离线。

## 5. 标准版本更新流程

### 5.1 开发与集成

1. 从最新 `origin/main` 创建专用工作树和分支，例如 `codex/<task>`。
2. 明确允许修改的路径、禁止路径、验收项和依赖；不得覆盖他人的脏工作区。
3. 完成功能后运行与改动区域匹配的测试。
4. 提交明确的 commit，推送任务分支并创建 PR。
5. 由集成负责人评审并合并；冲突必须逐项理解，不能整边覆盖。
6. 合并后重新获取远端，确认待发布 SHA 与 `origin/main` 完全一致。

标准验证门禁：

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest backend/tests -q

Push-Location frontend
& "C:\Program Files\nodejs\npm.cmd" test
$env:VITE_API_BASE_URL = "https://webgisai.com"
& "C:\Program Files\nodejs\npm.cmd" run build
Pop-Location

git diff --check
```

测试失败、工作树存在不明修改、提交不等于计划发布 SHA、数据备份失败时，停止发布。

### 5.2 发布前记录

在发布记录或 PR 中写清：

- 完整提交 SHA；
- 改动范围和用户可见行为；
- 后端测试、前端测试和构建的精确结果；
- 数据结构是否变化；
- 是否依赖新的环境变量或外部服务；
- 上一已知良好 SHA；
- 计划回滚条件。

建议给稳定版本打注释标签，例如 `web-v2026.09.10.1`。标签只能指向已合并且验证通过的 `main` 提交。

### 5.3 维护窗口、停机备份与启动

更新前先告知使用者短暂停机。随后在仓库根目录执行：

```powershell
.\deploy\public-windows\Stop-PublicWebGIS.ps1

.\deploy\public-windows\Backup-PublicWebGISData.ps1

.\deploy\public-windows\Start-PublicWebGIS.ps1
```

备份脚本默认拒绝在后端运行时复制，以避免 SQLite 与 JSON 快照不一致。不要把 `-AllowLiveBackup` 当作日常选项。

启动脚本会：

- 读取 Windows 用户/机器级运行环境变量；
- 自动恢复常见 QGIS 安装路径；
- 使用 `https://webgisai.com` 构建生产前端；
- 仅在回环地址启动后端和 Caddy；
- 校验本地健康状态；
- 在 `backend/data/public-runtime/release.json` 记录实际提交和前端资源版本。

启动参数 `-RepoRoot` 同时决定代码、`backend/data` 和账号库。脚本会覆盖继承的
`WEBGIS_AI_DATA_DIR`、`WEBGIS_AI_AUTH_DB` 及 `WEBGIS_AI_BUILD_SHA`，避免沿用隔离预览的配置。
生产数据如位于另一目录，应预先核实该工作树的 `backend/data` Junction 指向正确实例。
脚本已有服务复用提示不代表新代码已经发布；更新版本仍需先停止、备份再启动。

### 5.4 分层验收

发布后按以下顺序验收，上一层失败时不继续宣称成功：

| 层级 | 验收内容 | 成功标准 |
|---|---|---|
| L1 进程 | cloudflared、Python、Caddy | 服务/进程存在，PID 与名称一致 |
| L2 本机 | `18999/health`、带公网 Host 的 `18080` | HTTP 200 且正文非空 |
| L3 公网 | 域名首页、`/health`、HTTPS | HTTP 200、正文非空、证书有效 |
| L4 版本 | 公网 JS 与本机构建 | 版本化资源名一致 |
| L5 账号 | 管理员/教师登录与退出 | Secure/HttpOnly Cookie 正常，越权访问被拒绝 |
| L6 核心业务 | 地图、教案、课堂、报告、产物 | 关键路径无阻断，旧数据仍可读取 |
| L7 外部能力 | QGIS、MiniMax、地图、天气、语音 | 按能力逐项运行真实样例 |

发布后观察 15 分钟日志，再结束维护窗口。只做了 L1-L4 时，应明确报告“网站已上线，但业务/设备/外部服务尚未完成现场验收”。

## 6. 回滚规范

### 6.1 触发条件

出现以下任一情况应优先回滚：

- 登录或权限系统不可用；
- 生产数据无法读取或发生非预期覆盖；
- 首页、核心地图或课堂主流程阻断；
- QGIS 工作流大面积失败且新版本引入；
- 错误率持续上升，无法在维护窗口内确认修复。

### 6.2 代码回滚

1. 记录失败版本 SHA、日志和复现步骤。
2. 停止公网源站。
3. 在新的恢复工作树中检出上一已知良好标签/提交；不要对脏工作区执行 `reset --hard`、`clean` 或整库覆盖。
4. 保持当前 `backend/data` 不变，重新构建并启动旧代码。
5. 依次完成 L1-L7 中与故障相关的验收。
6. 用新的修复 PR 恢复主线，不重写 `main` 历史。

### 6.3 数据恢复

代码回滚通常不应恢复数据。只有确认数据被错误迁移、删除或损坏时才恢复备份：

1. 立即停止后端和 Caddy，保留损坏现场副本；
2. 检查备份目录中的 `backup-manifest.json`、文件数量和关键 SHA-256；
3. 先在隔离目录恢复并启动验证；
4. 明确恢复点会丢失哪些发布后的数据；
5. 获得负责人确认后再替换生产数据；
6. 完成账号、项目、上传文件、工作流和产物的逐项核验。

不要把“恢复代码”和“恢复数据”捆绑成同一个默认动作。

## 7. 备份策略

最低建议采用 `3-2-1` 思路：生产数据一份、本机另一磁盘备份一份、加密的异地备份一份。

| 类型 | 频率 | 保留建议 | 内容 |
|---|---|---|---|
| 发布前备份 | 每次发布 | 至少保留最近 5 个稳定版本 | 全部 `backend/data`，排除运行日志 |
| 日常备份 | 每天有使用时 | 7 天 | auth、state、uploads、outputs、workflows |
| 周备份 | 每周 | 4-8 周 | 全量数据与关键文件 SHA-256 |
| 月度恢复演练 | 每月 | 保留演练记录 | 在隔离目录启动并验证登录/项目/产物 |

备份成功的定义不是“文件已复制”，而是清单存在、关键哈希可读，并至少定期完成一次隔离恢复演练。

## 8. 常见故障处理

### 公网 502 / 1033

1. 检查 `cloudflared` 服务是否运行、Tunnel 是否 Healthy；
2. 检查 `18080` 和 `18999` 是否监听；
3. 检查 Caddy/后端日志；
4. 确认 Cloudflare Route 仍指向 `http://localhost:18080`；
5. 确认本机代理没有阻断 cloudflared 到 7844 端口的连接。

### HTTP 200 但页面空白

1. 检查公网正文长度，不能只看状态码；
2. 用 `Host: webgisai.com` 请求本机 `18080`；
3. Caddy 必须使用任意 Host 的站点地址，并通过 `bind 127.0.0.1` 限定回环监听；
4. 对比公网与本地版本化 JS 名称。

### 登录失败或 401

1. 检查 `WEBGIS_AI_AUTH_MODE=users`；
2. 确认 `backend/data/auth/auth.db` 存在且来自正确数据目录；
3. 检查 Cookie 的 `Secure`、`HttpOnly` 与域名；
4. 不通过删除账号库“修复”登录问题。

### QGIS 工作流失败

1. 管理员登录后从 `/diagnostics` 查看实际 `qgis_root` 和初始化警告；公开 `/health` 只返回最小存活状态，`/ui/capabilities` 用于前端能力展示；
2. 确认 `QGIS_ROOT` 指向包含 `bin/python.exe` 的安装根目录；
3. 区分 QGIS 环境错误、数据错误、坐标系错误和工作流逻辑错误；
4. 运行一条真实工作流并打开产物，不能只以健康检查代替。

### AI 或语音不可用

1. 只检查配置来源和“是否存在”，不要打印 API Key；
2. 分别验证文本 AI、视觉、图像生成、浏览器麦克风和离线 ASR；
3. 外部余额、限流、网络失败要与本地代码故障分开报告。

## 9. Windows 可用性建议

- `cloudflared` 保持 `Automatic`；
- 演示期间禁用自动休眠，但不要关闭系统安全更新；
- 后端和 Caddy 当前由启动脚本管理，Windows 重启后需要重新运行启动脚本；
- 若要无人值守长期运行，应另行评审后配置受限服务账号和“登录/开机后启动”任务，并验证环境变量、工作目录和日志权限；
- 不要把 Tunnel token 或 API Key写进任务计划程序的可见参数；
- 每月至少检查一次域名续费、Cloudflare 状态、磁盘空间和备份可恢复性。

## 10. 标准发布记录模板

每次更新复制以下模板到 PR、发布记录或工单：

```text
版本/标签：
发布日期：
发布负责人：
目标提交（完整 SHA）：
上一稳定提交：
改动范围：
数据结构变化：无 / 有（说明迁移与回滚）
环境变量变化：无 / 有（仅写变量名，不写值）
备份位置与清单：

验证结果：
- 后端测试：
- 前端测试：
- 生产构建：
- 本机 health/root：
- 公网 health/root：
- 公网与本地资源版本：
- 登录与权限：
- QGIS 真实工作流：
- AI / 语音 / 外部地图：

已知限制：
观察结束时间：
是否回滚：否 / 是（原因和目标版本）
```

## 11. 最简操作速查

```powershell
# 巡检
.\deploy\public-windows\Test-PublicWebGIS.ps1

# 维护窗口：停止、备份、启动、复检
.\deploy\public-windows\Stop-PublicWebGIS.ps1
.\deploy\public-windows\Backup-PublicWebGISData.ps1
.\deploy\public-windows\Start-PublicWebGIS.ps1
.\deploy\public-windows\Test-PublicWebGIS.ps1
```

以后向 Codex、Claude Code 或其他开发代理提出“更新公网网站”时，应要求其按本规范给出：发布 SHA、改动文件、测试精确结果、备份位置、分层验收结果、未验证项、回滚目标，并确认未修改无关工作区内容。
