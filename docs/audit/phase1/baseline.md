# Phase 1 审计执行——T0 基线与证据清单

- 记录时间（UTC）：2026-09-19T13:31:53Z
- 执行环境：Windows 10.0.26200 x64 / Git Bash；本地 Python 3.12.10（`%LOCALAPPDATA%\Programs\Python\Python312`）；本地 Node v24.14.0（CI 为 Node 22，见 `.github/workflows/quality-gate.yml`）。
- 本文件路径在 `docs/*` gitignore 规则内，按仓库既有做法以 `git add -f` 纳入版本库。

## 一、基线四列（不互相替代）

| 列 | SHA | 说明 | 复核方式 |
|---|---|---|---|
| GitHub main（本轮开发基线） | `a890b527335f8e0761dd7e73b945c1c107cd03b6` | PR #30 合并点；本轮工作树从此建分支 | `git fetch origin && git rev-parse origin/main`，2026-09-19 实测一致 |
| 本地主检出 HEAD（未动） | `c99c32f8c46cbee1c9636d0d9d46a4660e79426a` | 分支 `codex/desktop-latest-20260910`；4 个未提交条目：`.zcode/`、`backend/data/`、`scratch/`、`项目设计要求/人口分布教案参照.docx`（仅记录条目名，未读取内容） | `git rev-parse HEAD && git status --short` |
| 构建版本 SHA | 无法确认 | 仓库无 release.json / build-info 产物；FastAPI 版本常量 `1.1.0`（backend/app/main.py）。当前线上运行版本无法确认，不得称 main 已上线 | 仓库全文检索（build_sha/release.json/GIT_SHA 均无） |
| 历史发布清单 | `02fd30224b58e4757b007fbab8750e4832fad2d1` | 来自审计 MCP 证据（public-runtime/release.json @ 2026-09-13），与 main 不同 | 引用审计记录，未本地复核（生产目录不在本工作树范围） |

## 二、CI 基线独立复核

- Quality gate run `34757637543`：`gh run view` 实测 `status=completed, conclusion=success, headSha=a890b527…`，标题「修复智能控制界面并重组教案设计布局 (#30)」。与审计记录一致。

## 三、本轮工作树

- 路径：`WebGIS-AI-worktrees/claude-phase1-hardening`（与生产主检出物理分离）。
- 分支：`claude/phase1-hardening`，起点 `a890b527335f8e0761dd7e73b945c1c107cd03b6`。
- 隔离核验（2026-09-19T13:31Z）：`backend/data` 不存在；`.env` 不存在；`find -maxdepth 2 -type l` 无符号链接；`dir /AL /B backend` 无 junction。命令退出码 0。

## 四、本轮已执行的读取命令

| 命令 | 结果 |
|---|---|
| `git fetch origin` | exit 0 |
| `git rev-parse HEAD`（主检出） | c99c32f8… |
| `git rev-parse origin/main` | a890b527… |
| `git status --short`（主检出） | 4 个未跟踪条目（见上表） |
| `git worktree add … -b claude/phase1-hardening a890b527…` | exit 0，工作树干净 |
| `gh run view 34757637543 -R Sinfony8838/WebGIS_AI --json …` | conclusion=success |

## 五、验收状态体系（本轮起用）

- `PASS`：有命令、退出码与产出证据的实测通过。模块/接口存在**不算** PASS。
- `FAIL`：实测未通过，附输出摘要。
- `BLOCKED`：缺账号/设备/授权/环境无法执行（如线上登录、真实课堂、真人麦克风、付费调用）。
- `NOT_RUN`：本轮计划内但未执行（如全量长时测试尚未结束），附原因。
- README/PR 自述一律记为「历史报告」，不计入 PASS。
- 记录脱敏约束：不含凭据、账号、学生身份、可复用会话标识、本机绝对路径（工具版本与目录标签除外，且不指向生产数据）。
