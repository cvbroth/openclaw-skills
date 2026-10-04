# V1.2 架构与取舍

本轮在 V1.1 `ec6ea15f2ec833473bc776cbbb3e7f533ae86373` 上增量开发，分支 `feat/filetools-v1.2`。V1 为 `87f93acad75c7b92a091fe673e67326d6d640143`；检索参考 `623aa73abcd0dc7f4854a58a8a42e8b6c4725072` 不改动。2026-10-04 核对公开远程 V1.1 与基线一致；main 为 `83014f7843f0fe0bcfbf872b3a3cf22c7cbd2d6f`，不能把默认分支当作已经包含 V1.1。

## 职责

通用 `file-workspace` Skill 指导选择工具；10 个真实 `filetools_*` 工具提供管理和处理；Gateway 的固定管理 CLI 负责原件登记、快照、保存、访问标记；一个独立 CPU worker 容器执行 OCR、ASR、提取及临时 Python。继续使用本地 Unix socket HTTP，不新增 MCP、账号系统、网页或管理容器。

核心代码为一份共享源码，Gateway 安装一次无需引擎依赖的管理副本，worker 镜像有一次独立引擎环境；不在每个 Agent 工作区复制代码/虚拟环境。标准库管理入口已用 Python `-I -S` 实测。

```text
可信渠道下载/已授权具体 NAS 文件
  → Gateway 管理 CLI（固定配置、可信 Agent/会话）
  → 实际 Agent workspace/filetools/registry.sqlite + snapshots
  → Unix socket 控制请求（ID/操作/配置，不传原件字节）
  → 单 worker，私有执行 → 回收进程树 → 校验 → 原子发布
  → Gateway 可读产物 → 证据回答/现有渠道交付 → 独立 saved 版本
```

## 实际工作区与映射

每个实际工作区有 `filetools/{snapshots,cache,saved,registry.sqlite}`，另有内部 incoming/.registry.lock。snapshot/saved 至少10类：pdf、word、text、images、audio、video、spreadsheets、datasets、archives、other。MD/TXT 属于 text。分类不是解析支持。

例：宿主 `/root/.openclaw/workspace-chen/filetools`，Gateway `/home/node/.openclaw/workspace-chen/filetools`，worker `/workspaces/chen/filetools`，三者指向同一物理目录。返回的是 Gateway 路径和 `filetools/...` 工作区相对路径。独立控制根只存安装、模型和迁移记录。

每 Agent 独立注册表/目录；main 与 chen 虽兼容同一人，也不合并或跨 Agent 去重。一个全局调度器按排队时间选任务，重任务并发1。运行诊断也取得全局重任务锁，其他 Agent 活动时延期，避免额外加载模型。

SQLite WAL 和文件锁要求本地受支持文件系统；不要把注册表放在 NFS/SMB 等未经验证的网络文件系统。家用 NAS 的 ext4/Btrfs 支持仍须部署实际验证。

## 登记与版本

登记模型只选已配置根及具体相对/绝对本地路径；运行上下文提供 Agent、sender/account、sessionKey/sessionId。来源标签是不可信说明，不能扩展允许根，不能伪造附件到达。URL 不作为本地文件；先走已有下载能力。

snapshot 使用完整 SHA-256，同 Agent 去重并保留接收事件。尝试 reflink，失败流式复制、校验并同步落盘；不用软链接或硬链接做快照。相同请求幂等，相同 request_id 不同版本返回 REQUEST_CONFLICT。

reference 记录 root_id+relative_path、SHA 和版本统计，保持外部原处。查询显示缺失/可能变化；真正使用前校验完整 SHA，变化返回 REFERENCE_CHANGED。普通 workspace 外部引用不默认挂进 worker；需改 snapshot，或管理员显式挂指定 NAS 根。reference 删除只取消登记，不删外部文件。

已发布产物直接登记，mode:artifact；保存的独立版本登记 mode:saved，无重复快照。临时输入为已登记快照或经版本校验的引用。旧 V1/V1.1 布局保留兼容/迁移代码；V1.2 安装必须选 shared-v1.2，禁止把兼容布局当真实工作区。

## 执行和发布边界

Gateway 可执行可信登记/保存管理代码。worker 只挂各 filetools 子树、模型、socket、控制配置和明确的 NAS 只读引用根；不挂整份状态/认证目录。安装渲染后的 Compose 额外检查继承挂载，拒绝意外的 worker 挂载。

生产临时 Python 用 Landlock ABI≥3 和 seccomp；只读本次 `FILETOOLS_INPUT` 及必要运行库，只写本次 `.private/execution`。不授予 snapshots/saved/SQLite/其他 Agent/发布区访问权限，不继承 Gateway 凭据环境。禁止网络、信号攻击、setsid/setpgid 等绕过；CPU/内存/输出/日志/进程数另有限额。

Windows 开发使用内核 Job Object：先挂起、绑定、恢复子进程，始终结束整棵进程树并确认活动数为0。Linux worker 与监督进程作为 subreaper，追踪 /proc 后代、冻结、杀死并定向 waitpid 回收；取消后被收养的僵尸进程也必须消失，回收不完整拒绝确认。原有进程组及父死亡处理保留，Docker部署启用轻量init作为额外回收层。Windows development 模式没有文件/网络隔离，不得生产启用。

程序在子进程回收后验证输出、复制到同文件系统 staging，校验哈希，原子重命名为 published，并登记。不能把跨文件系统复制称为原子移动；不搬走 QQ 下载原件。正文图片使用相对链接，saved 保持整套依赖。sources.json 为可信可更新元数据，其哈希按查询时计算；正文/二进制正式产物保持稳定。

OpenClaw 默认 sandbox off、workspaceOnly 未确认：**工作区不是天然安全边界**。上述隔离只覆盖本工具执行路径，不给既有普通 read/exec 增加全局沙箱。本轮不改变现有工具授权或知识库链路。

## 访问、清理和回滚

成功专用 read 续期；status/未命中/无效读取不续期。已知普通 read/read_file 的可信 SDK hook 在读取前持有5分钟租约，成功后续期并释放；失败不续期。外部 OS/任意 shell 的读取不可自动观测，使用后需协作 touch，不称完整访问审计。长于租约的外部读取需用户/调用方管理访问标记。

72小时默认闲置缓存清理只删终态任务，保护运行/排队任务、读租约及被其他活动任务用作输入的缓存产物。快照/saved/外部原件不自动清理。旧注册表与业务文件迁移保留，回滚代码和容器仍保留新 workspace/filetools 的业务数据。

既有检索/Embedding/索引/私人与 Family 授权导入不变。文件正文不授予永久入库权限。版式转换、完整办公系统等留待后续。
