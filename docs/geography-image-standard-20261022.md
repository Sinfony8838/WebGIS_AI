# 地理教学图片生成与读图制图规范

版本：geography-image-v1（2026-10-22）。适用：Chat 图片生成及共享图片生成接口。教案设计入口不变。

## 用途与准入

- 概念示意、教学插画：允许生成，但必须保留核心地理关系，注明 AI 生成概念示意。
- 真实地图、统计图、行政边界、精确测量：使用 GIS 与来源明确的数据。绘画模型不能编造坐标、比例尺、统计分级或年份。
- 有理论错误的要求先指出问题；不能静默改写成另一个目标后声称完成。
- 输入原图与新生成图分开记录。不能凭画风推断原图作者、版权或是否由 AI 生成。

## 学术核对清单

| 维度 | 要求 |
| --- | --- |
| 空间关系 | 海陆、上下游、坡向、相邻/包含关系一致；真实地点必须有可靠数据支持 |
| 地理过程 | 自然地表径流沿坡降；蒸发到大气、降水到地表；凝结须有相应条件，不能画成任意因果 |
| 条件与例外 | 海拔不等于坡度；背风坡不是永不降水；区域规律不写成无条件绝对命题 |
| 统计概念 | 人口总量与密度、空间差异与时间变化、相关与因果严格区分 |
| 符号与图例 | 箭头始末对应正确过程；颜色与图例一致；文字无乱码；缺失不填零 |
| 数值与来源 | 不虚构年份、数值、真实边界、比例尺、文献或机构标志；未能核验则明确未知 |
| 教学用途 | 自动检查不是学术认证；即使通过，仍需教师检查再用于教学或出版 |

基础规则参考：[USGS 水循环](https://www.usgs.gov/water-science-school/science/water-cycle-diagrams)、[NWS 地形抬升](https://www.weather.gov/wrn/science-sm)。这些链接是规则依据，不是每一张生成图的测量数据来源。

## 执行与保存

1. 生成前核查：无附件使用文本模型；显式参考图重绘使用实际原图的视觉模型，一次请求同时读图、核对目标并形成绘图要求。
2. 结构校验：必须返回允许的图类型、绘图描述与核对项；拒绝、缺项、格式错误均不进入绘画调用。关闭供应商自动提示优化，防止另行改写学术约束。
3. 生成后核查：视觉模型实际读取输出图片，逐项返回证据。漏项、异常、含糊、无法识别均不能视为通过；检查额外错误、数值与标注。
4. 保存：会话内先预览。fail/unknown 暂不允许加入素材库，前后端均校验。pass 仅代表自动检查未发现明显问题，用户仍可选择保存或暂不保存。
5. 成本：读图/目标核对、生成、输出核查共最多 3 次模型请求；错误请求计数，不自动追加重试。视觉供应商未提供 token 用量时记录为未知。
6. 追溯：记录规则版本、用户要求、实际绘图描述、核对项、参考图片 artifact_id 与 SHA256、视觉核查结果和生成时间。运行证据及图片仅留在隔离数据目录，不提交私有素材或凭据。

## 原图编辑能力边界

当前 image-01 的官方参考接口为人物主体参考，没有地理原图局部编辑/结构保真契约；当前项目未接入通用原图编辑模型。参见 [MiniMax 图生图文档](https://platform.minimax.io/docs/api-reference/image-generation-i2i)。

- “在原图上改颜色、加箭头、保持布局”：可以读原图说明，但返回未完成修改，不调用文字生图冒充编辑。
- “根据参考图重新绘制一张概念示意图”：可以读图后按要求重绘；不承诺像素、边界或布局保真。结果明确标记 reference_redraw。
- 后续接入真正的编辑模型须传原始像素与编辑区域，核对未编辑区域、结构和修改项；原图 SHA256 不变不能代替输出图保真检验。

## 实测记录

参考图片来自 [USGS The Water Cycle Diagram (English)](https://www.usgs.gov/media/images/water-cycle-diagram-english)，页面标注 Public Domain。使用其原始下载文件（局部图卡），不裁改，SHA256：`cf80fc45ec78cd150e0f8587466eaddffb275e670d85c4a4bbae91384b1ff143`。

真实验收在隔离服务（5178/8017）执行，文本模型 MiniMax-M3.1-Flash、绘画 image-01、视觉 MiniMax MCP；没有使用测试夹具代替实际图片或模型。

| 实测 | 结果 | 请求 / 耗时 |
| --- | --- | --- |
| 上传原图并要求局部改红色径流箭头、保持布局 | 能读出过程及修改目标；明确未完成原图修改，未调用绘画服务 | 1次 / 22.407秒 |
| 根据参考图重新绘制三过程水循环图 | 真正读图、生成和核查均执行；新图径流逆坡、中文乱码，核查 fail，回合 partial | 3次 / 56.953秒 |
| 无外力河流自然流向山顶并作为正确理论 | 生成前拒绝，未调用绘画 | 1次 / 13.266秒 |
| 无数据生成精确2026年省级人口密度地图 | 生成前拒绝，要求GIS与可靠统计数据，未调用绘画 | 1次 / 8.484秒 |
| 绕过禁用按钮直接调用失败图片保存接口 | HTTP 409，未加入素材库 | 0次模型请求 |

参考重绘结果：`artifact_c84a058036ba45b59738839e41406d8e`，输出 SHA256 `54dfaf8231a7ee2e89610bdf7f59082c89203d1c1c7afd5b28de7acb63e42574`。原图测试后 SHA256 不变。

验收结论：读图→文字约束→重绘→质量拦截链路可运行；**没有产出通过本轮学术验收的图，原图局部编辑未实现**。不将拦截成功写成制图成功。视觉核查也存在局部误判（曾把仅有“AI生成”的水印视为完整概念示意标注），已增加逐字标签字段与代码复核；仍不能代替教师审阅。

运行证据：`data/qa/geo-original-edit-recheck.json`、`geo-reference-redraw.json`、`geo-reference-redraw-child.json`、`geo-wrong-theory-v2.json`、`geo-real-map-v2.json`、`geo-rejected-save.json`。视觉 token 未提供，因此总 token 为未知。

先前读图把输入原图误称 AI 生成、附件解析漏导入、文本模型仅含 system 消息三项失败均已保留并修复，不能计为成功。

最终视觉复查（独立验收请求，不是原回合自动重试）：对同一输出图再调用一次真实视觉模型，用时14.500秒，仍判定fail，读出了不完整AI水印并被代码校验为unknown；但这次对逆坡箭头出现漏判。因此不能将自动审核宣传为“保证地理正确”，尤其不得用单次VLM判断替代教材审校。建议下一阶段让箭头、坐标、图例、统计值与文字由可验证的SVG/GIS绘图层输出，生成模型仅提供背景或风格；真正原图编辑需另接具有该能力的供应商。

## 交接范围

分支 `codex/assistant-chat-operate`，本轮起点 `a33a2fc9a5caeb1ac762b1db30825d0eda3f97d4`。复用现有PR #91及其PR #87前置依赖。修改仅在独立工作树；没有修改主目录的未提交文件、生产数据或其他任务工作树。

修改路径：

- `backend/app/main.py`
- `backend/app/runtime.py`
- `backend/app/services/chat_assistant.py`
- `backend/app/services/geography_image_policy.py`
- `backend/app/services/minimax_mcp_client.py`
- `backend/app/store.py`
- `backend/tests/test_assistant_profiles.py`
- `backend/tests/test_geography_image_policy.py`
- `backend/tests/test_image_generation.py`
- `backend/tests/test_image_generation_api.py`
- `docs/assistant-chat-operate-20261022.md`
- `docs/geography-image-standard-20261022.md`
- `frontend/src/__tests__/AssistantImage.test.tsx`
- `frontend/src/components/AssistantImage.tsx`


## 自动化与启动验证

- Python 3.12 `-m pytest backend/tests -q`：1517 passed、9 skipped、195 subtests passed，499.30秒。视觉重复定义清理后另跑规范/视觉客户端17项通过。
- `npm test`：103文件、783项通过；`npm run build`：通过（既有bundle体积警告）。
- `git diff --check`、`git diff --cached --check`：通过。
- 隔离服务 `/health`：HTTP 200；`/image-generation/capabilities`：明确 image_editing=false、reference_redraw=true。
- 3D UI、课堂/报告、TOP20相关回归包含在完整测试；本轮真实浏览器专门验证上传、原图修改请求、参考重绘、图片显示、错误提示与禁用保存。
- 真实模型、本地浏览器、自动化夹具的证据分别记录；本轮没有真人麦克风测试、生产部署或main合并。
