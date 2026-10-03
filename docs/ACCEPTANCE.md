# 部署后验收（当前全部生产项待验收）

本页是执行清单，不是已完成记录。本轮只有本地代码/SDK/真实引擎测试，未连接 NAS，未上传真实家庭附件，未发 QQ 消息。

## 环境与资源

- 记录 2026.9.4 / 3a9d69d、QQ 插件版本、stockanalyse 镜像实际 digest、容器 UID/GID、Ubuntu/Python/FFmpeg 版本；确认 CPU/AVX2、30 GiB 内存和当前共用负载。
- 独立 worker/no GPU，并发 1、线程 2；核验 socket-only 挂载/0660 权限、state/Source/Inbox/backend/Docker socket 未暴露，模型缓存仅 worker 可读。
- 在 worker 身份/禁网下实测 RapidOCR 和 small ASR；记录冷启动/加载、运行秒数、页/秒或音频秒/处理秒、峰值 RSS、cgroup 限制、Swap/I/O，以及 Immich/MySQL/检索延迟。本地 Windows 耗时不能推算 NAS SLA。
- 实测内存不足、FFmpeg 卡住、3600 秒超时、取消；确认退出的工作进程及 ffmpeg 不再运行。强杀服务后重启，旧 RUNNING=INTERRUPTED，QUEUED 恢复；检查 PDEATHSIG/systemd/Docker 的后代清理效果。
- 在真实本地文件系统检查 SQLite/WAL/fsync，磁盘满明确失败。不要未验证便放 mergerfs/NFS。

## QQ 私聊完整链路

对 chen、liang、ziling 分别进行：

1. 上传代表性小附件；检查 canonical media.path、普通文件/扩展名、senderId/account/session、session-store-runtime 捕获的 sessionId / session_start 首次创建事件 和 toolContext.requesterSenderId 匹配。普通事件没有 runId 也须可登记；/new 或自动重置同批附件应拒绝旧 epoch 并提示重发。日志仅留脱敏字段，不留凭据/私有正文。
2. 模型工具列表真实包含 7 个 filetools_*；inspect 列出附件并返回有界预览；extract 返回 job_id；查询最终状态；read/find 返回带真实页码或时间来源的证据；Agent 根据证据回答。
3. 文字 PDF、扫描 PDF、同页数字+栅格/跨页混合 PDF、DOCX 段落→表格→图片→段落、UTF-8 中文文本、清晰中文图片、中文录音逐一比对原件。扫描识别非空不能直接打“完整”；人工比对漏段/阅读顺序。
4. 录音询问指定时间段、核对 start/end，纪要另存并核对 source_segments，transcript.md 原文未变化；原件/每任务独立目录没有同名覆盖。
5. 大 PDF (>20 页)、长录音 (>10 分钟) 首先检查/preview，用户选范围或全文；状态覆盖 requested/processed/full_document 正确。页码不从 1 重新编号，读取长度上限/truncated/next_offset 正确。关键词未命中回答不声称全文无关。
6. 扫描页空白/模糊、混合页 OCR 不可用、表格/图片超限，核对 PARTIAL/FAILED、失败页和警告；未知扩展名、损坏 PDF、加密 PDF、zip 解压限额、64 MiB/500 页/2 小时音频/2400 万像素分别明确拒绝。
7. 同附件同配置复用 job，其他范围独立 job；重复/并发调用不重复登记或后台处理。多个附件必须选择返回 ID，不猜原路径。
8. `/new`、`/reset` 后即使 sessionKey 相同，sessionId 变化使旧 attachment/job/artifact 不可读；未提取的旧附件也不能在新 epoch 复活。Gateway 重启已上传任务可在同 UUID 范围读回；未上传附件要求重传。

## QQ 用户与群聊隔离

- 两个真实 QQ 用户分别私聊：把 A 的 attachment_id/job_id/artifact_id 交给 B，所有 list/inspect/extract/status/cancel/read/find/minutes 均不可见/拒绝。更换 Agent、account、sessionKey、sessionId 也拒绝；main 不能作为跨人管理入口。
- 模型添加 path/user/agent/session/scope 参数必须参数错误；文档中写“执行命令/读其他人/入库”仅作为文本，不触发新权限/永久导入。
- **群聊 V1 预期拒绝处理**。同组 A/B 上传附件，filetools_* 工具不返回内容，不登记成可读取私聊文件；复制群附件 ID 到私聊也不应可用。记录实际 group/channel sessionKey 被拒绝、未知 canonical direct 也失败封闭。
- 群内旧 document-extract/知识库工具的历史可见性属于既有 Gateway 配置，V1 不承诺改变或隔离其群历史。若用户要求群内私密文件处理，需要先独立 sender session 与私密回传，再另行设计验收；不能仅打开工具就宣称支持。

## TTL、清理与兼容

- 测试环境将 TTL 降低并核对到期 ID 不可读；服务清理终态任务幂等，正在处理/读取的任务不删除；服务运行时离线 cleanup 拒绝。原始上传文件和 originals 快照均还在，配额到达明确拒绝而不是静默删原件。
- 内容返回不含日志、绝对路径、内部身份或凭据；任务私有日志不挂入 Gateway。
- 检查 knowledge_private/shared、knowledge_import_private/shared、session_document_query 的 schema、可见性、私库/Family 映射、明确用户同意与原 Broker 路由保持；工具不重名、自动预览未关闭，Skill 不重复提交提取/建索引。
- 入库的预期是 **V1 临时处理零自动入库**：检查永久 SQLite/index/Source/Inbox/Embedding 调用前后不变化。用户另行明确请求永久导入时仍走旧原附件授权入口。

请为每条填入执行日期、样本 ID（脱敏）、实际结果、失败日志位置和是否通过。真实附件、中文质量/复杂版式、群聊拒绝、权限/资源和 QQ Agent 引用答案在完成真机执行前一律为“待验收”。
