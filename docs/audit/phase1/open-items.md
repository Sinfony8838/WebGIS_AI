# Phase 1 遗留与受限事项（BLOCKED / 待授权）

以下各项在本轮**未完成**，不以"阶段全部完成"概括。

## BLOCKED（需账号/设备/授权）

1. **线上验证**：当前实际线上 SHA、构建资源、启动配置无法确认（仓库无 release/build-info 产物）。线上只读检查、登录态验收、真实写操作、付费调用——均需专门授权。
2. **浏览器 E2E**：隔离环境教师 A/B 资源互访、完整课堂流（草稿→确认→预演→开课→观察→结束→报告）、AI 超时/QGIS 不可用/SSE 断开降级路径——需浏览器验收环境与授权。
3. **真实设备**：真麦克风中文指令（含否定句、讲课与命令混杂）、手机/平板触控完整流程。
4. **人工无障碍**：键盘主流程、焦点可见、缩放、语音文本等价操作——需真人评估；不宣称 WCAG 合规。
5. **真实课堂与恢复演练**：教师独立完成真实课堂、生产备份恢复演练。

## 受限修复（本轮许可路径外，需后续轮次）

6. **auth.py grant_file 授权改派**：`ON CONFLICT(path) DO UPDATE SET user_id=excluded.user_id` 允许同一文件的授权被后授予者改派。本轮在调用侧收口（_grant_response_files 只授予已授权根内的真实资源），改派面已大幅缩小，但根修需改 auth.py（不在本轮允许路径）。
7. **AI/语音调用并发准入**：minimax_client / agent_harness / voice_asr 的出站调用并发闸不在本轮允许路径；T3 只落地了 QGIS 管线 AdmissionGate 与语音会话数上限。
8. **api.ts/types.ts 收尾**：HealthResponse 类型仍包含已收窄字段，前端本地已用 UiCapabilities 覆盖消费点；类型层清理属集成保留文件。
9. **uvicorn access log 对 legacy_token query token 的记录**：应用层零日志调用（已核验），但标准 access log 会记录 URL query；建议部署侧关闭 access log 或迁移 legacy_token 到 cookie/头。

## 待确认（信息缺口）

10. 反向代理请求限制、Cookie Secure、可信代理头、API 进程数与 worker 配置（需运维信息）。
11. 私有题库图片/答案逐项正确性与来源许可；真实参与者数据口径。
12. 本地主检出 4 个未提交条目（.zcode/、backend/data/、scratch/、人口教案 docx）内容未核实——属集成所有者。
