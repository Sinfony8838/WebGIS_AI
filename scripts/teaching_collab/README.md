# MiMo × ZCode 课堂协作

本工具只协调两款真实客户端，不调用模型 API，不模拟角色回答，不自动合并主线或部署。默认每批最多三轮，每轮最多三个问题。`complete` 表示批次停止并已交接，不等于真实教学效果验证通过。

## 本次任务所有权

- 工具分支：`codex/classroom-collab`；起点：`c99c32f8c46cbee1c9636d0d9d46a4660e79426a`。
- 允许：`scripts/teaching_collab/`、`backend/tests/test_teaching_collab.py`、本次 `audit` 交接文档。
- 禁止：课堂业务代码、共享集成文件、主工作区已有改动、凭据、正式服务、运行数据入库。
- 验收：协调器故障测试、`git diff --check`、真实客户端连接探针；课堂优化必须在探针通过后的独立 ZCode 工作树中执行。

## 启动

需要 Python 3.12、项目后端依赖、Git；课堂预览另需 Node、指定工作树中的 `npm ci`。不需要额外模型 API Key。以下操作只初始化独立工作树和本地队列：

```powershell
# 在集成检出中创建专属课堂工作树；有同名目录或分支时先核对，不能覆盖。
git fetch origin
git worktree add .claude/worktrees/zcode-classroom-batch-01 -b codex/zcode-classroom-batch-01 origin/main

$collabPython = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$collabTool = 'C:\Users\zcyxn\Desktop\WebGIS-AI\.claude\worktrees\codex-classroom-collab\scripts\teaching_collab\cli.py'
$collabState = 'C:\Users\zcyxn\Desktop\WebGIS-AI\.claude\teaching-collab-runtime'
$collabWorktree = 'C:\Users\zcyxn\Desktop\WebGIS-AI\.claude\worktrees\zcode-classroom-batch-01'
& $collabPython $collabTool --state $collabState init --worktree $collabWorktree --preview http://127.0.0.1:5197 --npm 'C:\Program Files\nodejs\npm.cmd' --allow-path frontend/src/lesson-workflow.css --allow-path frontend/src/components/ --allow-path backend/app/services/classroom_workflow.py --allow-path backend/app/services/lessons.py --allow-path backend/app/services/lesson_design.py --allow-path backend/app/services/lesson_rehearsal.py --allow-path backend/app/data/builtin/lessons/ --allow-path backend/tests/ --allow-path frontend/src/__tests__/
& $collabPython $collabTool --state $collabState serve --port 18765
```

服务是前台命令；需要后台运行时由启动者以隐藏窗口启动，并保存进程标识。不要创建无限定时任务。不要运行仓库默认一键启动脚本覆盖现有端口。状态页是 `http://127.0.0.1:18765/`，不是课堂页面。

在两款客户端各启动一次独立任务，发送同目录 `teacher.md` 或 `expert.md` 中的任务说明，并给出三个变量的实际绝对路径。两者可以从不同当前目录运行绝对路径入口。MiMo 只读代码，ZCode 只在 `collabWorktree` 修改；不得通过界面选择切换或修改主检出的分支。

角色每次领取后将任务 JSON 保存到各自 runtime 文件；完成后直接领取下一项。`claim --wait 45` 无任务并不是批次完成，`running` 时继续等待。客户端结束会话后不会被共享文件神奇唤醒；必须如实记录此限制，重启同一任务后从队列恢复。

两款客户端的项目选择必须指向各自的工作树目录。MiMo 教师另用 `codex/mimo-classroom-teacher-01` 的只读工作树；不要在主项目的分支菜单里直接切换。教师复验以队列指定的实现提交和预览为准，不以教师只读工作树中的旧文件作运行证据。浏览器使用独立 profile/context，避免不同本地端口共享 Cookie 干扰日常登录。

## 命令协议

所有命令共同前缀为 `& $collabPython $collabTool --state $collabState`。

| 命令 | 参数与行为 |
| --- | --- |
| `claim` | `--role teacher/expert --wait 45 --out <runtime绝对路径>`；返回任务、租约 token、配置、上轮证据 |
| `heartbeat` | `--task ID --token TOKEN --progress "实际进展"`；至少每两分钟报告，延长租约与浏览器锁 |
| `surface` | `--task ID --token TOKEN`；浏览器操作前领取唯一锁，结束加 `--release` |
| `submit` | `--task ID --token TOKEN --result <UTF-8 JSON路径>`；返回 accepted 才可继续 |
| `pause` | `--batch ID --reason "具体原因"`；撤销租约并保留任务 |
| `resume` | `--batch ID`；处理阻碍后恢复，工作树 HEAD 必须匹配 |
| `status` | 完整任务、结果和事件；不输出租约 token |
| `report` | `--out <本地报告路径>`；导出批次 Markdown 证据索引 |

不要修改 SQLite、伪造客户端身份或用脚本代替实际网页点击。租约是防并发和过期提交的机制，不是针对恶意本机进程的安全隔离。角色身份是客户端声明；最终还要核对两款应用任务记录。截图文件校验与哈希只能验证证据文件，不证明课堂效果。

## 连接探针

顺序为 teacher → expert，重复三次。每项领取 `surface` 后，用客户端浏览器打开：

`http://127.0.0.1:18765/probe/<task.id>?lease=<task.token>`

实际点击“验证网页操作”，截图保存到 `<state>/artifacts/`，打开图片读取 challenge。`payload.previous` 是对方上一项结果，必须读后回应。提交示例：

```json
{
  "target_sha": "使用领取任务中的完整SHA",
  "summary": "已阅读对方结果，实际点击并查看截图；记录具体观察",
  "next_step": "交给另一客户端；继续等待下一任务",
  "client": "MiMo Desktop",
  "observed": "点击后页面显示的challenge",
  "screenshot": "artifacts/teacher-probe-1.png",
  "screenshot_read": true,
  "evidence": []
}
```

ZCode 的 client 必须填 `ZCode`。截图由该客户端实际生成，不复用另一客户端或单元测试图片。允许 Playwright 等驱动真实浏览器，不允许直接 POST 探针接口冒充页面点击。探针 URL 带短期租约，只在本机使用，不写进 PR。

先验证一项的暂停、恢复、旧 token 拒绝，再让双方自动完成六项。停顿超过三次租约会暂停；不得以提高重试次数掩盖持续执行失败。接入未通过，不进入课堂修改。

## 课堂流程和结果

所有结果都必须包含 `target_sha`、`summary`、`next_step`，附加 `evidence` 路径数组。证据必须是 state/artifacts 内的非空文件，协调器保存内容 SHA-256。

| 阶段 | 角色 | 额外结果字段 |
| --- | --- | --- |
| discover | teacher | `issues`（最多3项），完整浏览器结果 |
| review | expert | `issues`，`verdict: accept/revise/defer`，独立证据文件；不得编辑代码 |
| agree | teacher | `accepted: true/false`，对评审的具体回应 |
| implement | expert | `new_sha`；提交只能改双方确认的 issues.paths 文件 |
| checks | 本地程序 | 自动执行四项回归，记录实际命令、退出码及日志 |
| verify | teacher | 完整浏览器结果，`outcomes: {问题ID: improved/unchanged/regressed}` |
| handoff | expert | `commit`、`pr_status`、报告证据路径；远端失败也必须如实记录 |

问题必填：`id`（后续修复保持一致）、`stage`、`steps`、`impact`、`proposal`、`acceptance`、`paths`（准确文件，不用目录）。路径必须位于批次 `allowed_paths`。共享集成文件默认不授权；发现必须改动时暂停并说明具体文件、原因及授权请求，不绕过范围。

完整浏览器结果包含 `preview_sha`、`screenshot`、`flow_evidence`（逐步操作、时间、版本、截图索引和异常的记录文件）、`flow_checks`。后者必须包含下列全部键，取值 `pass/fail/blocked`：

`lesson_accept, eight_stages, layers_legends, questions_hints, snapshot, assistant, end_class, report, viewport_1920, viewport_1366, globe, top20, health`。

教学清单见 `classroom-checklist.md`。没有学生数据则“未采集”，模拟作答只在隔离测试课堂并明确标记；真实模型、实际麦克风、投影仪分别记录，不能由软件测试推断通过。

## 独立预览与故障

六项探针通过后，协调器才启动指定工作树的预览：前端5197、后端19079，仅绑定127.0.0.1，认证保持 users，新数据库为该工作树的 backend/data/auth/collab.db。不复制真实用户数据库或旧 runtime。首次管理员初始化由用户在隔离预览完成；受登录阻挡时暂停，不从旧会话寻找凭据。

`/preview` 返回协调程序拥有的进程、工作树和启动版本；客户端必须核对。工作树新提交后自动重启该预览，浏览器锁被占用时等待；端口已被其他服务占用则暂停，绝不终止未知进程。缺少 npm 依赖、后端依赖、地图资料或账号时，保留断点和日志，不把空白图层当通过。

回归失败暂停并生成后续修复任务；同一问题两次未改善则结束本批并记录原因；评审往返两次仍无一致结论则记为待议。达到三轮或可执行队列为空后整理 handoff。最终是否满足“至少一项课堂改善且全课有证据”，须查看实际 verify 结果，不能只看批次 complete。

每个实现任务在自己的工作树显式暂存、审查 staged diff、测试后提交。handoff 可使用 `gh pr create --body-file <报告>` 为本批分支创建一个 PR；远端为 `https://github.com/Sinfony8838/WebGIS_AI.git`。不合并、不部署、不 force push。

## 检查

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest backend/tests/test_teaching_collab.py -q
git diff --check
```

这些用例使用合成探针和临时仓库，只证明协调程序的行为；不能冒充两款客户端连接成功。
