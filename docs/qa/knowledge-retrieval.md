# 中文知识库检索质量与来源可追溯 — 评测报告

任务分支：`claude/knowledge-retrieval-quality`（起始 SHA `00bb920`，已合入 `origin/main` `1f416d9`）
评测语料：`scripts/qa/knowledge_retrieval/corpus.json`（内置 16 条 + geo 单元 + 21 条评测专用合成资料描述）
样本集：`scripts/qa/knowledge_retrieval/samples.py` — **119 条中文问句**（调优集 63 / 保留测试集 56）
复现：`python scripts/qa/knowledge_retrieval/run_eval.py --split all`（仓库根目录，Python 3.12）

## 一、真实调用链（逐条核实）

| 调用方 | 路径 | 本次是否覆盖 |
| --- | --- | --- |
| 前端 `searchKb`（App.tsx `loadKnowledgeBase` 等） | `GET /kb/search` → `runtime.kb_search` → `KnowledgeBaseService.search` | ✅ 引擎重写、权限前置、结果缓存键含 owner+清单指纹 |
| 资源检索 `ResourceSearchService._search_kb` / `_search_materials` | 同上 + `get_manifest` | ✅ 间接受益（同一服务） |
| 教案设计 `LessonDesignService` | `knowledge_base.search(query=message, limit=3)` | ✅ 同一服务 |
| 人口资料注册 `PopulationSourceRegistryService` | `get_manifest` | ✅ 缓存加速，行为不变 |
| 数据库界面（DatabaseViewer） | `GET /kb/manifest` + **前端字符串过滤**（DatabaseViewer.tsx `filteredEntries`） | ⚠️ 数据源已受益；排序仍在前端，见集成需求 R1 |
| 助手本地证据（session_engine `KnowledgeEngine`） | 构造时 `build_engine_units()` 一次性加载 + 自有 `_match_entry` | ⚠️ 见集成需求 R2 |
| 讲解兜底 `runtime._compose_knowledge_answer` | `KnowledgeService.search`（内置卡片） | ✅ 同一引擎，弱证据返回空卡回退 |

## 二、检索实现（backend/app/services/knowledge_retrieval/）

- `textnorm`：全角/半角、大小写、标点归一。
- `tokenize`：语料词表驱动的最长匹配中文分词 + 双字回退；停用词/停用字（“怎么”“条什”“图在”等函数碎片）过滤。
- `constraints`：区域别名归一（上海/全国/全球，多区域比较问句取全集）、统计年只认 `time` 字段（正文年份仅作 `mentioned_years` 中立匹配——2025 年发布的报告可以描述 2020 年人口）、七普/六普/五普→统计年、指标族（总量≠密度、常住≠户籍）、资料类型。
- `scoring`：字段加权 + idf + 约束乘子；年份冲突的时限性资料直接排除（不同普查年不混淆）；区域冲突排除；比较问句区间年（五普到七普之间的六普）中立保留。
- `engine`：证据覆盖率 + 守门比率（问句里语料缺失的内容词如“股票/房价/航运”达到一定权重时如实无结果）；同义扩展（人口总数↔人口数量）只参与排序不参与守门；方向相反的表述（西多东少）**不**作为同义词；近似重复合并需标题+正文且统计年一致（同一张图的清量版合并、五普/六普不合并）。
- `KnowledgeBaseService`：检索前权限过滤；结果缓存键含 owner/include_all/清单指纹，任何写操作（upsert/material/delete）与文件变更立即失效；新增 `delete_item`（内置条目只读）。
- `KnowledgeService`：同一引擎驱动内置卡片；证据不足返回空列表，由调用方回退。

## 三、评测结果

基线 = 起始提交 `00bb920` 的 `KnowledgeBaseService.search` 打分逻辑（逐行复刻于 `run_eval.py`）。

### 保留测试集（56 条，冻结未动）

| 指标 | 基线 | 优化后 |
| --- | --- | --- |
| Recall@5 | 0.120 | **0.943** |
| Hit@1 | 0.111 | **0.933** |
| MRR | 0.133 | **0.960** |
| nDCG@5 | 0.116 | **0.933** |
| 无答案误命中 | 0/13 | **0/13（0%）** |
| 延迟 p50 / p95 | 0.15 / 0.20 ms | 2.57 / 3.99 ms |

分类召回（保留集）：natural 1.00 · region_year 0.983 · paraphrase 0.879 · ambiguous 0.85。
说明：基线“无答案误命中 0”源于其自然中文问句几乎全部零召回（Recall@5 仅 0.12），两者不可直接比较精度。

### 全量 119 条

| 指标 | 基线 | 优化后 |
| --- | --- | --- |
| Recall@5 | 0.114 | **0.931** |
| Hit@1 | 0.133 | **0.933** |
| MRR | 0.144 | **0.956** |
| nDCG@5 | 0.117 | **0.922** |
| 无答案误命中 | 0/29 | 4/29（13.8%，全部位于调优集暴露的语义类样例，见“已知局限”） |
| 延迟 p50 / p95 | 0.15 / 0.20 ms | 2.69 / 3.14 ms |

分类召回（全量）：natural 0.982 · region_year 0.990 · paraphrase 0.831 · ambiguous 0.888。
助手卡片路径（KnowledgeService，90 条可答样本）：Hit@1 0.933、MRR 0.954、无答案误命中 0。

### 权限隔离与失效（自动化检查 + 实测）

- 跨用户泄漏 0：A/B 两教师各建同名私有资料，交替查询与缓存复用均不串（`permission_and_freshness` 全过）。
- 管理员 `include_all` 全见为设计行为；教师不可见他人私有资料、不可删除内置条目。
- 新增→立即可搜、更新→立即反映、删除→立即消失（清单指纹自动失效，跨进程生效）。

## 四、真实界面验证（后端 19123 / 前端 5193，独立 QA 账号，非演示账号）

1. **搜索**：教师 B 登录 → 数据库面板 → 教学资料 25 项（16 内置 + 素材 + 本人私有 1），筛选“界面验收”仅剩本人条目。
2. **跨用户隔离**：A/B 两账号各建同名“界面验收私有资料”，B 的界面与搜索均不出现 A 的内容（A 为管理员，按设计可见全部）。
3. **更新重查**：API 更新标题/摘要/关键词后刷新页面，界面立即显示“界面验收私有资料（已更新）”与新摘要。
4. **删除重查**：服务层删除（同 live 状态目录）→ 刷新后界面 0 项、总数 61→60，已删内容不再出现。
5. **打开来源**：青浦区条目 → 素材预览展示统计图、CSV 数据表（`/teaching-resources/shanghai_qingpu_population.csv`）与青浦区统计局原文（`https://www.shqp.gov.cn/stat/tjtzgg/20210816/885923.html`，描述明确提示“普查年份与网页发布日期不同”）。

## 五、已知局限（如实报告）

1. **方向相反/否定/比较纠错问句**（t01/t02/t13，调优集）：词面检索无法把“西多东少”连接到讲“东密西疏”的纠错资料（按需求不做反向同义映射）；当前靠“人口分布”等共有词部分命中。
2. **缺失指标/粒度语义**（t07/t08/t12）：语料没有“人口总数排名”“老年人口比例”“小区级”资料时，仍可能返回同区域相邻主题资料；区级街镇汇总不能自动识别为“不能回答小区级问题”。
3. **泛查询 top5 竞争**（n03/p08/a04/a05，调优集；p13/p16/p19/r28/a08/a09/a12 部分召回，保留集）：主线合入新上海资料后，泛区域问句的等价相关资料超过 5 条时按排序截断。
4. **x12“七普的房价数据”**：返回七普数据口径卡片——主题相邻但不含房价，属可辩护的最近邻而非正确答案。

## 六、集成需求（范围外公共接线，请集成负责人处理）

| # | 文件 / 位置 | 现状 | 需求 | 验收 |
| --- | --- | --- | --- | --- |
| R1 | `frontend/src/components/DatabaseViewer.tsx` `filteredEntries`（约 484-495 行） | 知识检索为前端 `haystack.includes(keyword)` 字符串过滤，不走 `/kb/search` 排序 | 教学资料检索改调 `searchKb`（App.tsx 已有封装），结果按后端 `retrieval_score` 排序；保留现状作为离线兜底 | 自然中文问句（如“上海2020年人口普查资料”）在数据库界面按后端排序命中 |
| R2 | `frontend/src/App.tsx`（约 615 行起，`kbQuery/kbItems` 状态已存在） | `KnowledgePanel` 组件未挂载，仅导入类型 | 在合适Dock/页面挂载 `KnowledgePanel`（出处链接、年份、无结果文案均已实现并有组件测试） | 界面可见知识面板并可检索、打开出处 |
| R3 | `backend/app/services/session_engine.py` 557/567 行 | `KnowledgeEngine` 构造时一次性 `build_engine_units()`，知识库新增/更新/删除后助手证据链陈旧直至重启 | 将单元加载改为按清单指纹惰性刷新（可复用 `KnowledgeBaseService` 的指纹缓存），或在知识库写操作后回调失效 | 助手在知识库变更后（无需重启）使用新状态回答 |
| R4 | `backend/app/main.py` + `backend/app/runtime.py` | 知识条目无 HTTP 删除路由（服务层 `delete_item` 已实现并测试） | 增加 `DELETE /kb/items/{id}`（owner 校验同 upsert，内置只读） | 界面/接口删除后 `/kb/search` 立即不可见 |

## 七、合规说明

- 外部模型调用：**0 次，费用 0**（全部评测本地运行；未调用 MiniMax/网络检索）。
- 未批量收录模型生成事实：新增语料仅位于 `scripts/qa/`（评测用合成资料描述，标注 `eval_fixture`，不含统计数字断言），产品知识库（backend 数据文件）未新增模型生成条目。
- QA 账号（kb_qa/kb_qa_b）与私有条目仅存在于本 worktree 运行态（`backend/data/`，不入库）；验收用的私有条目已删除。
- 未修改语音、CopilotWidget、App.tsx、api.ts、types.ts、main.py、models.py、runtime.py、config.py、store.py、session_engine.py、全局样式及其他任务的课堂/报告/地图统计模块；`git status` 仅含本任务范围文件。
