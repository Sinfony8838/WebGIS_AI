# 分支与未提交内容梳理（2026-09-08）

> 下文保留最初盘点时点的状态。zcode 已结束并推送至 `bb3d14b`；后续集成状态和验证结果以 [INTEGRATION_REVIEW.md](INTEGRATION_REVIEW.md) 为准。

基线：`origin/main = a0491a1c1b029617b1f9161e9ee00446f415f2bb`。
本次整理分支：`codex/branch-inventory`，从该基线创建独立 worktree。
目标是保存尚未发布的代码、识别重复历史和集成风险，不把所有旧分支直接合入 main。
允许写入范围仅为本清单及明确指定的 Git 分支引用；原工作区业务文件不修改。

## 当前运行任务：排除

`claude/choropleth-replay` 对应 zcode 的模板样式补齐、工作流实测和回放优化。
仓库 `.zcode/plans/plan-sess_bb6f9061-8c41-4944-afd2-50ffe56a984e.md` 明确声明该分支，与用户截图任务内容一致。
检查时该分支为 `91c9c63`，存在未提交业务修改与测试脚本。本次不提交、不推送、不切换、不清理该分支，不操作其服务进程。

## 本轮保存 / 同步的分支

| 分支 | 保存的提交 | 结论 |
| --- | --- | --- |
| `codex/agent-harness-v2` | `934bdb0657a9a0184618e33619dae21f033df882` | 独立新增 harness 实现，1 个提交尚未进入 main；需适配最新交互代码后再集成 |
| `codex/assistant-image-library-tuning` | `aab7f188e9f79a337817ccd2a83c7da8ebadce6c` | 4 个提交的合并补丁与 main 的 `49151bf` 完全等价；仅保存历史，不重复发功能 PR |
| `codex/release-hardening-continuation` | `7b449b6a8b8cd38ee7bbaa978c938543a8167a35` | 旧整合版本；大量修复已进入 `3a62551`，不直接合并整条分支；保留原提交便于逐项溯源 |
| `codex/p0-persistence-globe` | `0e612c958a2a8333215b4e095b8c94b6b0ec0d83` | 与 main 的 `141af4c` 补丁等价；仅保存历史 |
| `codex/agent` | `ead7891` | 本地比原同名远端领先 2 个提交，但已被 main 包含；快进同步远端引用 |
| `codex/teaching-pet-runtime-recovery` | `141af4c` | 本地比原同名远端领先 2 个提交，但已被 main 包含；快进同步远端引用 |

没有改写上述提交，没有 force push，没有把未验证的旧版本放到 main。

## 等价与覆盖证据

### 图片分支：确认整体等价

对比以下两份补丁的 `git patch-id --stable`：

- `git diff 043f7d5 codex/assistant-image-library-tuning`
- `git show --format= 49151bf`

结果均为 `2d0cf807a6e4e061dd3c29b81c0331e52ffc3a5e`。
因此，单看 4 个旧 commit SHA 不在 main，会误判为图片功能尚未集成。

### 持久化分支：确认补丁等价

`git cherry origin/main codex/p0-persistence-globe` 输出 `- 0e612c9...`；main 含 `141af4c`。
不创建重复集成请求。

### 旧发布加固：有明确覆盖，但不宣称整条等价

`7b449b6` 与 main 中 `3a62551` 的以下文件内容完全一致：

- `backend/app/services/assistant.py`
- `backend/app/services/population_sources.py`
- `backend/app/services/reports.py`
- `backend/app/services/vision.py`
- `frontend/src/auth.css`
- `frontend/src/components/SideDrawer.tsx`
- `frontend/src/mapScreenshot.ts`
- `frontend/src/components/QuizOverlay.tsx`（两边均已删除）

其他文件经过教案共创、课堂面板等后续变更，不能仅以 commit ID 或自动合并结果断言缺失功能。
保留该分支用于复查，不恢复旧 UI 或已删除组件。

## 未提交文件：不重复制造代码提交

1. `codex/release-hardening-continuation` 工作区的 `frontend/src/__tests__/LessonWorkflow.test.tsx`：唯一差异是删除末尾空行，没有新增业务逻辑。原分支提交的差异检查会报 `new blank line at EOF`；本次记录，不为历史代码单独制造格式提交，也不恢复用户文件。
2. `claude/release-hardening-20260822` 工作区的三个文件：
   - `backend/app/main.py`：图片上传/生成的项目访问校验已在 main；当前 main 另有付费确认检查。
   - `backend/app/services/assistant.py`：避免把图层、标注、底图、图例误判为图片生成的保护已在 main。
   - `backend/app/services/population_sources.py`：错误消息不暴露本地文件路径的修复已在 main。
   这些残留不需要再次提交或推送。原文件保持不动。
3. 主工作区 `.zcode/`、`scratch/`，以及旧 `question-bank-lesson-flow` 工作区的 `scratch/`：属于任务计划/临时内容，未纳入提交。

## 三个失效的旧工作区

以下路径的 `.git` 文件仍指向移动前的 `Desktop/项目开发/WebGIS-AI/.git/...`：

- `Desktop/项目开发/WebGIS-AI-claude`
- `Desktop/项目开发/WebGIS-AI-opencode`
- `Desktop/项目开发/WebGIS-AI-worktrees/claude-workspace`

通过当前仓库已登记的 `.git/worktrees/<name>`，显式指定 `--git-dir` 和 `--work-tree` 并使用 `--no-optional-locks` 进行只读检查：三个工作区均无未提交变化。
其对应分支均指向已被 main 包含的 `35f67a3`。无需补交业务文件；本次不修复或删除这些工作区指针。

## 待集成内容与已有 PR

| PR / 分支 | 状态与注意事项 |
| --- | --- |
| [#8 数据库优化](https://github.com/Sinfony8838/WebGIS_AI/pull/8) | 已推送，OPEN；保留独立评审 |
| [#9 保守维护](https://github.com/Sinfony8838/WebGIS_AI/pull/9) | 已推送，OPEN；涉及语音停止和工作流状态竞态 |
| [#10 主题与布局](https://github.com/Sinfony8838/WebGIS_AI/pull/10) | 已推送，OPEN；与 #11 的 App 初始化修复有重叠 |
| [#11 智能交互](https://github.com/Sinfony8838/WebGIS_AI/pull/11) | 已推送，OPEN；包含独立实测报告，不代表完整自主规划 |
| `codex/agent-harness-v2` | 尚未集成；原基线为 `4cbbb61`。模拟与最新 main 合并时，`config.py`、`runtime.py`、`llm_planner.py`、`session_engine.py` 四个文件冲突；需同时核对 #11 和 zcode 后续交互/工作流修改 |
| `origin/claude/pensive-aryabhata-a3a44b` | 旧远端分支，PR #1 已 CLOSED、未合并；包含旧 QGIS bridge 路径，不恢复或重开旧 PR |

`git merge-tree --write-tree --name-only --no-messages` 仅用于对象层冲突预演，未改动 main、索引或工作区文件。
图片和旧发布分支也存在大量历史冲突；补丁已被集成或重写时，机械合并不是正确的恢复方法。
下一阶段由集成负责人结合功能意图按依赖顺序集成，尤其不能对共享文件整文件取一侧。

## 验证与交接

- Harness 原分支：Python 3.12 执行 `python -X utf8 -m pytest backend/tests -q`，**399 passed、9 subtests passed，49.43 秒**；相对主线差异 `git diff --check` 通过。
- 上述测试是在 `934bdb0` 上执行，**不代表与最新 main / PR #11 合并后通过**。该分支仅改动文档和后端，本轮未重新运行其前端测试、构建或真实浏览器验收。
- 图片分支：相对主线的 `git diff --check` 通过，整体补丁等价已验证；本轮不重复运行历史版本完整测试。
- 旧发布分支：上述空行差异检查未通过，已明确保留为历史记录；本轮未宣称该旧版本通过全部门禁。
- 本整理分支只新增本清单，检查 Markdown 链接、记录 SHA、`git diff --check`，无需运行业务测试。
- 原工作区未提交文件、zcode 正在运行的分支、数据库、依赖和本地认证配置均未修改。
