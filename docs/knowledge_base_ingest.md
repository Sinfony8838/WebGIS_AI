# Knowledge Base Ingest Guide

本文说明当前本地知识库的数据结构、权限、检索和导入方式。知识库结果是助教回答的证据来源之一，不等同于模型自行验证过的事实。

## 1. 数据与知识层

- 空间数据层：教师上传的 GeoJSON、CSV、ZIP Shapefile 和 PNG/JPG 覆盖图。
- 知识层：`backend/app/data/builtin/knowledge/kb_manifest.json` 中的教学卡片，以及通过认证 API 写入的教师私有条目。
- 地理补充层：`backend/app/data/builtin/knowledge/geo_knowledge.json`。

每张卡片可包含：

- `id`、`title`、`topic`、`region`、`time`
- `source`、`license`、`grade_level`、`keywords`、`crs`
- `summary`、`canonical_answer`、`teaching_points`、`citations`
- `dataset_refs` 和 `materials`
- `owner_user_id`：空值表示内置公共条目；非空表示教师私有条目

## 2. 当前 API

- `GET /kb/manifest`：普通教师返回公共条目和本人条目，管理员返回全部可管理条目。
- `GET /kb/search?query=&topic=&region=&tag=&limit=`：先按权限和显式条件过滤，再做中文词法、语义词组及区域/年份/指标约束排序。
- `GET /kb/topics`：只基于当前用户可访问的条目聚合主题。
- `POST /kb/items`：新增或更新当前用户有权管理的私有知识卡片。
- `DELETE /kb/items/{item_id}`：删除有权管理的私有条目；内置公共条目只读。
- `POST /kb/layers/register`：将当前项目中的课堂图层登记为知识条目。
- `POST /kb/materials/upload` / `POST /kb/materials/link`：为有权访问的知识条目上传或链接素材。

所有写操作都使用当前登录用户的所有者作用域；普通教师不能读取、覆盖或删除其他教师的私有条目。不可访问 ID 与不存在 ID 均返回 404，避免泄漏条目是否存在。

## 3. 检索行为

当前检索是本地词法与约束驱动检索，不是通用向量数据库或自然语言推理系统。它会处理全半角、大小写、标点、同义词组和部分中文分词，并把区域、年份、普查简称、指标族和资料类型作为约束：

1. 权限和 `topic` / `region` / `tag` 显式筛选先于排序。
2. 高特异问题必须由对应概念组覆盖，不能只靠“上海”“人口”等宽泛重叠凑答案。
3. 没有足够证据时返回空结果或 `insufficient=true`，不强行拼出 Top-N。
4. 写入、素材变更和删除会使相关缓存失效；内置 manifest 或地理知识变化后会按文件指纹惰性刷新。

可用以下评测复现当前基线：

```powershell
python scripts/qa/knowledge_retrieval/run_eval.py --split all
```

评测范围和已知局限见 [`qa/knowledge-retrieval.md`](qa/knowledge-retrieval.md)。

## 4. 导入与维护

推荐通过认证 API 或前端“教学资料”面板写入，不要在服务运行时手工修改 manifest。批量图层导入可使用 `scripts/batch_ingest_kb.ps1`，它调用 `/datasets/upload` 与 `/kb/layers/register`。

仓库维护者可以在停服状态下审查并修改内置 JSON；内置条目必须保留可追溯的 `source`、`time` 和安全的 HTTP(S) `citations`，并通过测试后提交。教师运行期新增条目应保留 `owner_user_id`，不得改造成所有用户可见的无主条目。

## 5. 助教接地

所有 assistant 模式都使用统一 Agent Harness；`WEBGIS_AI_ASSISTANT_V2_ENABLED` 只是兼容旧部署保留的废弃配置，不再控制路由。

助教回答知识类问题时会把可访问的检索结果与当前地图、课时和课堂阶段上下文一起处理。MiniMax 可用时由模型组织自然语言回答；不可用时走规则兜底。弱证据不会被伪装成权威结论，界面会展示实际来源或明确说明资料不足。
