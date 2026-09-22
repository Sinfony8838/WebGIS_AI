# 地理图片生成实测（2026-09-21 至 2026-09-22）

本轮使用项目配置的 MiniMax 正式图片 API，真实生成 5 张原图；没有以其他生图工具替代，也没有修改模型返回的图片。全部调用成功，但只有第 5 张达到本轮「无文字、写实地貌教学插图」目标。3 张机制图不宜直接作为知识图解，第 3 张仅适合背景插画。本次是小样本人工核验，不能据此推出模型的总体成功率。

## 结果与人工核验

| 编号 / 原图文件 | 模型 | 提示词优化 | 用时 | 原图尺寸 | 核验结果 |
| --- | --- | --- | --- | --- | --- |
| 1 `water-cycle.jpg` | image-01 | 关闭 | 25.59 秒 | 1280×720 | 未通过。按中文提示生成了错误/伪英文标签，部分箭头无法表达蒸发方向，未形成完整水循环。 |
| 2 `sea-land-breeze.jpg` | image-01 | 关闭 | 29.77 秒 | 1280×720 | 未通过。文字错误、双向箭头含混，昼夜海陆风循环无法可靠区分。 |
| 3 `karst-landscape.jpg` | image-01-live | 开启 | 24.39 秒 | 1456×816 | 部分符合。山水插画美观，但山体偏棱角和幻想风格，未达到提示要求的自然写实地貌效果。 |
| 4 `water-cycle-optimized.jpg` | image-01 | 开启 | 72.78 秒 | 1280×720 | 未通过。景观更完整，但中文标签不可读、缺少地下径流等关键路径；优化器未解决科学图解错误。 |
| 5 `karst-photorealistic.jpg` | image-01 | 开启 | 28.54 秒 | 1280×720 | 达到插图目标。可辨峰林/峰丛、谷地农田及蜿蜒河流，无伪文字。可在教师复核后作为 AI 地貌示意素材，不可称为具体地点的实景照片。 |

编号 1–2 直接调用项目现有的图片客户端；编号 3–4 通过新增异步 HTTP API，使用真实登录 Cookie 与 CSRF，管理员请求未传 `confirmed`。两次提交均在约 0.016 秒返回 202，再通过任务状态取得已保存图片。编号 5 从网页管理员「直接生成并存入数据库」按钮发起，无确认卡，结果进入项目图片库并成为助教待发送附件。Python 示例客户端还完成了重新登录、续查编号 5 的任务及下载，下载哈希与原图一致，没有再次提交付费请求。

用时为单次调用至完成或任务创建至完成的观测值，不是并发或性能基准。浏览器与 HTTP 权限测试使用隔离测试数据库，未写入生产课堂数据。

## 可复用提示词

编号 5 使用以下提示词，可作为无文字地理景观素材的起点。它在本轮比中文写实提示效果更好，但两次模型和提示词均不同，不能据此归因于语言。

```text
Photorealistic geography teaching illustration of a humid subtropical limestone karst landscape. Distinct steep rounded limestone tower hills and forested cone-shaped hills rise from a broad flat alluvial valley. A naturally winding river crosses the valley, with small patches of agricultural fields beside the river. Daylight, realistic green vegetation and gray limestone, wide horizontal field of view, natural proportions, documentary photography style. No text, no letters, no numbers, no arrows, no map borders, no fantasy mountains. Illustrative synthesized landscape, not a photograph of a named real place.
```

机制图核对依据包括 [USGS 水循环图解](https://www.usgs.gov/water-science-school/science/water-cycle-diagrams) 和 [NOAA 海陆风说明](https://www.ndbc.noaa.gov/education/seabreeze_ans.shtml)。地貌特征参考 [UNESCO 中国南方喀斯特](https://whc.unesco.org/en/list/1248)。这些资料用于核验地理关系，不构成生成图对应真实地点的证明。API 参数参考 [MiniMax 官方文生图文档](https://platform.minimax.io/docs/api-reference/image-generation-t2i)；本轮两个模型均以实际调用成功为依据。

## 原图溯源

原图、完整提示词和 JSON 结果保存在任务工作区的 `.claude/geography-image-evidence/`，未提交生成图片或运行数据库。原图 SHA256 如下：

| 编号 | SHA256 | 上游 request_id |
| --- | --- | --- |
| 1 | `f2fd9960a6190fd5bc6944b8441aced7e638d8f14aa55ae44afc5cb65d0c54a3` | `07006fea07c8d17162898b23131b9e30` |
| 2 | `9b687d33bc4a38a175a14861d51b05b6fbdcf97e4878292a4f9166ea62998e4b` | `070070076401a571aa9532dca66e5036` |
| 3 | `7eee3767e130b6eb53df9e5b1c28e5dff87ca4edd8e404683f56324672d7f5c7` | `0700f9795b29c7194687456f263bc617` |
| 4 | `38c6e1c834e7eee98564de0b772ce0ff147d44234537d0953da6cea930dc6623` | `0700f99448bf5f4a6e589c5cfa4ec04d` |
| 5 | `f025fe13085f6bcda47278a737c86a0a5c6aa0f839c1dfa4b5d1c16e0ea59635` | `0700fb0e22f27a637caa5c1a0bbc5e69` |

## 交付行为

- 管理员网页、助教生图工具、同步和异步 API 均可直接使用；身份来自服务端会话。普通教师须确认费用，项目隔离、CSRF 与其他高风险操作确认仍生效。
- 异步接口返回任务编号；生成成功才登记图片。查询中断显示原任务编号，不自动重复付费调用。
- 助教生图结束后显示实际生成结果，不再由知识回答覆写成等待确认，也不描述未识别过的生成画面。
- 所有生成素材记录 `teaching_review: required`；产品提示核对文字、箭头和地理关系。本轮没有把不合格机制图处理成可用图，也未新增另一种绘图引擎。

使用方式见 [地理图片生成 API](../image-generation-api.md)。

## 自动化验证

- 后端全量：`python -m pytest backend/tests -q` → **949 passed, 6 skipped, 156 subtests passed**。
- 前端全量：`npm test` → **60 files, 441 tests passed**；正式域名配置的 `npm run build` 成功。
- 新增 API 测试覆盖实际登录/CSRF、管理员免确认、普通教师确认、伪造角色无效、跨项目拒绝、异步返回/下载、错误参数和失败不入库。
- 浏览器实测和 Python 客户端下载使用真实 MiniMax 结果；单元测试上游使用桩，不把测试桩结果计为生成效果。
