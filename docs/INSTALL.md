> 这是87f93ac交付的V1历史记录，限额/接口不代表当前V1.1。当前说明见 [V11_INSTALL](V11_INSTALL.md)。本轮远程CI未执行，不能将历史或已编写工作流视为V1.1 CI通过。

# 安装、资源控制与回滚（部署草案，未执行）

本轮仅开发。生产为 Ubuntu 26.04 x86_64 / OpenClaw 2026.9.4（3a9d69d），Gateway 容器 openclaw-openclaw-gateway-1，镜像 stockanalyse-openclaw-managed:latest；**不在运行容器或既有检索环境执行 pip install**。推荐新增独立 filetools 宿主服务，或另一个 CPU worker 容器；先通过测试机验证后再由用户批准生产部署。

## 准备与安装

1. 记录当前生产 Git commit、镜像 digest、Gateway UID/GID、OpenClaw/QQ 插件版本、工具 allow/deny、既有 knowledge 插件配置和挂载清单。只记录白名单字段，避免带出凭据/全文环境变量。确认 canonical sender、account、direct session、sessionId 及公开会话存储只读访问 在实际 QQ 通路存在。
2. 在新路径 `/opt/nas-filetools` 检出本分支提交；为此服务创建非 root 的 nas-filetools 用户，确认专用 socket 组可由 Gateway 访问。示例 openclaw 组名必须以真实 GID 为准；stockanalyse 容器已有用户/服务不改变。
3. 使用 Python 3.12 专属环境。Ubuntu 的发行版 Python 版本如果超出支持范围，用独立受管理 Python 3.12 或 worker 镜像，不能假设系统 python3 符合约束。

```bash
cd /opt/nas-filetools
python3.12 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock.txt '.[engines]'
.venv/bin/python -m pip check
ffmpeg -version
ffprobe -version
```

宿主服务另安装 Ubuntu 提供的 FFmpeg/ffprobe，记录包版本；Dockerfile 基础为 Python 3.12.10 bookworm，构建安装 FFmpeg。`requirements.lock.txt` 是实测精确约束，Linux 安装仍需检查平台 wheel；不要宣称只在 Windows resolve 就已验证 Ubuntu 部署。记录最终镜像 digest、pip freeze、ffmpeg 版本，再固定镜像。

4. 显式预下载模型，不在首个用户任务中自动拉取。联网准备环境可执行：

```bash
.venv/bin/python scripts/prepare_models.py --model small --cache /var/cache/nas-filetools \
  --revision 536b0662742c02347bc0e980a01041f333bce120
```

记录生成的 model-manifest；将 downloaded snapshot 的绝对路径写入 whisper_model。模型缓存归 worker 用户可读，运行 `offline:true`。在实际 worker 身份下验证无网络仍可加载。RapidOCR 模型已随 pinned wheel 提供；记录包和模型文件散列可作为部署证据。模型不要下载到 Gateway 或检索 `.venv`。

5. state 使用本地可靠锁/fsync 的专属目录 `/var/lib/nas-filetools`，worker 所有、0700；配置 `/etc/nas-filetools/config.json` 管理员所有，仅服务可读。socket 目录 `/run/nas-filetools` worker 所有、专用组、0750；socket 0660。原件/缓存不挂给 Agent。根据 NAS 共享负载初始使用 deploy/filetools.example.json 的并发 1、线程 2、超时 3600、检查 15 秒；RLIMIT_AS 4 GiB 虚拟空间与整体 MemoryMax 4 GiB 实际内存都需要真机验证。出现模型内存失败时依据记录调整，不能无记录地无限制运行。

## 宿主 systemd 或独立容器二选一

systemd 样例：deploy/nas-filetools.service。安装 unit、配置并检查权限后再启用；整体 CPUQuota=200%、MemoryHigh=3G、MemoryMax=4G，与 Immich/MySQL/检索共享机器时先监测真实 RSS、I/O、延迟再调。KillMode=control-group 控制 ffmpeg/模型进程退出。worker_memory_mb 控制单子进程虚拟地址空间，必要时可独立调整；不要把 RLIMIT_AS 当成 RSS 指标。

容器样例：deploy/Dockerfile / compose.example.yaml，只增加 worker，不替换 stockanalyse/Gateway Compose。设置真实 FILETOOLS_SOCKET_GID，预建目录给 UID 10001 与专用组；snapshot 缓存只读，network_mode:none，cpus=2，mem_limit=4g、pids_limit=96，无 GPU/特权/Docker socket。预下载在容器启动前完成。Docker/systemd 与 Linux 子进程内存限制在本轮开发机未实测，待验收。

将 `/run/nas-filetools:/run/nas-filetools:ro` 加到 **Gateway 原有 Compose 的增量覆盖**，只让它访问服务 socket；保留原 query/import/session-document sockets 和其他挂载，不加入 state/原件/Source/Inbox/Embedding 数据路径。容器重建/Gateway 重启属于后续生产部署步骤，本轮不执行。宿主独立服务避免强耦合到 stockanalyse image。

## 插件和 Skill

插件目录 integrations/openclaw-filetools；在独立 Node 24.16 开发/打包环境：

```bash
npm ci --ignore-scripts
npm test
npm run plugin:build
npm run plugin:validate
```

使用 **2026.9.4** 的插件安装/本地路径加载流程，运行 `openclaw plugins install <插件目录>` 前检查该版本 `--help`，不替换/升级运行 Gateway 的依赖。随包携带 src、manifest、Skill 和 production typebox 依赖，OpenClaw 由 Gateway 提供；安装包不要携带开发用完整 OpenClaw/node_modules。插件实际入口 src/index.mjs，不是不存在的脚本或仅文档工具。

在现有 OpenClaw 配置内**增量合并**插件 allow/entry 与所需 Agent 工具策略（不要覆盖 knowledge_*）：

```json
{
  "plugins": {
    "entries": {
      "nas-filetools": {
        "enabled": true,
        "config": {
          "bindings": [
            {"user_id":"chen","agent_id":"chen","channel_id":"qqbot","account_id":"default","sender_id":"<真实可信 QQ senderId>"},
            {"user_id":"liang","agent_id":"liang","channel_id":"qqbot","account_id":"default","sender_id":"<真实可信 QQ senderId>"},
            {"user_id":"azl","agent_id":"ziling","channel_id":"qqbot","account_id":"default","sender_id":"<真实可信 QQ senderId>"}
          ]
        }
      }
    }
  }
}
```

main 仅按真实 chen 身份另行绑定。unknown/重复绑定拒绝；不把群 ID、QQ 昵称、模型说的名字当 senderId。实际 account_id 不能盲用 default。Skill 由 manifest 的 `./skills` 加载；旧 filetools Skill 仅是遗留手动脚本，优先使用新 filetools-session，避免同附件重复运行。

注册后检查插件 runtime inspection 与三个 Agent 可见工具，再实际通过 QQ 私聊上传，验证所有可信字段。构建/manifest 成功不等于渠道 Hook 已触发。若身份字段/会话 run 关联缺失，失败封闭，不以聊天路径/legacy metadata 替代。启用前还须核对真实 Gateway arbitrary exec 权限，V1 的逻辑隔离不能抵御同 UID 任意代码绕过 socket。

## 回滚

1. 增量禁用 nas-filetools entry、移除新增 filetools_* allow 列表/Skill（保留既有 knowledge 工具及 document-extract）。恢复之前保存的插件/工具配置和 Gateway Compose 的 socket 增量挂载；按原流程重建 Gateway。
2. 停止/禁用独立 worker 服务或移除 worker 容器。不要卸载检索依赖、不要回退永久库数据库或运行 ingest。
3. 保留 `/var/lib/nas-filetools`、原件快照与模型缓存；按任务私有日志核对 INTERRUPTED/失败状态。需要恢复时使用同一版本与相同映射/权限启动，RUNNING 中断任务不会伪装成完成，QUEUED 可恢复。
4. 本 V1 没有修改永久 schema/index，因此不需要数据库迁移回滚。清理临时任务用停止服务后的 `nas-filetools cleanup --root /var/lib/nas-filetools`；**不删除 originals**。原件归档/删除是单独管理员政策，不提供模型侧删除入口。
