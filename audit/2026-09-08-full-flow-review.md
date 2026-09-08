# GeoBot 全流程实测与可视化修复记录

2026-09-08。此记录区分已修改、浏览器实际运行与未解决问题；不是教学效果评价。

## 任务与环境

- 分支：`codex/full-flow-audit-0908`；起点：`00bb92007099d4dfd6d8dcdac0d09830d0579296`（任务开始时的 origin/main）。
- 专属 worktree：`C:/Users/zcyxn/Desktop/WebGIS-AI-worktrees/codex-full-flow-audit-0908`。
- 允许范围：本任务的登录、助教等待状态、数据库、地图工具、人口专题表达、三维数据入口及对应测试、审查记录。共享 App.tsx 由本任务单独修改。
- 禁止范围：主工作区、其他 worktree、运行时数据和用户题库源文件、密钥、依赖目录、构建产物。未操作其他代理的工作区修改。
- 原主工作区 `codex/review0908` 的 `.zcode/`、`scratch/` 均未修改。未合并 main。
- 隔离测试：前端 `http://127.0.0.1:5188`，后端 `127.0.0.1:19008`，新建管理员 `audit0908@geobot.local`。
- 用户课堂：`http://localhost:5173` 使用本任务前端，仍连接原有 `18999` 后端。因此前端修复可见，但新后端模板逻辑需完成集成后使用。原 `127.0.0.1:5173` 还是另一份旧前端，不能混用验收。
- 验收要求：前端测试与构建、后端测试、diff 检查、3D 地球/课堂/Top20/健康接口保留、浏览器实际操作。语音、真实学生作答、第三方付费实景数据成功加载不在已验证范围。

## 已完成的修改

1. 登录改为地图与教学流程介绍配合紧凑表单，验证桌面、移动端、深浅色。图标白边来自旧前端；最新分支已有正确裁切。
2. 助教与教案共创等待时显示动效、真实阶段文案与已等待时间，不虚构百分比或模型内部思维。
3. 题目移除按钮改为小号单行危险操作；地图状态条删除没有数据的“海拔”。
4. 地图工具与可视化面板统一收起/展开，位置在右侧垂直居中；图层管理移入地图工具。顶部操作靠左，POI 检索和统计靠右。
5. 白色工具背景使用半透明颜色；文字保持不透明，去掉工具背景滤镜和导致分数像素合成的整体位移。
6. 数据库改为左侧分类、紧凑搜索/操作栏、固定大小关闭图标与资源列表。地图按气温、降水、人口等细分；教学资料按知识、视频、图片、文档、链接等细分；区分本地筛选和查找新资料。桌面/移动/深色实测。
7. 人口分布面图改为真实密度字段固定分级（10、100、400、800 人/km²），青绿色连续色阶，灰色表示缺失。原版用人口总量着色却讲“东密西疏”，含义错误。
8. 省级点符号放在省域内部，半径按平方根缩放并注明 4–24 px 截断；取消把所有点固定为 10 px 的全局覆盖。只抽稀相撞文字，不让统计点随标签消失。
9. Top20 改为蓝色顺序色阶，与青绿色密度图分开；柱状结果与地图颜色对应。注明行政区常住人口总量不等于城区密度。
10. 常驻地图图例显示单位、年份、缺失数据、三维高度含义及胡焕庸线依据；收起工具后仍可阅读。三维标签取消远距离缩小，使用白底深色字；移除胡焕庸线夸张墙体，调整教学场景构图和提示框边界。
11. 上海“城市空间与人口”入口提供陆家嘴、中心城区、松江新城三个观察视角及探究提示。新增有来源署名的 3D Tiles 会话接入，区别实景网格和建筑模型；可移除，过期异步结果不会覆盖当前数据源。

## 胡焕庸线的依据与限制

经典线使用黑河、腾冲的参考坐标（约 127.5°E/50.2°N 与 98.5°E/25.0°N），是人口地理概括，不是精密测绘边界。1935 年约 36% 国土/96% 人口与后来国土范围、统计口径下的比例不能混用。

原橙线是算法预设东南侧 94% 人口目标，按 2020 年地级行政单元人口和中心点，在经纬度平面内平行移动经典线选出的结果。它把跨线行政区整体归到中心点所在一侧，没有人口栅格切分或误差区间。因此不能据此宣称胡焕庸线发生真实移动。现默认关闭该线，需在“查看依据与算法”中主动显示，标为“教学拟合线”。算法本身未被包装成新的地理发现。

参考：[《地理学报》胡焕庸线两侧的人口分布与变化](https://www.geog.com.cn/CN/abstract/article/0375-5444/37311)。

## 上海实景三维的实际状态

浏览器已验证：上海近距离定位、不会自动退回二维、明确未配置提示、无效数据地址的失败提示、移除与退出恢复。当前没有已验证可用的上海实景数据源，未验证真实上海纹理瓦片加载成功，不能把底图倾斜显示或普通建筑模型称为实景三维。

可以通过授权的上海倾斜摄影/实景网格 3D Tiles 接入。Google Photorealistic 3D Tiles 是真实纹理网格，但需要 API 密钥和计费配置，上海覆盖尚未验证。本次未开通计费或申请账号。应保留数据提供方署名，并检查空间配准（系统现有高德底图与外部 WGS84 数据可能存在坐标偏移）。

参考：[Google 官方 3D Tiles 文档](https://developers.google.com/maps/documentation/tile/3d-tiles)、[Cesium3DTileset 生命周期与加载事件](https://cesium.com/learn/cesiumjs/ref-doc/Cesium3DTileset.html)。

教学设计应分别观察建筑形态、城市功能、交通与人口统计，避免“楼高就是人多”的推断。省级平均值不能解释上海街区差异；需同年份区级、街道或栅格人口及用地数据配合。

## 浏览器实测与未解决问题

| 优先级 | 问题与复现 | 影响与建议 |
|---|---|---|
| P1 | 最新测试草稿已生成五个环节且覆盖目标 1–4，但模型改写原题并产生人口比较事实错误 | 格式与活动覆盖问题已有网页恢复证据；内容准确性和原题保留仍未通过，不可视为可上课教案 |
| P1 | 教师明确 5 个环节、5/8/15/8/4 分钟，规则回退实际生成 3 个泛化环节；模型失败时没有清楚标识回退 | 不应把模板回退当成遵循教师要求的模型结果，保留具体时长和上海迁移环节 |
| P1 | 助手称“全部 9 步完成、数据来源均引用题库检索”，实际发布失败且当时没有完成对应检索 | 最终话术须以操作结果和真实引用为准 |
| P1 | 同一教师从新 origin 登录后题库为 0；原题库仍在另一项目下，新页面自动创建同名空项目 | 增加所属项目选择/恢复。原 94 题未丢失；不能让用户重复导入来掩盖项目选错 |
| P1 | 同一 host 多标签页 `/auth/me` 轮换 CSRF，旧页请求可能 403；界面显示后端不可达 | CSRF 更新机制与错误分类需要修复。localhost 与 127.0.0.1 分开后可隔离测试 |
| P1 | 点击“提前查看答案”会等待同步 AI 解析；期间官方答案与按钮一同被阻塞 | 先返回官方答案，AI 讲解异步补充。实测规则讲解有标识，但等待体验差 |
| P1 | 上海环节“抽取区县并生成推演”抽到崇明后，助教实际执行省级人口密度模板和全国视角，再输出区县推演 | 工具计划与城市尺度不匹配；缺数据时应保留上海视野并说明局限。此次已实测，未修复 |
| P1 | 上海证据步骤直接显示 `shanghai_population_density` 等内部 ID；点击上海步骤后未看到区县材料或视野变化 | 核对教学地图注册表与目录 ID 映射、文件可用性；缺资源必须显式反馈 |
| P1 | 地图标注落点和文字已保存，但助教额外切换人口模板、尝试不存在的教学地图后报错；界面先显示“标注已添加” | 本地标注应直接落图，不应触发无关地图计划；应区分局部成功与后续失败 |
| P2 | 新建第二次课堂时曾显示上一课堂的旧环节计时，进入首环节后才重置 | 开始新会话应重置 stageEnteredAt 和计时状态 |
| P2 | 截图导出不含图例/年份/来源；长标注遮挡地图 | 导出时合成证据图例，标注限制宽度 |
| P2 | 无题库时题目匹配卡提前返回，提示可手动录题但缺直接入口 | 保留手动建题表单 |
| P2 | 预演对话返回问题，预演卡报告为空/旧版的可能性 | 需补充 revision 切换和返回值同步检查，暂列待复核 |
| P2 | 开始上课后为 -/8、计时 0，需再次选择环节 | 明确“课堂已建立/环节未开始”，或自动进入第一个环节 |
| P2 | 跳到第 6 环节时，未执行的前面环节也显示勾号，源码按 index < currentStageIndex 判断 | 应按实际执行记录显示访问/完成状态，不应把位置当完成证据 |

题库配对 DOCX 导入已实测：94 题、答案覆盖 100%、40 张图。隔离课堂验证了密度图、Top20（重庆 3205 万、上海 2487 万等 20 项）、上海定位、助教调用、教师即兴提问。第二次隔离课堂已完成框选、图片入库和报告记录：生成 830×640 图片，报告正确计数为 1。实际图片包含地图与工具标注，但缺少 HTML 图例、指标年份和来源；尚不满足完整教学证据图要求。数据库图片“查看”原先被数据库与课堂面板覆盖；后续已改为原生模态预览，浏览器验证图片可见、背景不可误点，Esc 只关闭预览并保留图片分类。题库检索原被目标 schema 阻塞，追加修复后已在网页返回 5 个候选。

未采集任何真实学生作答，没有输入虚构答对/部分/误区记录；不能据本次操作评价学习效果或正确率。正式课时为 40 分钟，本次是跳转检查，并非完成一堂真实教学。

## 课后报告补充实测

隔离课堂已结束；报告实际生成，显示课堂时长 11.7 分钟、课堂作答“未采集”、系统提问 1、教师速记 0、截图 0。环节计时保留重复进入上海环节的两条记录。

发现并修复 P1：规则诊断在无学生作答、无教师观察的情况下仍给出“课堂节奏与理解情况总体正常”。已改为证据不足、先收集作答再调整安排；“未记录误区”也明确不代表没有误区。增加空证据和有教师误区记录的回归测试。修复后已重启隔离服务并在浏览器重新生成报告，确认不再出现“理解情况总体正常”。

另发现并修复：已结束课堂后点击底部“课堂模式”会重新打开旧课中面板并继续显示计时。现只允许 running 会话进入课中，ended 会话返回备课入口；补充结束后再打开的回归断言。

练习卷导出实际生成学生卷/教师卷链接，但选题为 0，且提示“未导入题库”；本项目实际已有 94 题。该路径尚需区分“已导入但未绑定”“无课堂误区题”和“无题库”，并明确选题策略，不能算有效练习卷验收通过。

补充工具实测：测距生成 1140.41 km 的线段与结果；标注文字已落图，但出现上述无关工具调用。第二次隔离课堂结束后生成报告，时长 11.8 分钟、课堂截图 1、作答未采集、提问与观察均 0。超时建议要求先核对演示等待，没有把本次操作视为正常教学节奏。

## 检查结果

- 前端 `npm test`：44 文件，251 测试通过（15.15 秒）。
- 后端 Python 3.12 `-m pytest backend/tests -q`：465 测试、9 个子测试通过（47.71 秒）。
- 最终前端生产构建通过（315 模块，Vite 4.37 秒）；3D 地球、课堂、Top20 与 `/health`（success）仍存在并运行。
- `git diff --check` 通过。
- 最终颜色与点标签定向前端 7 测试、后端 14 测试通过；结束课堂回归 3 测试通过（3.05 秒），报告证据保护 2 测试通过；不把构建通过当作外部实景服务可用。

## 截图证据

本机证据目录：`C:/Users/zcyxn/.codex/visualizations/2026/09/08/01a07fe5-6863-7a50-bf6c-de29fd629682/`。

- `01-object-object.png`：教案结构错误；`17-design-publish-blocked.png`：发布失败。
- `06-login-dark.png` / `07-login-light-desktop.png` / `08-login-mobile.png`：登录。
- `12-database-redesigned-desktop.png` / `13-database-mobile.png` / `14-database-dark.png`：数据库。
- `15-crisp-translucent-toolbar.png`：工具背景与文字；`16-question-revealed.png`：官方答案。
- `18-shanghai-study-unconfigured.png`：上海观察与未接入状态。
- `19-density-line-readable.png`：新版密度色阶、标签与常驻图例。
- `20-population-columns-centered.png`：新版三维柱体构图。
- `21-density-symbols.png`：密度点图初次验收，随后进一步修正标签抽稀导致点消失的问题。
- `22-shanghai-ai-wrong-scale.png`：区县推演错误切到全国尺度。
- `23-report-unsupported-normal-claim.png`：无学情证据却判定理解正常，随后修复。

- `24-report-evidence-protected.png`：修复后无证据报告。
- `25-annotation-unrelated-tool-failure.png`：标注局部成功，但出现无关地图调用错误。
- `26-snapshot-preview.png`：图片预览被数据库覆盖。
- `27-report-with-snapshot.png`：第二次课堂截图计数为 1。

## 集成交接

所有修改均在专属任务 worktree 内；没有修改无关工作区文件。变更范围和检查见本记录及分支 diff。依赖现有 Cesium/OpenLayers，不新增付费服务或密钥。提交不包含运行时、题库 DOCX、截图、依赖或构建输出。已存在课堂快照不会被批量改写；新的默认镜头需要新建课堂或重新备课后验证。

### 精确变更路径

```text
audit/2026-09-08-full-flow-review.md
backend/app/data/builtin/lessons/population_distribution_lesson.json
backend/app/geo.py
backend/app/services/population_lesson_prep.py
backend/app/services/reports.py
backend/app/services/templates.py
backend/app/services/visual_query.py
backend/tests/test_report_evidence.py
backend/tests/test_templates.py
frontend/src/App.tsx
frontend/src/__tests__/DatabaseViewer.test.tsx
frontend/src/__tests__/LessonSceneOrchestration.test.tsx
frontend/src/__tests__/MapToolsDock.test.tsx
frontend/src/__tests__/ThinkingIndicator.test.tsx
frontend/src/__tests__/UrbanStudyPanel.test.tsx
frontend/src/__tests__/populationVisual.test.ts
frontend/src/auth.css
frontend/src/components/AuthGate.tsx
frontend/src/components/CopilotWidget.tsx
frontend/src/components/DatabaseViewer.css
frontend/src/components/DatabaseViewer.tsx
frontend/src/components/LessonDesignWorkspace.tsx
frontend/src/components/LessonWorkflowShell.tsx
frontend/src/components/Map3DGlobe.tsx
frontend/src/components/MapEvidenceLegend.css
frontend/src/components/MapEvidenceLegend.tsx
frontend/src/components/MapStatusBar.tsx
frontend/src/components/MapToolRail.tsx
frontend/src/components/MapToolsDock.css
frontend/src/components/MapToolsDock.tsx
frontend/src/components/ThinkingIndicator.css
frontend/src/components/ThinkingIndicator.tsx
frontend/src/components/UrbanStudyPanel.css
frontend/src/components/UrbanStudyPanel.tsx
frontend/src/components/VisualQueryPopup.tsx
frontend/src/lesson-workflow.css
frontend/src/lib/globeThemes.ts
frontend/src/lib/populationVisual.ts
frontend/src/main.tsx
frontend/src/styles.css
```

## 追加修复：资料预览被遮挡

起点提交 `744023acc3333d95907afcb0bf8bdfd886563745`，仍在同一专属分支。范围仅 TeachingMaterialViewer.tsx、styles.css、对应测试与本审查记录；未改主工作区、运行时文件或其他任务。依赖浏览器原生 dialog（当前验收 Chromium 支持），无新增包。

根因为预览 z-index 31，低于数据库 34 与课堂面板 62。改为原生模态顶层后，数据库及地图背景进入不可交互状态，关闭操作有可访问名称，并恢复入口焦点；按 Esc 不再传播给底层数据库关闭监听。浏览器已验证截图显示、Esc 返回原图片分类。证据：`28-snapshot-preview-fixed.png`。

定向回归：TeachingMaterialViewer 与 DatabaseViewer 共 13 测试通过（2.97 秒）；浏览器原生模态与层级通过实际截图验收，不用 jsdom 替身证明视觉效果。

追加修复完整检查：前端 44 文件、252 测试通过（15.32 秒）；生产构建 315 模块通过（4.33 秒）；`git diff --check` 通过。此次未改后端，保留上一提交后端 465 测试及 9 子测试的验证范围。

## 追加修复：教学目标与问题链格式

起点 `efb1aa2d1b0f3d0c342461b35f0b4d0a1198dbd9`，分支仍为 `codex/full-flow-audit-0908`。允许范围为 `backend/app/services/lesson_design.py`、`backend/tests/test_lesson_design.py` 与本记录，依赖现有草稿字段约定，无新增包；未修改无关文件或主工作区。

根因有两处：模型返回 `{statement, id, ...}` 对象，页面与题库请求却要求字符串；`objectives`/`core_questions` 同时用作步骤与章节 ID，直接编辑章节时被错误要求步骤包装对象。

现对已知富文本条目提取 statement/text/question/description，保留条目顺序与原始附加信息（structured_text_originals，归档用途）。create/resume/get 在副本上补齐规范字段，不因读取改写原草稿或 revision；下一次合法保存持久化规范结果。新模型输出在合并前检查条目文字；无效编辑不会污染存储中的草稿。兼容章节本身与步骤包装两种编辑载荷，不放宽课时长度和目标覆盖检查。

浏览器原草稿复验：4 条目标与 4 条子问题正常显示；目标与问题链分别直接保存成功。持久化读取确认仍为 4 条字符串目标、4 条子问题，原对象附加信息保留。检索“人口密度”返回 5 道真实题库题，不再报 422。截图：`29-objectives-readable-saved.png`、`30-question-search-recovered.png`、`31-core-questions-readable-saved.png`。

边界：点击“选用”被自动审批拒绝，理由是这份测试草稿此前要求保留三道自拟开放题，新增真实题库绑定需确认；点击“确认发布”也被自动审批拒绝，理由是会持久化课时草稿并可能导出 Word、且预演项未完成。两项均未执行，未绕过拒绝。只读检查确认草稿 active、final_lesson_id 为空，三个环节仍只对应目标 1/2/3。远端推送同样等待授权，未创建 PR。

另观察：检索“人口密度”时，航空产业基地选址题也显示“相关度 100%”。该分数不能当作客观匹配准确率，排序及百分比展示需进一步复核。

检查：教案定向 13 测试通过（1.97 秒）；完整后端 468 测试、9 子测试通过（44.91 秒）；隔离 19008 服务重启后 /health 返回 success，原用户课堂后端未重启；git diff --check 通过。未修改前端，沿用上一提交的前端测试及构建验证范围。


## 浅色底图按钮白角修复

- 原因：浅色主题的面板选择器误包含定位容器 `.basemap-menu`，导致圆角按钮外露出矩形底色。改为真实下拉面板 `.basemap-menu-panel`；按钮外层恢复透明，不使用裁切影响菜单。
- 修改范围：`frontend/src/theme.css` 与本复盘记录；未修改其他工作区。
- 网页验收：浅色模式按钮四角背景正常，底图菜单与基础底图列表可展开且未裁切；截图 `32-basemap-corners-fixed.png` 保存在本地证据目录。
- 检查：`npm test -- --run src/__tests__/BasemapMenu.test.tsx`，1 test passed；`npm run build` 通过，315 modules，Vite 4.80 秒；`git diff --check` 通过。


## 教案生成回退与完成状态保护（持续排查）

- 本轮范围：`backend/app/services/lesson_design.py`、`backend/tests/test_lesson_design.py` 和本记录；依赖现有教案 schema 修复。起始提交 `03cb66b`，分支仍为 `codex/full-flow-audit-0908`。未修改主工作区或无关文件。
- 固定三环节来自 `_fallback_turn`，此前 AI 无有效结果时静默采用。现在规则回复和持久化历史明确披露规则模式；教师用“环节名称 + 数字分钟”明确列出至少两个环节时，核验名称、顺序与时长。不符合要求会返回可读错误，保留原草稿、revision 和输入；不会覆盖成三个通用环节。该解析不代表支持所有自然语言时间表达。
- 教学过程生成增加至 8192 输出 token 上限、90 秒请求时限；其他步骤保持原限额。增加失败分类日志，不记录响应正文或异常详情，避免泄露凭据。
- 预演及确认步骤的回复由本轮合并后的实际校验结果、未确认章节生成；返回的报告与历史回复一致，模型不能直接宣布完成、发布或文件生成。
- 网页实测：在原隔离测试教案按 5/8/15/8/4 分钟重做，两次均未得到可用五环节结果。原三环节未被覆盖，输入保留；第二次服务诊断为 `invalid_payload`，不是超时。**五环节实际生成仍未通过验收**，接下来需进一步定位返回字段结构，不能把保护性拒绝当成功生成。
- 网页“只检查当前草稿”返回：上海人口目标缺少活动，教学目标/核心问题链/GIS能力未确认，尚未发布、尚未生成 Word，并披露规则模式。截图 `33-lesson-readiness-truth.png` 在本地证据目录。原有历史错误话术仍保留作审查证据。
- 检查：最新完整后端 `472 passed, 14 subtests passed in 52.24s`；`git diff --check` 通过；隔离服务 `127.0.0.1:19008` 重启且健康接口 success，原用户 18999 服务未重启。本轮未改前端，未重复运行前端检查。
- 无发布、绑定题库、远端推送或 PR 操作；此前被自动审批拒绝的操作仍待授权。全流程目标继续，未标记完成。


## 五环节生成恢复与教学内容复核

- 本轮起点 `e8291c0`，允许修改教案服务、教案测试和本记录，禁止修改其他工作区、用户源题库和凭据。原工作区未改，独立任务分支不变。
- 继续复现得到 `JSONDecodeError`；上轮还出现过 `invalid_payload`，因此不能将所有失败归因于单一字段。实际草稿为 6369 字符，低于 12000 字符截断上限，排除了本次草稿截断。添加只记录字段类型的校验诊断，不保留模型原始回复。
- 明确 `section_patch` 为章节字典，提供完整教学过程对象示例，要求未变更字段省略而非 null。无效 JSON/格式/明确时长不匹配时最多自动修正一次；网络错误不自动重试。教学过程输出上限改为 12288，其余步骤保持 2400，时限仍为 90/45 秒。
- 真实网页恢复：隔离教案 revision 19，generation_mode=model，五个环节名称与 5/8/15/8/4 分钟正确，四个目标均被活动引用，上海迁移活动存在。本次日志为 HTTP 200，未出现修正重试日志，说明首轮有效；自动修正路径由定向测试覆盖，不能宣称实测已走过修正重试。
- **新增 P1 内容问题**：模型声称保留三道原题，实际把 s1q1/s2q1/s3q1 改写并新增 s4q1/s5q1；还写“山东与西藏总量相近”。内置 2020 年数据分别为山东 101578597、西藏 3648124 人，显然不相近。当前没有事实核对机制，结构检查通过不代表教学内容正确。原题快照与事实约束需继续修复，未发布。
- 上海区级数据确实在仓库中，`shanghai_population_density.geojson` 为 16 区；目录标注 2020 年人口基准表与阿里云边界。source_url 指向边界文件，未独立核验人口统计表来源；不能把有文件等同数据来源完全核实。先前“点击上海步骤未落图”仍是独立待修复问题。
- 完整预演网页返回“结构检查通过”，同时列出未确认章节且未发布、未生成 Word；未识别上述事实错误和原题改写。另复现 P2：主按钮运行后只有右侧对话得到结果，预演卡片本身仍未显示报告；卡片“重新检查”有独立状态与请求路径，后续需统一。
- 最新完整后端：`473 passed, 14 subtests passed in 52.27s`；发现并移除一处行末空格后 `git diff --check` 通过。仅后端变更，沿用前端已验证范围。服务现为隔离 19008，原 18999 未重启。
- 本轮未绑定题库、发布、导出 Word、远端推送或创建 PR。全部流程目标仍未完成，下一步优先解决题目保留、事实依据和预演报告呈现。


## 只读预演卡片与原题保护

- 本轮从 `5cd28a6` 开始，目标是统一预演报告并防止共创改写原题。修改范围：`backend/app/services/classroom_workflow.py`、`backend/app/services/lesson_design.py`、`backend/tests/test_lesson_design.py`、`frontend/src/components/LessonDesignWorkspace.tsx`、`frontend/src/__tests__/LessonDesignWorkspace.test.tsx` 和本记录。未改共享路由/接口类型、主工作区或其他任务的文件。
- 两个预演按钮都读取 `GET /lesson-design/sessions/{id}` 返回的同一版本草稿与报告；后端用同一份读快照校验，不调用模型、不写入新对话或 revision。报告显示在卡片内，AI 对话带回的报告也同步到同一卡片。报告按 design_id/revision 匹配，修改草稿或检查失败后不再显示旧的通过结论，失败有可见提示。
- 网页实测：两个按钮各产生一次 GET 200，卡片显示 40/40 分钟与设计思路字数建议；检查前后均为 revision=20、turns=12、status=active、final_lesson_id 为空。截图 `35-readonly-rehearsal-card.png`。首次进入教案时出现单次初始化请求失败，其他 API 正常，关闭教案再进入恢复；尚未定位该瞬时加载问题，不能声称网络层已经修复。
- 题库题、教师录入题按完整题目对象保护；教师明确要求保留开放题时同样保护。允许移动到其他环节，不允许生成结果改写、删除或重复原题。模型修正提示附原题对象，且保存前再次检查，规则回退也不能绕过。回归测试覆盖改题干、改答案、删除、重复、移动和回退失败；**该保护本轮以测试验证，尚未进行下一次真实模型保留原题的网页复验**。
- 保护不会回溯恢复已经改写的旧题。当前五环节测试草稿中的旧题和“山东与西藏总量相近”错误仍需单独恢复/纠正；结构通过不等同事实与资料来源核验通过。
- 检查：完整后端 `475 passed, 18 subtests passed in 52.39s`；完整前端 44 文件/254 测试通过（17.22 秒）；生产构建通过（315 modules，5.60 秒）；`git diff --check` 通过。19008 隔离服务已加载保护且健康返回 success；原用户 18999 未重启。新预演卡片需要配套后端返回报告，旧后端会显示更新提示，不能将 5173 旧后端视为已验收。
- 本轮没有发布、题库绑定、生成 Word、远端推送或 PR；之前相关授权问题未被再次尝试。全流程目标继续，剩余内容真实性、原题恢复、地图尺度、课堂工具与报告问题见前表。
