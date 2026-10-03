> 这是87f93ac交付的V1历史记录，限额/接口不代表当前V1.1。当前说明见 [V11_ARCHITECTURE](V11_ARCHITECTURE.md)。本轮远程CI未执行，不能将历史或已编写工作流视为V1.1 CI通过。

# V1 架构取舍（ADR）

## 1. 单独的 CPU 服务，不使用检索环境

Python 包 nas_filetools 是 CLI 与插件共同使用的核心。独立 Python 3.11–3.12 环境（开发实测 3.12.3）调用引擎，SQLite 仅记录临时任务；没有 Embedding、向量索引、永久入库、Source/Inbox 访问或永久库 socket。插件通过固定 Unix HTTP socket 上传经过登记的字节并调用结构化接口。服务只能在 Linux 上启用；Windows 支持核心/工作进程开发测试。

NAS 初始重任务并发 1、引擎线程 2。配置可调整并发 1–2、线程 1–8、进程虚拟地址空间上限、任务墙钟超时与检查超时。systemd / Docker 样例另限制整个服务 2 个 CPU、4 GiB 内存和 96 个任务；这些是真正整体 RSS/cgroup 边界，worker_memory_mb 的 RLIMIT_AS 是虚拟地址空间边界，两者不能混称。默认 CPU/int8 语音，无 GPU。Windows 未应用 Linux 内存/process-group 限制，NAS 限制效果待验收。

## 2. 可信身份和登记

插件管理配置显式绑定 `channel_id + account_id + sender_id + agent_id → user_id`，固定映射 main/chen→chen、liang→liang、ziling→azl。绑定必须唯一，不能由模型设置。工具身份还要求可信 requesterSenderId、sessionKey、sessionId 与渠道/account；范围键是用户、Agent、SHA256(sessionKey + NUL + sessionId) 的哈希。Agent 和真实用户不同，main 并不授予查看所有人的权利；同一用户的 main/chen 也不会共享会话任务。

只读取公开 message_received 的 canonical media.path，匹配 sender/session/message 事实。2026.9.4 普通入站 mapper 不提供 runId，因此不能按类型声明中可选的 runId 建立必需关联。入口用公开 session-store-runtime 的 getSessionEntry（readConsistency=latest）只读捕获现有 sessionId；工具使用自身可信 sessionId 校验。首次创建还没有存储条目时，在任何异步文件读取前保留待绑定记录，仅 session_start 的无 resumedFrom 首次创建事件可解析；session_end、reset、存储异常及缺失事件均失败封闭。生命周期只更新首次创建记录，不重新绑定原来会话的文件。

随 /new、自动 idle/daily 重置一起到达的附件可能捕获到旧 epoch，保守拒绝在新会话读取；应完成新会话建立后重新上传。TTL 内最多 100 个内存登记会话、每会话 8 个附件及 100 个首次创建待绑定记录。Gateway 重启后已上传附件/任务仍能按当前可信 sessionId 查询；未上传的内存登记丢失，需重新上传。缺失可信原始 epoch 返回 ATTACHMENT_SESSION_UNRESOLVED。SDK 只读会话存储的真实 Linux 验证及 QQ lifecycle 时序仍待验收。

登记检查普通文件、符号链接、dev/inode/大小/mtime/ctime；O_NOFOLLOW 打开后 fstat，预哈希后再核对，再从同一 fd 流式发送。服务核对 SHA256 后保存独占只读权限快照。模型只看到登记 ID，不提供路径、URL、scope、用户、Agent、会话或 socket 参数。未提供原名的渠道使用 staging basename；没有支持的扩展名会明确失败，模型不能改名。

**群聊 V1 拒绝**：即使返回数据按 sender 隔离，共享群会话的 LLM 历史/转发仍可能暴露文字，因此不能声称在共享群历史内实现了私密回答。SDK 验证需要 canonical direct session，拒绝 group/channel、未知身份和共享 main 风格会话；渠道不是这种结构时先验收/调整可信适配，不能放宽为只认 Agent。后续群聊需 sender 独立 session/私密回传与历史隔离后重新设计。

威胁边界：固定 socket 只允许可信 Gateway 插件和管理员连接；同 UID 中具备任意代码执行的 Agent 可以绕过逻辑接口伪造身份。V1 不提供密码学认证/强沙箱隔离，强隔离需要 per-user UID/容器/capability。不得给 Agent 挂载 state、原件目录、NAS Source、数据库或 Docker socket。

## 3. 任务与恢复

QUEUED → RUNNING → SUCCEEDED / PARTIAL / FAILED；取消有请求标志并最终进入 CANCELLED；墙钟超时 TIMED_OUT；服务重启将旧 RUNNING 变为 INTERRUPTED，明确重提；未开始 QUEUED 保留并恢复（已过 TTL 则超时）。失败/取消/中断不会伪装成结果复用。相同 scope、attachment/hash、标准化配置、引擎版本标识及 limits 的请求，复用活跃或成功/部分成功任务；不会跨用户/会话复用。

单一 supervisor 由 OS 文件锁约束，后台子进程可终止；Linux 每个子进程独立 process group，取消会结束 ffmpeg 后代，父进程异常退出通过 PDEATHSIG 清理，systemd KillMode 再提供进程组保护。子进程写 progress 到 SQLite，最终产物先写 sources.json 再发布结果标记，由 supervisor 更新终态。数据库 WAL、任务目录随机 UUID，机器结果不混日志。

SQLite 只支持本地可靠文件系统；不把 state 放到未验证锁语义的 mergerfs/NFS。CPU/OCR、ffprobe 解码、模型载入都有有界检查或进程超时。引擎日志是任务私有文件，可能包含第三方信息，不挂给 Agent。

## 4. 成功与覆盖

SUCCEEDED 仅指请求的 scope 完成，不表示识别准确率/版式完美；preview/range 永远不冒充全文。PARTIAL 有证据且有失败块/页；FAILED 没有可用识别文本。未读内容不补造。扫描页有文字也附质量警告；混合 PDF 含图像的页整页 OCR，失败可恢复已有数字文字，但该页明确 incomplete 并记录失败。DOCX 图像保留但未 OCR，纯图像正文块记为未识别，混合文档可能 PARTIAL，纯图像文档 FAILED。

## 5. 生命周期与原件

原件快照 `originals/<opaque scope>/<attachment_id>.<ext>`；任务 `tasks/<job_id>/`。默认 72 小时到期访问拒绝，服务启动/每小时清理终态任务；活跃/排队任务或受锁保护的读取不会被删。离线 cleanup 必须拿服务独占锁。拒绝符号链接清理目标，不按模型路径删除。

**自动清理不删除 Gateway 原件或 originals 快照。** 快照到期只停止工具访问，管理员需制定独立原件备份/归档保留政策。每 scope 最多 8 个有效附件、累计原件 1 GiB、32 个有效任务；到期快照仍占原件配额，防止静默删除原文。不同 session scope 的配额不是全盘配额，部署须为 state 使用独立磁盘/项目配额并监控剩余空间，V1 不承诺全 NAS 自动空间管理。

## 6. 与现有插件共存

只注册 filetools_*，没有 knowledge_* / session_document_query 重名；观察消息不 claim、不改正文、不自动抽取/OCR。检查时才上传/preview probe，extract 时才启动重任务。既有 bounded document-extract 可继续小预览；Skill 规定复用任务，不把同一问题同时送旧脚本和临时检索索引。旧 Skill 加入口提示以降低重复执行；不更改现有查询/导入授权。

附件正文始终不可信。Skill 只指导使用真实工具，不赋予正文工具权限。后续用户要永久导入仍使用既有明确同意流程，与临时处理结果无自动联系。
