# 地理图片生成 API

管理员登录后可直接生成，不需要提交 `confirmed`，也不出现助教生图确认卡。普通教师仍需明确确认本次付费调用，且只能操作有权访问的项目。管理员身份由服务端会话确定，传入 `role`、`actor_role` 或地图上下文不能改变权限。该规则仅适用于生图，其他高风险课堂操作仍按原规则确认。

网页入口：展开智能助教 → 教学助手 → 图片生成。结果保存到当前项目数据库的「图片」分类，并成为助教待发送附件。生成素材仍需核对文字、箭头和地理关系。

## 认证与接口

先 `POST /auth/login`，JSON 为 `email` 和 `password`。保存返回的登录 Cookie 和 `csrf_token`。后续写请求同时携带 Cookie 与 `X-WebGIS-CSRF`；查询和下载同样需要登录。不要把 MiniMax 密钥发送给前端或第三方客户端。

| 接口 | 用途 |
| --- | --- |
| `GET /image-generation/capabilities` | 查看是否配置、默认模型、模型对应比例、1500 字符限制以及当前账号是否需要确认 |
| `POST /image-generation/jobs` | 推荐：校验后返回 HTTP 202 与任务编号，后台生成 |
| `GET /jobs/{job_id}` | 查询 `queued/running/completed/failed`；成功图片在 `result.artifact`，失败原因在 `error` |
| `GET /outputs?project_id=...` | 查询已入库图片；筛选 `artifact_type=generated_image` |
| `GET /files/...` | 使用 `artifact.metadata.public_url` 下载已保存图片 |
| `POST /image-generation` | 兼容旧同步接口，等待上游生成后直接返回 `artifact` |

异步请求示例（管理员可省略 `confirmed`）：

```json
{
  "project_id": "你的项目编号",
  "title": "喀斯特地貌教学素材",
  "prompt": "高中地理教学配图，喀斯特峰林与蜿蜒河流，远处石灰岩峰丛，近处平地和植被。自然写实风格，无文字、数字和箭头。",
  "model": "image-01",
  "aspect_ratio": "16:9",
  "prompt_optimizer": true
}
```

每次请求生成一张。普通教师需增加 `"confirmed": true`。提示词优化可以关闭，复杂结构仍须人工核验。请求参数沿用 [MiniMax 官方文生图 API](https://platform.minimax.io/docs/api-reference/image-generation-t2i)，服务端取得 base64 图片后持久保存，不依赖上游临时下载链接。

响应示例：`{"status":"accepted","job_id":"...","project_id":"...","status_url":"/jobs/..."}`。

401 表示未登录；403 表示会话/CSRF 校验失败；404 表示对象不存在或无权限；409 表示普通账号尚未确认付费；400 表示提示词、模型或比例无效；503 表示异步服务未配置。HTTP 202 仅代表已接收，不能据此宣称图片已生成。上游失败会记录为任务 `failed`，不登记图片。没有自动付费重试；连接断开后续查原任务，避免重复生成。任务在当前服务进程内执行，服务重启后的中断任务不会自动重发上游调用。

## 可运行的 Python 客户端

仓库的 `scripts/image_generation_client.py` 使用 Python 标准库，支持登录、提交、续查、下载及 SHA256 清单。将提示词保存为 UTF-8 文件，然后运行：

```powershell
python scripts/image_generation_client.py --email admin@example.com --project-id 你的项目编号 --prompt-file prompt.txt --output-dir scratch/image-results
```

密码会交互输入，不进入命令行参数或结果清单。自动化环境可通过进程环境变量 `WEBGIS_IMAGE_EMAIL`、`WEBGIS_IMAGE_PASSWORD` 提供凭据。管理员不用 `--confirmed`；普通教师显式增加该选项。中断后用返回的任务编号续查：

```powershell
python scripts/image_generation_client.py --email admin@example.com --resume-job 任务编号 --output-dir scratch/image-results
```

后端继续使用已配置的 `WEBGIS_AI_MINIMAX_API_KEY`；图片服务地址和默认模型对应 `WEBGIS_AI_MINIMAX_IMAGE_BASE_URL`、`WEBGIS_AI_MINIMAX_IMAGE_MODEL`。管理员免确认不会免除服务商实际用量费用。
