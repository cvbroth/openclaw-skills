# V1.2.1 Samba 同 UID 修复交付报告

## 范围与基线

开发基线：`69c194c57314e162997591340b7e5bbd3f9b2e93`，开发分支 `fix/filetools-samba-owner-uid`。本报告与代码、测试在同一小补丁提交中，最终提交号以该分支 `git log -1` 及交付清单为准。

仅开发机 Windows / Docker Desktop Linux 测试，没有连接或部署生产，也没有修改 Gateway、检索、导入链路。生产 Gateway/chen UID/GID 1000 是用户提供的已核实条件；生产 Ubuntu 26.04 / OpenClaw 2026.9.4 的实际 Samba 版本、文件系统 ACL、账号及共享均未在本轮访问。

包版本保留 1.2.1，不修改数据库或工具接口。插件、Skill、引擎、依赖版本、运行用户及资源配置没有改变。修复入口仍为 `scripts/filetools_admin.py samba-results`，普通 Agent 不取得管理员权限。

## 实现与取舍

| 权限模式 | 安装 / 新结果 | diagnose | 回滚 |
|---|---|---|---|
| `owner_samba_readonly`，账号 UID = saved 所有者 UID | 不改保存区权限/ACL，不给所有者加读者 ACL | 检查 r/x，允许本地可写；报告“Samba 访问只读，服务器本地所有者仍可写。” | 不恢复、删除或缩减任何新旧保存区 ACL/所有者权限 |
| `reader_acl`，两个 UID 不同 | 保留旧读者 ACL、原子 JSON 与新版本 ACL 掩码修复，服务所有者保留写权限 | 检查 r/x 与 Unix 不可写 | 沿用旧文件权限恢复及新结果读者 ACL 撤销，文件不删除 |

每个 share 在 plan、rollback plan 和安装记录中包含 `permission_mode`、读者 UID 与所有者 UID。重复 apply 按模式检查身份、挂载、单位、配置与必要读者 ACL；UID/模式变化拒绝自动切换。旧记录缺少模式时按 `reader_acl` 解释，兼容旧安装/回滚。

同 UID 与不同 UID 都保持 `valid users`、`read only = yes`、`guest ok = no`，并显式清空继承的 `write list`、`admin users`、`force user`、`force group`。diagnose 使用 testparm 查询各共享**实际有效值**，漂移报告 `RESULTS_SAMBA_POLICY_CHANGED:<agent>`。它不带密码运行 SMB 请求，明确返回 `smb_protocol_acceptance:NOT_RUN`，不能替代账号操作验收。

发布器忽略属于文件所有者的 named-reader UID，仅有非所有者 r-x 默认读者条目时修复新结果；没有读者 ACL 时保留原发布行为。现有非所有者默认读者 ACL 仍作为原有管理员读者配置，未改成新的权限数据库。`reader_acl` 模式仍拒绝自动覆盖既有自定义 named ACL；同 UID 模式保留这些 ACL。

不递归 chown/chmod 工作区，不放宽 /root 或其他目录，不改变 Gateway 用户。同 UID 共享依靠 Samba 协议层只读，具有相同 Unix 身份的服务器本地进程仍有原所有者权限；这是两种模式的必要区别，不宣称新增本地用户隔离。

## 本轮测试与证据

| 类别 | 结果 | 边界 |
|---|---|---|
| 静态 | Ruff src/tests/scripts、git diff --check 通过 | 不代表生产行为 |
| Windows 目标回归 | 24 通过 / 15 跳过，43.12 秒 | V1.2.1 / V1.2 / 管理操作测试；Linux 专属项跳过 |
| Linux 全量核心回归 | **91 通过 / 15 跳过，74.69 秒** | 非 root UID10001，本次未开启 OCR/ASR 实际模型测试 |
| 实际 Samba 集成 | **4 通过，9.12 秒** | 两种模式的完整共享流程与失败回滚；真实 smbd/smbclient、testparm、bind mount、Unix ACL、runuser |
| systemd / 故障模拟 | systemctl 调用替身；mount 失败与 busy umount 注入通过 | 没有真实 systemd 开机/服务重载测试 |
| 生产端到端 | **待验收** | 未连接 NAS/QQ/Gateway/远程客户端 |

真实 Samba 环境为 Debian Bookworm 本地一次性测试容器，Samba 4.17.12，网络 `none`，只用容器内部 loopback，没有宿主端口、生产目录或 Docker socket。镜像里 chen 实际 UID/GID1000（测试有断言）；不同 UID 时写入者 filetools 为10001，同 UID 时写入者为对应 Samba 用户。chen/liang/azl 三个随机测试账号均参与交叉拒绝检查，密码只在临时0600文件中存在，不输出日志。

两种模式都实际验证了：旧结果下载、新 content.md / 原子 saved.json 下载、账号上传/覆盖/删除/重命名四种操作返回 ACCESS_DENIED、所有错误个人账号不能进入其他共享、全局写/强制身份特权未继承、重复 apply、回滚及重复回滚、旧新数据保留。chen 另执行真实登记 → CPU 纯文本 Worker → save → SMB 立即下载。不同 UID 原子 JSON 第二次发布仍可读；同 UID 本地写入成功，预先存在的 named-owner 与自定义 group ACL 在安装和回滚中保持；回滚对所有新旧结果的权限/ACL逐项比较。

还覆盖：UID/模式漂移，旧安装记录无模式兼容，Samba readonly 配置漂移，后续配置/片段编辑保护，busy 中断后的回滚续作，以及两个模式的安装失败回滚。失败命令属于明确注入，不宣称发生真实 NAS 故障。

证据：[Samba](evidence/samba-owner-uid-real.txt)、[Linux 全量](evidence/samba-owner-uid-linux-regression.txt)、[静态](evidence/samba-owner-uid-static.txt)、[实际测试环境](evidence/samba-owner-uid-environment.txt)。各运行有重叠，不累加为独立总数。仅出现既有 PyMuPDF SWIG 废弃提示，无失败。OCR、ASR、真实 OpenClaw/QQ、知识库接口本轮没有重测；相关代码未变，旧版报告是历史证据。

### 本地复现

仓库目录下，已按原文档构建固定依赖基础/测试镜像后：

```powershell
docker --context desktop-linux build -f deploy/Dockerfile.samba-test -t nas-filetools-samba-test:owner-uid-fix .
docker --context desktop-linux run --rm --privileged --network none -e FILETOOLS_SAMBA_TEST=1 -e PYTHONPATH=/opt/nas-filetools-check/src -v "${PWD}:/opt/nas-filetools-check:ro" nas-filetools-samba-test:owner-uid-fix -m pytest /opt/nas-filetools-check/tests/test_v121_samba.py -q -p no:cacheprovider
docker --context desktop-linux run --rm --network none -e PYTHONPATH=/opt/nas-filetools-check/src -v "${PWD}:/opt/nas-filetools-check:ro" nas-filetools-test:1.2.1 -m pytest /opt/nas-filetools-check/tests -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check src tests scripts
.venv/Scripts/python.exe -m pytest tests/test_v121.py tests/test_v12.py tests/test_v12_operations.py -q
git diff --check
```

privileged 仅用于一次性容器内真实 bind mount，生产 Worker 不增加权限。重建的 Samba 测试镜像把测试 chen UID/GID设为1000，不修改 NAS 账号。旧测试镜像的 chen24001不满足当前精确UID断言，应重建。

## 安装、迁移与回滚（管理员未来执行，本轮未执行）

首次安装沿用 [安装文档](V121_INSTALL.md)。若已安装1.2.1，这是同版本补丁，**不能直接重复 install --apply**：旧安装器会拒绝覆盖 `installation/1.2.1/rollback.json`。无需数据库迁移，也不要删除该记录或重新初始化工作区。

对已安装版本采用最小代码更新：

1. 暂停新的保存请求、等在途保存完成。保留现有安装/Samba记录、Compose文件、Worker旧镜像ID和 manager 文件备份。确认实际 `manager` 宿主路径是现有 `/opt/nas-filetools-management:ro` bind 的源目录，不能按猜测路径操作。
2. 宿主管理员 CLI 从本补丁仓库执行。已部署的 manager 只需替换 `src/nas_filetools/saved_permissions.py`；先备份它，核对目标为现有普通文件而非链接，写入新内容时保留目标 inode、所有者与模式。管理调用为独立 Python 进程，后续调用加载新版模块。不要向 Gateway pip 安装或更换其运行用户。
3. 如 Worker 已安装，按原 Dockerfile 构建**独立新镜像标签**（例如 `nas-filetools:1.2.1-samba-owner-uid`），以仅覆盖 `nas-filetools.image` 的追加 Compose 文件更新现有 Worker。审查合并 `compose config` 后只重建该服务（`up -d --no-deps nas-filetools`），保持已有 user、挂载、CPU/内存/线程/超时。不用覆盖旧标签或重建 Gateway。保留追加文件供回滚。
4. 执行核心 diagnose，再按下面入口生成结果共享计划、审查后应用/诊断。新同 UID 共享选用未使用的 state_dir；旧不同 UID 已安装共享可沿用其记录，重复 apply 验证兼容。Samba reload 按服务器已有服务管理方式显式执行。

```bash
python3 scripts/filetools_admin.py diagnose --config /ACTUAL/install.json
python3 scripts/filetools_admin.py samba-results --config /ACTUAL/results.json
sudo python3 scripts/filetools_admin.py samba-results --config /ACTUAL/results.json --action apply --apply
sudo python3 scripts/filetools_admin.py samba-results --config /ACTUAL/results.json --action diagnose
```

`/ACTUAL` 是待核实路径占位符；保留原 results JSON，不新增模型可指定的用户/路径参数。错误 `RESULTS_IDENTITY_OR_PERMISSION_MODE_CHANGED` 表示账号或 saved 所有者与记录不同，应人工核对，不能递归 chown 来强行通过。

撤销时先暂停保存、**用本补丁 CLI 撤销同 UID Samba 共享**，旧69c194c CLI会拒绝同UID，不能先回退代码再撤共享：

```bash
sudo python3 scripts/filetools_admin.py samba-results --config /ACTUAL/results.json --action rollback
sudo python3 scripts/filetools_admin.py samba-results --config /ACTUAL/results.json --action rollback --apply
```

核对结果、显式 reload 原 smbd。再恢复备份的 manager 模块，撤销仅镜像标签的追加 Compose 文件，按原文件列表恢复旧 Worker 镜像。核对新旧 saved 哈希、模式及ACL，随后恢复请求。没有数据迁移，不回退或删除数据库。若只撤共享而保留修复代码，数据仍保留；已回滚记录用于审计，再安装需新 state_dir。busy时关闭相关共享文件后按同记录重试，不强制/lazy卸载。对后来修改的配置保持拒绝自动覆盖。

## 生产待验收清单

以下全部**待验收**，本地通过不能代替：

1. 记录真实 Samba 版本、现有共享全局参数、saved 所有者、公共 bind 入口祖先 r/x、实际文件系统 ACL，以及备份/空间。确认生产 chen 模式为 owner_samba_readonly，保持 Gateway/Worker UID/GID1000。
2. 用对应真实 Samba 账号下载一份旧结果及刚通过 FileTools 保存的新版本（含 JSON/图片），比对文件哈希；确认 Gateway/Worker仍能本地保存。另选实际不同 UID 共享核对 reader_acl 与 Unix不可写，若当前未配置此类账号则记录该模式生产未执行，不新增账号只为验收。
3. 在专用验收结果上尝试上传新文件、覆盖已有文件、删除、重命名，四项都应拒绝；错误个人账号和guest不能进入。可用交互式 smbclient 提示输入密码，不把密码放命令行/报告。下载成功或 ls 成功不能代替写拒绝。
4. 重复 apply 不叠挂载；真实 smbd reload / systemd 开机持久挂载正确。模拟源丢失/后续配置变动前先备份，确认诊断；实际生产 systemd 测试本轮未做。
5. 先撤共享再回退代码，所有旧新文件仍在。同 UID 逐项核对安装前及回滚前的 mode/ACL均未缩减；不同 UID 恢复旧 ACL且新结果保留。原个人/Family/隧道、知识库不受影响。
6. Windows/macOS/iPhone及既有远程通道下载验收、真实QQ保存结果流程仍待执行。本补丁不调整私聊/群聊策略。

尚需实际 Samba/文件系统信息、确认后的 results/install 配置路径及现有部署记录来安排生产验收；这些信息不阻塞本轮源码交付。
