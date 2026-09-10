# `webgisai.com` 低成本公网发布

本目录用于把 Windows 教师机上的完整 WebGIS-AI 通过一个 HTTPS 域名发布到公网。后端、SQLite/JSON 状态、上传文件、离线语音模型和 QGIS 仍留在本机；Cloudflare Tunnel 只建立出站连接，不开放路由器端口。

## 架构与费用

```text
访客浏览器
  -> https://webgisai.com（Cloudflare HTTPS）
  -> Cloudflare Tunnel（免费计划）
  -> 127.0.0.1:18080（Caddy，同源静态文件和反向代理）
       -> frontend/dist
       -> 127.0.0.1:18999（FastAPI、SSE、WebSocket、文件）
```

日常基础设施费用为域名续费。电脑关机、休眠、断网或本机服务停止时，公网链接不可用。MiniMax、高德和天气等外部 API 仍按各自规则计费。

不要用随机 `trycloudflare.com` Quick Tunnel 作为正式入口：Quick Tunnel 不支持 SSE，而本项目的任务和 GIS 工作流依赖 SSE。

## 一次性准备

1. 确认腾讯云中的 `webgisai.com` 已完成注册和实名认证。
2. 注册或登录 Cloudflare，选择 Free 计划并添加 `webgisai.com`。
3. Cloudflare 会给出两条权威 DNS 服务器。在腾讯云域名控制台把 `webgisai.com` 的 DNS 服务器改为这两条；等待 Cloudflare 状态变为 Active。
4. 安装 Caddy 和 `cloudflared`。只从 Caddy、Cloudflare 官方下载页或 Windows Package Manager 安装。
5. 保留现有 `backend/data`，并备份其中的 `auth`、`state`、`uploads`、`outputs` 和 `workflows`。不要把这些目录提交到 Git。

## 首次安全启动

先不要安装 Tunnel 的 Windows 服务。进入仓库根目录后运行：

```powershell
.\deploy\public-windows\Start-PublicWebGIS.ps1 -InstallFrontendDependencies
```

脚本会执行生产构建，以 `https://webgisai.com` 作为前端 API 地址，随后只在本机回环地址启动 FastAPI 和 Caddy。若用户库为空，脚本会在公网入口开放前要求创建首位管理员。

本机检查：

```text
http://127.0.0.1:18080
```

确认能登录、地图能打开、助教能返回结果、GIS 工作流能产生产物、语音输入可建立连接后，再创建正式 Tunnel。

## 创建正式 Cloudflare Tunnel

在 Cloudflare 控制台进入 **Networking -> Tunnels**：

1. 新建 Cloudflared Tunnel，名称使用 `webgisai`。
2. 添加 Public hostname：
   - Hostname：`webgisai.com`
   - Service type：`HTTP`
   - URL：`localhost:18080`
3. 如需 `www.webgisai.com`，再添加一条指向同一服务的 Public hostname；正式对外仍统一分享 `https://webgisai.com`。
4. 控制台会生成 Windows 服务安装命令。该命令包含私密 Tunnel token，只在本机管理员终端执行，不要粘贴到聊天、Git、截图或文档中。

安装服务后访问：

```text
https://webgisai.com
```

## 日常操作

启动源站：

```powershell
.\deploy\public-windows\Start-PublicWebGIS.ps1
```

停止源站：

```powershell
.\deploy\public-windows\Stop-PublicWebGIS.ps1
```

运行日志位于 `backend/data/public-runtime/`，该目录属于本地运行状态，不应提交。

## 上线前验收

- `https://webgisai.com/health` 返回成功，且不泄露 API Key。
- 未登录访问业务 API 返回 `401`，登录后 Cookie 带 `Secure` 和 `HttpOnly`。
- 前端、普通 API、SSE、WebSocket 和产物下载均通过同一 HTTPS 域名工作。
- QGIS 状态正确，至少运行一次真实工作流并打开产物。
- 新建一个非管理员教师账号，确认项目和文件不能跨账号读取。
- 关闭本机服务后公网入口不可用；重新启动后数据仍存在。
- 备份 `backend/data`，并确认恢复流程可用。

## 边界

这套方案适合答辩、演示和小规模试用，不提供云服务器 SLA。它不把本机单进程、文件型状态存储改造成高并发 SaaS，也不自动证明外部 AI、第三方地图、真实麦克风或不同网络下的浏览器兼容性。
