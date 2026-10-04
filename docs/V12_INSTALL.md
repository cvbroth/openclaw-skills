# V1.2 安装、诊断、迁移与回滚

**本轮只完成开发，没有连接或部署生产。以下是管理员后续执行步骤，不是已执行记录。** 目标 Ubuntu 26.04 x86_64、OpenClaw 2026.9.4/3a9d69d、QQBot 2.0.3、现有 managed Docker 镜像。保留现有检索/知识导入/StockAnalyse 镜像、配置和通信挂载。

## 一份配置和入口

把源码解压到独立管理目录，复制 `deploy/install.v12.example.json` 为操作者配置。确认真实 QQ sender/account/Agent 绑定，管理 Python 路径，以及要启用的 Agent。只配置必要 Agent；没有第二套账号。main/chen即使同一sender，也按可信 Agent 分别绑定和建独立目录。

workspace 优先读取显式映射或现有 OpenClaw agents.entries/agents.list 中的 workspace、main defaults.workspace；缺省时调用目标版 `openclaw agents list --json` 取得 SDK 实际解析位置。仍不能确定返回 AGENT_WORKSPACE_DISCOVERY_REQUIRED，禁止猜成服务自己的目录。示例列出已知 chen 实际路径；可增加 main/liang/ziling 的真实映射。host_workspace 用于离线管理/迁移，在线安装按 Docker bind 实际发现并校对；worker service_root 自动生成。

QQ下载根 kind:media 仅可信到达适配可用，不对模型路径登记开放。具体 NAS 文件根可增加：

```json
"documents": {"path":"/mnt/nas-documents","host_path":"/data/approved-documents","kind":"nas"}
```

这是示例。该根必须是已批准、Gateway 实际可读的具体数据目录；不给 worker 挂 `/`、整份 `.openclaw` 或认证目录。worker只读NAS引用根。NAS上传方必须写 `.part`，关闭并发布最终文件名后才登记；不需要人工 `.ready` JSON。源仍在写入/发生变化时拒绝登记并重试。工具无法替不遵守发布约定的上传程序证明“已经完成”。

## 安装前最少只读检查

在 NAS 上由管理员检查（输出先脱敏，不提交完整配置/环境）：

```bash
docker exec openclaw-openclaw-gateway-1 openclaw --version
docker exec openclaw-openclaw-gateway-1 id
docker exec openclaw-openclaw-gateway-1 /usr/bin/python3 -I -c 'import sys,sqlite3; print(sys.version.split()[0])'
docker exec openclaw-openclaw-gateway-1 openclaw agents list --json
docker inspect --format '{{json .Mounts}}' openclaw-openclaw-gateway-1
docker exec openclaw-openclaw-gateway-1 openclaw plugins list --json
docker info --format '{{.OSType}}'
df -h /root/.openclaw /var/lib
```

必须已有 Python≥3.11 标准库/SQLite；可配置 management_python 到现有路径。缺少时安装返回错误，需要管理员后续更新/准备镜像，本工具不向运行Gateway临时 sudo/pip/apt 安装。确认实际 Gateway 进程与文件 UID/GID，同步核验下列双容器读写；docker exec 的 id 不能替代真实Agent权限验收。检查注册表所在本地文件系统和空闲磁盘。

先只生成计划：

```bash
python3 scripts/filetools_admin.py install --config /path/install.json
```

只读计划发现 Docker/Compose/Gateway 和挂载，不重建容器。Windows/离线本地开发用本地真实路径配置及 `--local-only`；此模式不安装运行时，不等价于生产计划通过。

## 后续安装动作

完成备份并审查计划后，管理员执行：

```bash
python3 scripts/filetools_admin.py install --config /path/install.json --apply
python3 scripts/filetools_admin.py diagnose --config /path/install.json
```

安装只初始化专属 filetools 子树，新目录使用检测到的 Gateway UID/GID，不递归chown既有workspace。存在但所有权不符的 filetools 返回错误供审查，不强制纠正。管理代码只装到共享 release 一次。

安装生成 `data_root/installation/1.2.0/{gateway.json,worker.json,compose.filetools.yaml,rollback.json}`，固定 Gateway CLI入口与各Agent映射。两个运行配置均赋予实际容器 UID/GID、0640 权限。新增 socket/管理源码只读挂载；worker挂每个filetools子树和显式NAS只读根。保留原Gateway image，渲染Compose后拒绝意外继承worker挂载，避免旧override残留导致挂整个状态目录。

plugins.allow 不存在仍不创建；空数组保持空；非空追加 nas-filetools。其他插件 entries/load.paths/工具政策保持，仅移除已确认属于本插件的旧重复load路径。检查安装前后 plugins list 的实际 loaded 状态，不能仅看配置entries或tools.effective预览。安装不会把 message 自动加到既有授权，发送仍需既有合法工具。

生产首次构建固定依赖需要网络；首次small ASR模型下载为固定 revision `536b0662742c02347bc0e980a01041f333bce120`。准备后worker network_mode:none、offline:true、模型只读缓存；RapidOCR wheel自带ONNX模型。不向检索虚拟环境装依赖。基础镜像python:3.12.10-slim-bookworm和系统包有版本tag但未锁digest，后续构建需记录镜像digest/包版本。

初始全局并发1、CPU线程2、容器CPU预算2、内存4GiB、脚本60秒，均按配置限额；详见SUPPORT。NAS同时运行Immich/MySQL/检索，应观察实测负载后调整，不能以本地耗时估算NAS速度。已有worker升级前先取消/结束长任务并保留检查点，不同时运行V1.1/V1.2两个调度器。

重复已记录的生产安装返回 INSTALLATION_ALREADY_RECORDED，先诊断或选择新安装控制根，避免覆盖唯一rollback记录。准备阶段失败未更改Gateway时保留模型/源码供诊断；不要机械删除业务filetools目录。

## 诊断范围

诊断逐Agent检查宿主注册表/容量、Gateway路径与worker路径；生成唯一诊断文件，Gateway写→worker读→worker写→Gateway读，随后删该诊断文件。检查socket、worker实际OCR/模型加载/Python隔离、插件loaded和安装前已loaded的QQ/知识库插件是否仍loaded。只在全局重任务空闲时运行引擎诊断。

诊断文件只位于专属子树，不包含认证/正文。实际Agent调用、正式发布/保存/清理及QQ客户端下载还须执行 [验收清单](V12_ACCEPTANCE.md)。即使 runtime_verified:true，也保留 production_acceptance:PENDING；没有凭QQ真实回执/下载验收就不能声称全流程已可用。

## V1.1迁移

先停旧worker；保留完整V1.1原目录、旧Compose/插件和OpenClaw配置备份。建立显式Agent映射，例如 `{"chen":"chen","main":"main"}`，禁止自动合并/改名。确认host_workspace是宿主真实位置；已安装V1.2时使用生成的gateway映射，离线迁移使用配置中的明确host_workspace。

```bash
python3 scripts/filetools_admin.py migrate-workspaces --config /path/install.json \
  --old-root /var/lib/nas-filetools-v11 --agent-map /path/agent-map.json
python3 scripts/filetools_admin.py migrate-workspaces --config /path/install.json \
  --old-root /var/lib/nas-filetools-v11 --agent-map /path/agent-map.json --apply
```

迁移锁拒绝旧服务正在运行；备份SQLite到控制根migration，按Agent复制独立快照及saved依赖，保留ID/接收来源，逐文件SHA核验，生成业务文件清单。未知Agent返回PARTIAL_MIGRATION+paused_agents，只暂停未明确映射部分，旧文件不删除。目标冲突不覆盖。原文件/保存版本复制本身保留独立备份，旧完整目录是迁移回退来源；额外磁盘级备份由管理员保留。

旧cache/任务留原处供追溯，不伪装成新共享布局下有效任务；新会话select快照重处理。旧音频cache检查点不自动改路径搬迁；停机前有长任务须先处理/保存，后续可在旧worker恢复或新布局重处理。本地迁移已验证saved在删除新快照后仍独立可读。

## 回滚

```bash
python3 scripts/filetools_admin.py rollback --record /var/lib/nas-filetools-v12/installation/1.2.0/rollback.json
python3 scripts/filetools_admin.py rollback --record /var/lib/nas-filetools-v12/installation/1.2.0/rollback.json --apply
```

停止新worker，移去本次增量override，恢复旧插件/配置与原Compose服务；不删新Agent业务目录、模型或迁移备份。若安装后OpenClaw配置又变更，返回 ROLLBACK_CONFIG_CHANGED，需管理员合并备份，禁止覆盖后来的配置。新增业务文件可直接从workspace/filetools/saved取回；重新启用V1.2可沿用其目录/注册表，新业务格式不会自动倒灌进V1.1数据库。

本轮已在本机 Docker Desktop Linux 执行真实引擎、Landlock/seccomp、进程回收及双容器共享文件/socket 测试；Gateway 侧使用管理替身，没有运行生产 Gateway。以上真实 OpenClaw Compose 安装、迁移生产数据、回滚及其实际 UID/GID 效果仍 **待生产验收**。本地配置、真实文件迁移、运行配置权限和测试卷检查不替代这些生产操作。JSON5 配置会明确拒绝，避免丢失注释；管理员需另行准备可审查的 JSON 配置。
