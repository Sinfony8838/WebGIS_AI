# 框架交接（2026-09-12）

用户将本阶段范围收敛为搭好框架、启动两端，随后由 MiMo 与 ZCode 自行处理；协调者不持续操作窗口或代替双方完成教学验收。

## 分支与范围

- 框架：`codex/classroom-collab`，起点 `c99c32f8c46cbee1c9636d0d9d46a4660e79426a`。
- MiMo：`codex/mimo-classroom-teacher-01`，只读教师工作树。
- ZCode：`codex/zcode-classroom-batch-01`，独立实现工作树。
- 改动仅为 `scripts/teaching_collab/` 和 `backend/tests/test_teaching_collab.py`；未修改产品业务代码或主工作区无关文件，未合并或部署。

## 本机已启动

运行目录：`C:/Users/zcyxn/Desktop/WebGIS-AI/.claude/teaching-collab-runtime`。
批次：`batch_c386e9d18809`。状态页：http://127.0.0.1:18765/ 。

两端任务已实际发送，项目选择分别指向各自工作树。交接时首个教师探针已领取；六项真实探针、完整课堂证据和至少一项修复复验尚未确认通过。不得将框架测试结果写成这些验收已完成。

队列、日志与证据保留在运行目录。暂停、恢复、导出记录及服务重启命令见 README；已有队列不要再次 init。客户端退出后需重新启动原角色任务才能继续领取，框架不自动启动桌面客户端。当前服务保持运行；退出服务或重启电脑后需重新运行 serve。没有创建定时任务。

## 检查

- Python 3.12：`python -m pytest backend/tests/test_teaching_collab.py -q` → **33 passed in 18.31s**。
- `git diff --check`：通过。
- 覆盖重复提交、租约到期、暂停恢复、旧版本与分支变化拒绝、浏览器互斥、证据约束、路径越界、轮次及修复失败停止条件。
- 未改课堂或前端功能，本次没有运行全项目后端/前端回归；每次课堂实现后的四项回归由协调服务执行。

## 后续责任

MiMo 负责试讲、证据与最终网页复验；ZCode 负责独立评审、获确认的实现及待合并成果。框架只派单、管理互斥和检查结果。出现权限、工具、登录、数据或依赖问题时保留断点并记录具体原因，用户需要时再请求修复。正式网页保持不变。
