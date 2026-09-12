# 中文知识库检索质量与来源可追溯 — 评测与集成记录

PR 源分支：`claude/knowledge-retrieval-quality`（原始头提交 `4f8d813`）

本轮审修基线：`origin/main@4ca6afb`（已包含 PR #23–#27 中已合并部分）

评测语料：`scripts/qa/knowledge_retrieval/corpus.json`（内置条目、geo 单元和仅用于评测的合成资料）

样本集：`scripts/qa/knowledge_retrieval/samples.py`，119 条中文问句（调优集 63 / 保留集 56）

复现：`python scripts/qa/knowledge_retrieval/run_eval.py --split all`

## 一、当前真实调用链

| 调用方 | 当前路径 | 状态 |
| --- | --- | --- |
| 前端知识检索 | `searchKb` → `GET /kb/search` → `runtime.kb_search` → `KnowledgeBaseService.search` | 已接入共享检索引擎；权限和显式筛选先于排序 |
| 数据库“教学资料” | `DatabaseViewer` 输入 → 防抖调用 `searchKb` → 按 `retrieval_score` 展示 | 已接入语义检索，不再对后端结果二次做整句字面过滤 |
| 资源检索 / 教案设计 | `ResourceSearchService` / `LessonDesignService` → `KnowledgeBaseService` | 使用同一检索服务 |
| 助手本地证据 | `KnowledgeEngine` → 共享 `RetrievalEngine` | 每次匹配检查 manifest + geo 指纹，无需重启即可刷新公开知识 |
| 讲解兜底 | `runtime._compose_knowledge_answer` → `KnowledgeService.search` | 使用同一引擎；弱证据返回空列表 |
| 删除知识条目 | `DatabaseViewer` → `DELETE /kb/items/{id}` → runtime → service | 仅显示私有条目删除入口；服务端按登录 owner / admin 作用域校验；内置条目只读 |

## 二、实现与审修要点

- 归一化与分词：处理全半角、大小写、标点；语料词表最长匹配并以双字回退。量词“个”不再制造“某个/个小”等伪内容词。
- 约束：区域、统计年、普查简称、指标族和资料类型参与匹配；区域或年份冲突会排除不适用资料。
- 必需语义组：房价、排名、老年人口、小区粒度等高特异限定不能被“上海/人口/七普/青浦”等宽泛重叠替代；同组别名（如小区 / 社区 / 街区）可互相覆盖。
- 证据守门：语料缺失真实问点时返回 `insufficient=true`，不硬凑 Top-N。
- 显式筛选：topic / region / tag 先缩小可访问语料，再在筛选后的索引中评分与截断，避免正确条目被全库 Top-N 挤掉。
- 权限与缓存：索引和结果缓存键包含 owner、管理员作用域、筛选条件及清单指纹；写入、素材变更和删除都会失效。
- 来源展示：当前用户实际使用的 `DatabaseViewer` 直接展示年份、来源和安全的 HTTP(S) citation 链接；未重复挂载旧的独立 `KnowledgePanel` 浮层。
- 删除闭环：新增认证 DELETE 路由、运行时转发、前端 API 与确认交互；不可访问 ID 与不存在 ID 同样返回 404，避免泄漏。

## 三、评测结果

基线是原起始提交 `00bb920` 的 `KnowledgeBaseService.search` 打分逻辑，由评测脚本逐行复刻。以下为本轮审修后的代表性本地运行结果。

### 全量 119 条

| 指标 | 基线 | 审修后 |
| --- | ---: | ---: |
| Recall@5 | 0.114 | **0.928** |
| Hit@1 | 0.133 | **0.933** |
| MRR | 0.144 | **0.954** |
| nDCG@5 | 0.117 | **0.923** |
| 无答案误命中 | 0/29 | **0/29** |
| 延迟 p50 / p95 | 0.15 / 0.16 ms | 2.51 / 2.91 ms |

分类召回：natural 0.982、region_year 0.991、paraphrase 0.823、ambiguous 0.888。

`KnowledgeService` 可答样本 Recall@3 0.879、Hit@1 0.922、MRR 0.943；无答案误命中 0/29。

延迟为同机单次代表值，会随机器负载波动；排序质量指标连续复验保持一致。

### 权限与新鲜度

- A/B 两教师同名私有资料交替查询：跨用户泄漏 0。
- 管理员 `include_all` 可见全部私有条目；普通教师只见公共条目和本人条目。
- 新增、更新、删除后立即反映到搜索结果。
- 助手公开知识索引在 manifest 或 geo 文件改变后惰性刷新，无需重建 `KnowledgeEngine`。
- 内置条目删除被拒绝。

## 四、本轮验证边界

已执行：

- 后端知识检索、助手、授权、数据库运行时定向回归。
- 前端 `DatabaseViewer`、API、`KnowledgePanel` 组件回归。
- TypeScript 与 Vite 生产构建。
- 119 条离线检索评测。

原 PR 曾记录在独立端口和 QA 账号上的手工界面检查；本轮没有把该历史记录当作当前浏览器验收。本轮最终合并前仍以全量后端、全量前端、CI 与构建结果为门禁。

## 五、已知局限

1. 这是本地词法与约束驱动检索，不具备通用自然语言推理能力；方向否定、反事实和复杂多跳问题仍需要上层助手审查。
2. 泛区域查询可能有超过 Top-N 的等价资料；返回集合受 `limit` 约束。
3. 高特异限定词只有在知识文档明确覆盖同组概念时才返回，设计上偏保守，优先避免课堂中把邻近主题冒充答案。
4. `KnowledgePanel` 组件仍保留供其他页面复用，但当前产品入口采用 `DatabaseViewer`，未额外挂载重复面板。

## 六、合规说明

- 外部模型调用：0 次；评测全部离线运行。
- 评测合成资料只在 `scripts/qa/`，未写入产品知识库。
- `report.json` 是运行产物，不提交。
- 本轮修改覆盖共享接线文件 `App.tsx`、`api.ts`、`types.ts`、`main.py`、`runtime.py`、`session_engine.py` 及对应测试；未修改地图、天气、语音、人口工作流或课堂报告逻辑。
