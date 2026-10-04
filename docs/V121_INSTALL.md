# V1.2.1 安装、NAS 输入及 Samba 结果共享

本轮仅本地开发验证。以下命令供管理员未来在 NAS 审查后执行，未替用户执行。沿用 V1.2 插件、单 Worker、共享目录、Unix HTTP 控制、一人一 Agent；没有新增账号、数据库、MCP 或常驻同步服务。

## 升级前核验

1. 核对 OpenClaw 2026.9.4 / QQBot 2.0.3，既有 Compose 项目/服务与配置路径。只用实际 `docker exec <gateway> id` 的 UID/GID，不根据 node 名称猜测。必要时核对 Gateway 主进程与 exec 默认用户是否一致；有差异先诊断，不套用示例。
2. 备份现有安装回滚记录、OpenClaw/Compose/Samba 配置和各 Agent registry.sqlite（暂停写入，SQLite backup API 或在线 backup）。记录快照/saved 内容哈希。main/chen 始终独立。
3. 核对 `docker inspect <gateway>` 的最长匹配 bind，`findmnt -T <saved>`、`namei -l <路径>`、`getfacl -p <saved及样本文件>`，确认实际所有者、可用空间和 POSIX ACL 能力。只读来源可以，登记表/缓存/saved 必须可写。不要递归改变已有工作区或 /root。
4. 新版的管理 CLI 源码和插件需一起升级，不能仅换 Skill。固定 Python/引擎依赖未变化；Gateway 只需已有 Python 3.11+ stdlib/SQLite，不在 Gateway 或检索环境 pip 安装。CPU、重任务并发1、线程2、4GiB Worker 限制沿用可配置值。

```bash
python3 scripts/filetools_admin.py install --config /path/install.json
# 审查计划后：
python3 scripts/filetools_admin.py install --config /path/install.json --apply
python3 scripts/filetools_admin.py diagnose --config /path/install.json
```

配置继续使用 `workspace_layout:shared-v1.2`，参照 [V1.2 安装说明](V12_INSTALL.md)。新 release 为 data_root/installation/1.2.1，旧1.2.0回滚记录保留；安装复制新版 stdlib manager、构建1.2.1 Worker、替换本插件并备份原版。新版本不转换登记表结构，旧活跃附件与历史文件兼容。`--local-only` 仅建立开发目录，不代表 Gateway 安装。重复 apply 同 release 拒绝覆盖回滚记录。

## 个人 Incoming 只读输入

用户在既有个人共享中创建 Uploading/Incoming。先上传 Uploading，客户端确认写入关闭后在同一共享中移到 Incoming，再通知 Agent 具体文件及任务。这是人工发布约定；稳定大小/前后哈希一致不单独证明传输结束。Uploading、.part/.tmp/.crdownload/.download 拒绝；检测到变化要求安全重试/登记新版本。

[compose.nas-inputs.example.yaml](../deploy/compose.nas-inputs.example.yaml) 是 Gateway 的追加 override，需要按真实服务名调整，并纳入既有 Compose 文件列表后重新创建 Gateway。不会直接由 samba-results apply 修改 Gateway。只挂载明确个人 Incoming，示例可只启用一个 Agent；不映射 Uploading、全部 storage、Family、全 OpenClaw 状态。后续 FileTools install 根据这些实际只读 bind 自动发现宿主来源并生成 Worker 相同来源的只读引用挂载。

各 Agent install.json 增加自己根，例如：

```json
"chen": {
  "workspace": "/home/node/.openclaw/workspace-chen",
  "source_roots": {
    "incoming": {"path":"/nas/filetools/chen/Incoming","kind":"nas"},
    "qq_downloads": {"path":"/home/node/.openclaw/media/qqbot/downloads","kind":"media"}
  }
}
```

liang→自己的liang路径，ziling→azl路径；不要把三个人的根填入同一个 Agent。`host_path` 可省略，由实际 bind 发现；显式填写则需管理员核对。Family 只有另行明确授权才配置。Gateway 自身是可信服务进程，FileTools 按 Agent 根检查并不宣称构成完整 OS 多租户安全平台。

只读挂载不授予 Linux 读取权。管理员应检查 Incoming 原件及路径的 ACL，让实际 Gateway/Worker UID 对指定个人 Incoming 有读取/遍历权，Samba 用户仍有上传/发布权限。可在明确 Incoming 上设置该服务 UID 的 access/default ACL，逐项检查上传后文件实际 ACL 掩码（Samba/客户端 chmod 可能缩窄）；不要通过广泛组、force user、开放 /root 或整树 chmod777 解决。此修订不自动改既有个人共享的 ACL/认证。用容器真实 UID 读取一份已发布测试文件验证，不能只用宿主 root 的 cat 判定可用。

Agent 调 `filetools_register({source_root:"incoming",source_path:"report.pdf",mode:"snapshot"})`。快照独立占空间、同 Agent SHA 去重；reference 不复制长期原件，但每次使用校验完整版本，后续处理可能有临时解码/工作副本。文件存在不等于内容支持；不移动原件、不自动入库。删除 reference 只取消登记。

## 可选 Samba saved 入口

核心 FileTools 不强制安装 Samba。复用 NAS 已有 Unix/Samba 用户 chen、liang、azl，不创建账号，不读取密码；azl→ziling，main 默认无结果共享。

[samba-results.example.json](../deploy/samba-results.example.json) 中 saved 必须是实际已初始化的 `filetools/saved`，不能误填 cache 或整个workspace。CLI 基于 pwd 查真实账号 UID，与 saved 的实际所有者 UID 比较，不猜 UID，不允许 root 共享账号。计划不创建文件/挂载/ACL，不连接 Docker、Gateway 或生产网络。

两种模式自动选择并写入计划及 `results-rollback.json` 的每个 share：

- `owner_samba_readonly`：账号 UID 等于 saved 所有者（例如已核实的 Gateway/chen UID 1000）。保留保存区现有权限和 ACL，不给所有者添加只读 ACL。Samba 访问只读，服务器本地所有者仍可写。
- `reader_acl`：账号 UID 与 saved 所有者不同，沿用指定读者只读 ACL，保留 FileTools 服务所有者写入权限；需要 POSIX ACL 支持。

不改变 Gateway 用户，不递归 chown/chmod 工作区，也不扩大其他目录权限。同 UID 时，知道同一 Unix 身份的本地进程仍受原所有者权限控制；Samba 只读并不构成服务器本地所有者的写入隔离。

```bash
python3 scripts/filetools_admin.py samba-results --config /path/results.json
sudo python3 scripts/filetools_admin.py samba-results --config /path/results.json --action apply --apply
sudo python3 scripts/filetools_admin.py samba-results --config /path/results.json --action diagnose
# 自己既有 smbd 服务的管理方式核实后，管理员显式 reload：
sudo systemctl reload smbd
```

apply 只做以下修改：

- 仅在 `reader_acl` 模式给 explicit saved 树安装“服务所有者原权限 + 指定用户只读/遍历”的 POSIX ACL，group/other不获额外访问。该模式旧文件须为同一个已核验写入 UID，已有自定义 named ACL/所有者不一致要求人工审查，不自动覆盖。`owner_samba_readonly` 不修改保存区 ACL，包括原来已有的自定义 ACL。锁住现有 `.registry.lock` 与保存操作协调；两种模式都限制树检查为100000节点。
- 以 bind 在 `/srv/storage/results/<user>` 暴露同份 saved 数据，绕开 /root 路径遍历，不放宽 /root。既有 results 根不改权限；若其上级不可遍历，diagnose 报 Unix access 失败，管理员仅审查该公共入口祖先权限。
- 创建自己的 systemd `.mount` 单元，`RequiresMountsFor=原saved`、`Before=smbd.service`、启用 local-fs.target。首次目录不存在则拒绝，重启后挂载/失效需 diagnose；不覆盖现有入口或单位，不叠加未知 mount。
- 私有 state_dir 保存配置片段与权限/配置备份，末尾新增自己的 `[global]` include。`valid users`、`read only=yes`、`guest ok=no`；本共享显式清空继承的 write list/admin users/force user/force group，不借既有全局特权覆盖只读身份。隐藏并禁止访问未完成 `.saving-*`、`.migration-*`、`*.tmp-*`。testparm 校验前后配置，原来的个人/Family 共享不改。

bind 本身不复制也不改变所有者，不把 Worker 原 saved 入口整体 remount成只读。两种模式都依靠 Samba 配置禁止上传、覆盖、删除、重命名；不同 UID 还由读者 ACL 限制 Unix 写入。发布器忽略 named-owner 读者条目，没有非所有者读者默认 ACL 时保持原发布行为；有读者时在独立版本、chmod0440/0600及最后原子 JSON 替换后修复 read ACL/掩码。运行时用 Python stdlib xattr，不需要临时安装 setfacl。测试边界见 [UID 修复报告](V121_SAMBA_UID_FIX.md)；NAS 实际 FS、systemd 启动及账号仍待验收。

同配置重复 apply 核验身份/权限模式、mount、单位和配置哈希；仅不同 UID 模式检查读者默认 ACL。返回 RESULTS_ALREADY_APPLIED；UID/模式变化报 RESULTS_IDENTITY_OR_PERMISSION_MODE_CHANGED，不自动切换策略。旧 V1.2.1 未记录模式的已安装 share 按 reader_acl 兼容，无数据迁移。系统修改中失败会按记录尝试回滚，保留 saved。若系统命令失败或后续管理员改过配置，保留回滚记录并报告，不覆盖后续变动。

diagnose 两种模式检查账号读取/遍历 bind 入口；不同 UID 额外检查 Unix 不可写，同 UID 保留本地所有者权限并明确报告上述区别。diagnose 不读取密码、不代表真实 SMB 操作已通过。管理员必须用实际账号运行下载及四种写操作拒绝检查，错误账号亦不得进入；见修复报告中的部署后清单。

## 回滚及迁移

先暂停新保存请求，若启用了 Samba 先撤销结果共享，再回滚 FileTools 代码。旧 V1.2 发布器不修复新文件 ACL 掩码，不能保留 Samba ACL 却回到旧发布器并宣称新结果持续可读。

```bash
sudo python3 scripts/filetools_admin.py samba-results --config /path/results.json --action rollback
sudo python3 scripts/filetools_admin.py samba-results --config /path/results.json --action rollback --apply
sudo systemctl reload smbd
python3 scripts/filetools_admin.py rollback --record /DATA/installation/1.2.1/rollback.json
python3 scripts/filetools_admin.py rollback --record /DATA/installation/1.2.1/rollback.json --apply
```

Samba rollback 核对身份/权限模式、配置、自己的单位及挂载来源。仅 `reader_acl` 恢复旧 saved ACL/模式并移除新结果的本功能 ACL；`owner_samba_readonly` 不改新旧文件 ACL 或所有者权限。恢复原 smb.conf，仅卸载自己的入口/单位、空目录。不删除任何 saved、原件、registry、缓存、账号或隧道；保存回滚审计记录。后续改过smb.conf则拒绝自动覆盖，需审查后只移除本功能include。再次部署使用新 state_dir 保存新回滚记录。

若卸载返回busy或systemctl暂时失败，关闭客户端对本结果共享的打开文件，按同一record/config重试rollback。已恢复到准确原配置/已撤销的单位和入口可续作，非本功能配置/片段修改仍拒绝覆盖；不用lazy/force卸载隐藏活动访问。若卸载失败，尚存ACL/挂载应按diagnose检查，不能先删除源saved。

FileTools rollback 恢复上次插件/OpenClaw/Compose，保留全部业务数据。V1.2→V1.2.1 无数据迁移，catalog-only 复用已有 attachments.active=0，不修改 Schema；这些目录文件回到旧插件后仍能 list/select（旧工具无法继续新增select:false）。V1.1 迁移仍用旧文档的明确 Agent 映射，不能合并 main/chen。回滚自己的 NAS 输入 override 时只撤销新增个人 Incoming bind，再核对旧 Compose 和知识库插件仍工作。
