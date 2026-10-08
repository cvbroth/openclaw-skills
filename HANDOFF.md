# FileTools 服务器开发交接

> 服务器接手后的增量状态见第9节；下文第1–8节保留原交接时点的记录。“待验收”须结合第9节解释，不能将历史描述覆盖后续用户提供的真实验证。

交接日期：2026-10-05（Asia/Shanghai）。本轮仅核对、文档和 Git 交接，不扩大开发、不连接或部署生产、不修改 Gateway/Samba/检索服务。交接完成后原 Windows 环境停止推进；服务器接手同一任务，避免两个环境并行修改。

## 1. 仓库与提交状态

- 开发仓库：<https://github.com/cvbroth/openclaw-skills>，`origin` fetch/push 均为 `https://github.com/cvbroth/openclaw-skills.git`。
- 本地仓库：`C:/Users/18296/Documents/Codex/2026-10-03/nas-openclaw-v1-https-github-com/work/openclaw-skills`。
- 交接独立分支：`handoff/filetools-server-20261005`，从 `36dfb1a1dc4292d2912396940721de3328350c73` 创建；最终交接提交号以 Git 分支及发送方交付的完整 SHA 为准（本文随该提交发布，不自引用自己的 SHA）。
- 交接前当前分支：`fix/filetools-samba-owner-uid`；未提交/未跟踪改动为空。交接只增加本文件，不重新修改已完成代码，不提交虚拟环境、模型或无关文件。

以下于交接当日通过实际 `fetch` 和 `ls-remote --heads` 核对，**已在 GitHub**，不是仅本地成果：

| GitHub 分支 | 完整 SHA | 成果 |
|---|---|---|
| `main` | `83014f7843f0fe0bcfbf872b3a3cf22c7cbd2d6f` | 原仓库基线，未合并本开发任务 |
| `feat/filetools-v1` | `87f93acad75c7b92a091fe673e67326d6d640143` | V1 统一临时附件处理 |
| `feat/filetools-v1.1` | `ec6ea15f2ec833473bc776cbbb3e7f533ae86373` | V1.1 持久 Agent 工作区 |
| `feat/filetools-v1.2` | `e3ba3db219d1a133971bc78dee1aeea9d8635930` | V1.2 共享工作区、安全发布 |
| `fix/filetools-v1.2.1` | `69c194c57314e162997591340b7e5bbd3f9b2e93` | V1.2.1 登记/来源/Samba 及中断回滚修订 |
| `fix/filetools-samba-owner-uid` | `36dfb1a1dc4292d2912396940721de3328350c73` | 同 UID Samba 只读共享小补丁，交接代码基线 |

交接提交在本文编写时尚未推送；提交后仅推送新交接分支，发送方会核对远端 SHA 并在最终回复报告成功或失败，不合并 main、不强制推送。旧报告中的“本轮未推送”描述其历史交付时点，以本表的当日远端核对为准。

参考检索仓库：<https://github.com/cvbroth/vector-search-engine>，本地接口核对基线 `623aa73abcd0dc7f4854a58a8a42e8b6c4725072`，工作区干净；本轮不修改或推送它，不把该基线称为当前远端最新版本。

## 2. 原目标与接受的边界

OpenClaw 接收 PDF/Word/图片/音频等附件后，通过真正注册的工具登记、检查、后台处理、按来源读取并回答。原件保留，任务输出独立；完整/部分/失败、覆盖、页码/时间段及警告必须可区分。文件正文是不可信数据，不能获得权限、跨 Agent 身份或永久入库授权。

沿用**一人一 Agent**，main/chen 不合并；实际工作区 `filetools/{snapshots,cache,saved,registry.sqlite}`。可信运行时提供身份/会话，模型不能指定其他用户/Agent/登记表路径。当前群聊保守拒绝，不扩展复杂用户系统、完整办公平台、新 MCP/同步服务或网盘 UI。

固定管理 CLI 在 Gateway 用 Python 标准库，重任务在独立 CPU Worker，全局重任务并发1。Unix socket HTTP 控制、共享文件子树，不二次传输原件；不向既有 Gateway/检索虚拟环境临时 pip 安装。线程、内存、超时可配置，默认线程2、Worker4GiB，测试须控制与共用服务的资源争用。

snapshot 按同 Agent 完整 SHA 去重并保留接收来源；reference 保留外部原件，每次校验版本，只取消登记不删除外部文件。NAS 来源只开放明确个人根；Uploading → Incoming 是用户显式完成上传约定，稳定大小不等于上传完成。登记目录不自动移动原件、提取或提高32个会话活跃附件额度。

cache 默认闲置72小时清理，保护活动任务/输入；已授权的 snapshot/saved 不自动删除。临时产物不自动进入永久知识库，现有数据库、Embedding、搜索算法及私人/Family 授权导入不变。文档生成/尽量保留版式转换仍是后续路线图，不能冒称完整实现。手写、公式、照片画面、复杂表格/多栏/OCR完整还原无可靠支持承诺。

## 3. 已完成与仍待完成

已完成且在当前代码基线中：

- PDF按页直接提取/OCR、DOCX正文顺序与图片保留、MD/TXT、印刷图片OCR、带片段时间音频转写；任务/结构化来源/状态/取消/分段读/关键词定位、覆盖与失败记录。
- 可信登记、背景任务、重启明确状态、幂等、租约/清理/隔离、共享工作区管理、受限临时 Python、正式输出核验、授权 saved 独立版本与原件保留。
- 2026.9.4 SDK 注册10个 `filetools_*` 工具；入站回执、pending/错误/重试、受限完整JSON分页；实际消息交付复用既有渠道，路径本身不代表已送达。
- 保存原转写与派生纪要分离；可选 NAS Incoming 输入与 saved-only Samba 计划/安装/诊断/回滚。
- 最新同 UID 补丁：`owner_samba_readonly` 不改保存区ACL/所有者权限，Samba只读；不同 UID `reader_acl` 修复保留。记录模式，重复安装/漂移/诊断/回滚按模式处理。保持 valid users/readonly/no guest，并清空继承的 write list/admin/force身份。

接手后的未完成项（不是本次交接新增开发授权）：

- 在**隔离的服务器测试环境**重跑基线，确认 Linux/FS/CPU/依赖及模型缓存，不触碰共用生产容器/目录/端口。当前 Windows/Docker 结果不能作为服务器实测。
- 真实 Ubuntu NAS 文件系统ACL、Samba版本/账号、systemd开机挂载/服务重载；真实 OpenClaw daemon/QQ附件到达 → 工具调用 → 发出结果 → 客户端下载；全是待验收，需明确测试实例与生产边界后再执行。
- 中文真实录音、长录音/4小时、4GiB完整传输、大型OCR、复杂文档及服务器共用服务资源峰值；尚无用户匿名真实样本。
- 录音 Skill 专节的完整指令（下节）、遗留 Skill 名称提示核对，不能把计划写成已更新。用户另行确认后才进入后续修改；当前交接不改 Skill。
- 参考检索 Python 全量缺独立测试依赖导致未完成；不修改其生产环境来绕过缺口。GitHub Actions 当前状态本轮未核查，不把分支推送等同 CI 通过。

## 4. 必须保留的录音流程及 Skill 实际状态

接受的流程约束：

1. 录音先按明确范围转写，保留原始 `transcript.md`、片段与起止时间、引擎/配置/覆盖/失败/警告；后续大模型不得把改写、猜测或补全写回原转写。
2. 大模型基于转写证据另行整理纪要/要点，派生产物独立，记录对应 source_segments；派生内容标为未经核实，不能把整理后的说法倒写成原话。
3. 听不清、专名/数字/否定词冲突或其他疑点，以时间戳/时间范围和原片段列出，交人工听原音确认；不编造、默默纠正或把推断当识别原文。人工更正亦应独立留来源，原始引擎转写保持。
4. 未经授权不把转写/纪要移入永久 `saved`，不导入知识库。原件 snapshot 的登记保留策略与“永久保存处理结果”是两件事；用户要求纪要只授权临时派生，不自动授权长期保存或私人/Family 入库。

**当前 Skill 完成到哪一步**：`integrations/openclaw-filetools/skills/file-workspace/SKILL.md` 已写登记→按范围提取→查询→来源读取，音频时间引用，`filetools_save_minutes(...source_segments)` 纪要另存、不覆写原转写，明确请求后 `files/save`，不自动知识库导入。最新同UID补丁没有修改该Skill，本轮也不修改。

**尚未完整写入**：该Skill没有完整的独立录音专节，尚未明确展开“大模型另行整理”和“疑点带时间戳交人工确认”的上述步骤；代码不自动调用大模型，不提供人工复核界面/工作流。不能报告为自动纪要或人工复核系统已完成。

代码事实：`worker.py` 写原始 transcript 并提示未生成纪要；`store.py:save_minutes` 写新的 `minutes-<artifact_id>.md`，保留 source_segments，标记 `author:agent-derived-unverified`。其返回 `status:SAVED` 指派生产物已写入任务缓存，**不代表永久保存或知识库入库**；长期保存仍须明确授权调用 `files/save`。

遗留 `filetools/SKILL.md` 仍保留手工脚本且提示优先插件，其中旧 `filetools-session` 名称与当前实际 `file-workspace` 不一致。列为后续核对事项，当前未修订，不能让遗留转换脚本能力冒充统一工具已经支持。

## 5. 代码、Skill、文档与入口

| 位置（相对仓库根） | 用途 |
|---|---|
| `src/nas_filetools/` | 可复用核心；engines/audio、worker、store/workspace、management/shared_workspace、saved_permissions/samba_results |
| `integrations/openclaw-filetools/src/index.mjs` | 真正OpenClaw工具及可信适配；该目录tests验证SDK/桥接 |
| `integrations/openclaw-filetools/skills/file-workspace/SKILL.md` | 当前插件调用规则，接手优先阅读 |
| `filetools/SKILL.md`、`filetools/bin/` | 遗留手工说明/引擎脚本，不是当前统一工具部署入口 |
| `scripts/filetools_admin.py` | install/diagnose/migrate/rollback及samba-results；服务器本轮不要 apply |
| `scripts/filetools_manage.py` | 可信固定配置管理适配，JSON stdin/stdout |
| `deploy/Dockerfile*`、`requirements.lock.txt`、`pyproject.toml` | 独立运行/测试环境；Samba测试镜像仅用于隔离开发 |
| `tests/`、`tests/test_v121_samba.py` | 核心/权限/来源/任务测试及两种UID真实Samba用例 |
| `docs/V12_ARCHITECTURE.md`、`docs/V12_INTERFACE.md`、`docs/V12_SUPPORT.md` | 共享布局架构、工具/产物契约、支持/限额 |
| `docs/V121_INSTALL.md`、`docs/V121_INTERFACE.md`、`docs/V121_USER_GUIDE.md` | 最新安装、UID模式、用户说明 |
| `docs/V121_SAMBA_UID_FIX.md` | 最新小补丁完整报告、迁移/回滚和生产待验收 |
| `docs/V121_REPORT.md`、`docs/V121_TESTING.md`、`docs/V12_*`、`docs/V11_*` | 历史阶段报告，按各自提交/批次解释，不作为本轮重测 |
| `docs/evidence/` | 已入Git的开发测试日志/JSON；当前分支可直接获得 |

Samba新同UID共享必须先用修复后CLI回滚，再回退代码；69c194c旧CLI会拒绝同UID。1.2.1同版本补丁不能重复install覆盖原rollback记录；备份、manager模块/独立Worker镜像更新说明见UID修复报告。本交接不执行安装、迁移或回滚。

## 6. 检查结果：真实、模拟、未验证

交接本轮只做 Git/文件/文档检查，没有重新运行处理引擎或生产验收。下表为已执行历史开发证据；重叠批次不累加。

| 批次/性质 | 已执行结果与边界 |
|---|---|
| 最新同UID补丁，静态 | Ruff src/tests/scripts与git diff --check通过；`docs/evidence/samba-owner-uid-static.txt` |
| 最新同UID补丁，真实 Linux 核心 | 91通过/15跳过，74.69秒；非root10001，本批未开启真实OCR/ASR；`samba-owner-uid-linux-regression.txt` |
| 最新同UID补丁，Windows目标测试 | 24通过/15跳过，43.12秒；Linux专属项跳过 |
| 最新同UID补丁，真实 Samba | 4通过，9.12秒；Debian Bookworm / Samba4.17.12，chen实际UID/GID1000；真实daemon/client、ACL、bind mount、runuser，新旧下载/四种写拒绝/错误账号/本地保存/重复安装/回滚数据权限保留；`samba-owner-uid-real.txt`与environment日志 |
| 最新同UID补丁，模拟部分 | systemctl调用替身，mount失败/busy卸载故障注入；不等于真实开机或NAS故障；虽位于真实Samba测试批次，也单独标为模拟 |
| V1.2.1历史真实CPU样本 | Linux引擎开启全量99通过/3跳过；文字PDF0.922秒、扫描3.236秒、混合2.920秒、DOCX1.012秒（PARTIAL）、印刷图2.258秒、MD0.971秒、JFK11秒录音7.973秒；本机Docker2CPU/4GiB，不是NAS速度，见V121_TESTING/evidence |
| V1.2.1历史SDK/桥接 | Windows19通过/1跳过、Linux18通过；真实SDK/核心桥接，身份/事件/渠道注入，非真实Gateway/QQ端到端 |
| V1.2/V1.2.1其他历史模拟 | 四小时/4GiB计数边界、注入ASR恢复、Compose/身份/QQ客户端及失败注入均不是完整真实大附件/长音频/生产服务 |
| 参考知识库插件历史回归 | 49通过/1跳过，TypeScript noEmit通过；Python全量缺pypdf/sqlite_vec出现4项收集错误，未完成，不算检索算法失败或通过 |
| 生产、服务器、CI | 本轮无服务器测试/生产接入/部署/服务重载；真实systemd、QQ、长中文录音、客户端/隧道全部待验收；未核查当前CI |

## 7. 必需环境、样本和 Git 外文件

- Linux x86_64，Python `>=3.11,<3.13`（固定镜像3.12.10）、独立venv；固定版本以requirements.lock/pyproject为准：PyMuPDF1.25.5、python-docx1.1.2、Pillow11.1.0、openpyxl3.1.5、RapidOCR1.4.4、ONNX Runtime1.20.1、NumPy1.26.4、faster-whisper1.1.1、pytest8.3.5、ruff0.11.2。
- FFmpeg、libseccomp2、DejaVu字体；Linux受限Python生产隔离要求Landlock ABI≥3/seccomp。Windows development隔离不能等同Linux沙箱。
- 插件开发Node24.16.0（package范围还允许>=26.1.0）、OpenClaw SDK2026.9.4、typebox1.1.38，独立`npm ci --ignore-scripts`，不要使用生产Gateway的node_modules。
- Docker仅使用经核对的**本机测试daemon**；不照搬Windows `desktop-linux` 到服务器，不用未知远端context。真实Samba测试需要smbd/smbclient/testparm/acl/systemd工具和仅一次性测试容器内bind权限；生产Worker不加privileged。测试无host端口、无生产目录或Docker socket挂载，loopback用于测试daemon。
- 网络仅用于明确准备依赖/镜像/模型/许可样本；处理阶段离线。CPU基线，不依赖GPU。首次下载需要空间/网络，缓存不能当已推送成果。

样本：`tests/conftest.py`动态生成文字/扫描/混合PDF、DOCX表格图片、印刷图、MD；不是私人资料。许可音频由`scripts/fetch_test_audio.py`下载openai/whisper固定提交`86098128c0b4f24f0e2aa2994de830614b474227`的JFK约11秒英文及MIT许可。ASR固定`Systran/faster-whisper-small`快照`536b0662742c02347bc0e980a01041f333bce120`，用`scripts/prepare_models.py`准备并记录文件SHA。真实用户匿名样本尚未提供。

仅当前环境、**未纳入Git**（不需要复制整个Windows工作目录）：

| 位置 | 接手方法 |
|---|---|
| 仓库`.venv/`、插件`node_modules/`、pytest/ruff/pycache/egg-info | 在服务器独立开发目录重建，不迁移Windowsvenv |
| 任务根`work/models/` | small/tiny.en模型缓存及manifest；服务器重新准备上述固定small快照，改用服务器绝对路径 |
| 任务根`work/samples/` | jfk.flac、许可/来源JSON；下载脚本可重建；合成文档由pytest重建 |
| `work/node.exe`、`work/sdk/`、QQBot参考材料 | Windows便携Node/SDK及参考源码证据，不是运行部署目录；独立npm固定SDK可替代 |
| 任务根`outputs/V1.1`、`V1.2`、`V1.2.1`、`V1.2.1-samba-uid-fix`及其他outputs | 本地源码ZIP/bundle/patch/附加证据与交付清单；Git含源码和docs/evidence，不自动上传这些归档 |
| 任务根`tmp-*`、benchmark、pytest生成目录 | 历史临时测试产物，非必需，不当作业务原件或新开发输入 |
| 用户Downloads中的各版本开发提示词MD | 未入Git；约束已汇入仓库设计/支持/接口与本交接，若需全文须用户另提供 |
| 本机Docker镜像/临时卷、运行配置/真实附件/认证 | 不在Git；镜像从提交重建，私密配置由有权限管理员独立提供，禁止提交凭据或复制生产数据作默认样本 |

## 8. 服务器第一个具体步骤与接续条件

**第一步只做源码接收核验**：在服务器新建与生产工作区分离的开发目录，clone此交接分支，核对发送方给出的完整SHA、确认工作区干净，然后完整阅读本文件；不运行install/apply、Compose up或碰生产容器。

```bash
# 从已确认的新隔离开发父目录执行；不要复用生产checkout
git clone --branch handoff/filetools-server-20261005 --single-branch https://github.com/cvbroth/openclaw-skills.git openclaw-filetools-dev
cd openclaw-filetools-dev
git rev-parse HEAD
git status --short
cat HANDOFF.md
```

确认SHA与最终交付一致后，在服务器Codex任务中声明“接手HANDOFF，先隔离复测基线，不部署生产”。先核对`python3 --version`、Node版本、`docker context show`及daemon目标、内核/FS/可用空间，再在新venv运行静态与默认核心测试；真实引擎/Samba按上述固定样本和隔离容器复测，各阶段记录真实/模拟/跳过。参考复现文档中的旧镜像tag应换成从交接提交重建的独立开发tag，不复用/覆盖生产镜像标签。

已知生产信息（用户提供，非本轮探测）：OpenClaw2026.9.4构建3a9d69d，Docker容器`openclaw-openclaw-gateway-1`，镜像`stockanalyse-openclaw-managed:latest`；Ubuntu26.04 x86_64，Xeon E3-1270v5 4核8线程AVX2，内存30GiB/此前可用约23GiB、swap8GiB；共用Immich/MySQL/检索服务；Gateway UID/GID1000、chen UID1000（chen实际GID待核实），QQ主要渠道。可用内存是旧时点信息，不作为当前余量。这些标识仅用于识别并避开生产，不授权exec/restart/改配置。

接续仍需：服务器隔离开发目录/测试daemon及空间、可用开发Python/Node/下载网络、需要时匿名样本。之后若要生产验收，另需明确授权、真实Samba/FS信息、审核后的安装/results路径与回滚记录、实际私聊/群聊及客户端范围。**连接Codex的服务器不等于批准部署生产。**原环境本次交接后停止修改/测试该任务；本文件不触发新的服务器任务或生产动作。

## 9. 服务器接手增量（2026-10-05）

本次接手在服务器 `myserver`、开发目录 `/home/chen/dev/openclaw-filetools-dev` 核对 HEAD 为 `9e853e857112816146153a423f640bc3dbbd5027`，初始工作区干净，当前命令账号 chen UID/GID 均为1000。独立分支为 `docs/filetools-recording-workflow-20261005`。

以下为用户补充的**已完成真实生产验证**，本轮接手未连接生产重复核验，也未取得新的生产日志：

- Chen 账号、Gateway、Worker 的 UID/GID 均为1000（更新原第8节的GID待核实项）。
- `/srv/storage/users/chen/FileTools-Incoming` 已只读挂载到两容器的 `/nas/filetools/chen/Incoming`，来源根名为 `incoming`。
- 用户可直接上传 Incoming，上传完成并关闭文件后再通知 Agent；没有自动扫描或自动处理。原 Uploading → Incoming 是其他环境可沿用的完成约定，不是当前 Chen 使用的必需步骤。
- PDF reference 登记、18页全文提取和 Markdown 回传已跑通。
- `calltoarms_03_lu.mp3` 全长661.524898秒，全文转写 SUCCEEDED，返回122段时间戳；实际附件12355字节，SHA-256与回执一致。用户未提供完整SHA，本轮不补造。
- 中文转写错字较多；实际模型与后端处理耗时尚未核实。流程成功不代表识别准确。上述事实不扩展为所有用户/渠道/客户端、真实Samba开机挂载、4小时或4GiB验收通过。

本轮用户授权仅更新现有录音 Skill 和必要文档、独立开发验证与提交。已补全“仅转写不生成整理稿；大模型另行整理；疑点携带时间戳交人工确认；明确确认后新增独立整理稿；不自动永久保存或入库”，并修正遗留 `filetools-session` 名称提示。运行时工具和引擎代码不变；当前工具支持缓存派生产物、真实片段关联和新增版本，不提供人工复核界面、原音试听或 confirmed/reviewed 状态参数。

本轮环境、场景检查、真实/模拟/未验证结果见 [录音流程更新报告](docs/RECORDING_WORKFLOW_UPDATE.md)。不调整模型、不部署生产、不修改运行中的Gateway/Worker/Samba或生产配置，不覆盖生产镜像标签；服务器开发不代表授权生产变更。

## 10. 文档生成小样本增量（2026-10-06）

文档分支 `feat/filetools-document-sample-20261006` 从已完成录音更新 `364d4d6431e63bd0244d4bce780b1b19458485b6` 创建，录音规则保留。新增可复用单选题 OCR 结构处理、python-docx/PyMuPDF 模板、独立渲染和 FileTools 核心发布/取回验证脚本；没有改变工具接口、服务架构或生产配置。Skill 补充 FILETOOLS_INPUT、已有产物 file_id 登记/选择、FileNotFoundError 诊断和证据保守的文档流程。

用户明确授权只读指定原 PDF 第6–10页及对应旧 OCR。指定 `/root` 原 OCR 权限不足后，未提权读取或扫描缓存，使用用户提供的开发副本；重新 OCR 结果另存。只在开发 runtime 保存5页副本、核对图和交付物，不提交原册或 OCR 正文。第6页第4题确为 OCR 漏行，原 PDF 完整；另发现第10页第32题开头漏行。恢复依据原页放大图，原稿不改，独立修订可追溯。

独立环境、可复现方式和能力限制见 [开发说明](docs/DOCUMENT_SAMPLE.md)，真实/合成/未验证结果及产物校验见 [本轮报告](docs/DOCUMENT_SAMPLE_REPORT.md)。服务器本轮仅开发和小样本交付，不进入或重启生产容器，不调整模型/生产依赖/权限/配置，不部署、不处理全册、不覆盖生产镜像标签；后续全册或生产部署等待用户确认。

## 11. 分页与模板增量

沿用文档样本分支和 `112c0e72c73a814372ed5e0aab16f30c959f080d`，改进可复用生成代码、集中模板和现有Skill；不重新OCR、不改32题原文、原始OCR或独立修订记录。Word/PDF分别验证原生/实测分页、标题层级黑色、简洁来源、自身页码；补充通用合成边界和精确前后比较。录音专节原文保留。详见 [分页改进报告](docs/DOCUMENT_PAGINATION_REPORT.md)；初版报告保留其历史时点。仍仅开发交付，不处理全册或部署生产。

本轮视觉复核补充：MuPDF逐页独立渲染仍偶有选项前缀漏显，未定位深层原因。独立开发验证镜像 `filetools-document-validation:20261006-pagination` 从旧文档测试镜像派生，仅补充Poppler-utils 22.12.0-2+deb12u3；验证脚本改用独立Poppler栅格引擎交叉复核。原生成依赖、生产标签、处理权限/限额不变。

## 12. PDF阅读器兼容性开发增量

沿用e49ac23a077031c61aadf043a9a04b3854159387和现有文档分支。用户Windows PDFium153/scale1.7实际漏显说明前轮单Poppler视觉验收不足；本轮Linux同版本同调用未复现，根因与Windows新版验证仍未闭环。可复用生成器增加全部Story/页脚后的原生字体子集、完整去重压缩保存，保留题文和分页；新增三引擎图像/字体流/搜索验证、资源复用回归及Skill跨阅读器边界。生成无新增运行依赖，开发验证单独加入PDFium/fontTools，不改生产。详见 [兼容性报告](docs/DOCUMENT_READER_COMPAT_REPORT.md)。继续停在小样本，不处理全册或部署。

## 13. 生产部署候选与模板管理准备（未部署）

用户已在原Windows、pypdfium2 5.13.0/PDFium153、scale1.7验收SHA为3ee015206c604d56af00563e6c4c74afbd2776cd85b6bf66943e80ce6b99951d的新版当前样本；第4页第13/14/16题前缀与来源正常，9页缩略图无新明显问题。根因仍未知，不扩大为所有文件/阅读器。保留12e8c614db898ed93d0823cbb2a41e227b156707后续增量。

本轮授权只读核对生产安装、挂载、依赖和固定限额；没有生产任务、重启、部署或全册。建立继承实际Worker镜像的独立候选，预装短调用生成入口、固定中文字体及版本化试题模板清单。当前模板仅questions-zh-cn/1.0.0，样式原值迁入JSON，结构解析与录音规则保留；运行入口只读选择已发布版本，不执行附件样式配置。独立候选按真实60秒/Landlock完成小样本包装、file_id再登记、生成及发布取回，约1.53–1.62秒生成、峰值RSS约132MiB；生产真实Gateway/Worker/QQ与每份文档视觉验收仍待部署后分阶段核对。详见 [部署/回滚方案](docs/DOCUMENT_DEPLOYMENT_PLAN.md) 与 [模板管理](docs/DOCUMENT_TEMPLATES.md)。到候选准备完成为止，等待用户审核和另行部署授权。

## 14. 已授权小范围生产部署（QQ验收待完成）

审核基线694908cadb58537379952148826180261f6a8578。本次已部署document-candidate-r3 Worker，确切ID dc7bb036ba656c50c0bb4e6732eb6a81d688b3bd938a73e45c212fcd519c04cd；备份、真实管理健康、受限模块/模板预检及正式发布取回通过。Gateway未重建，既有挂载/配置/限额保持。等待真实Chen QQ私聊测试，尚未完成本轮生成/附件/独立渲染，不复用开发回执声称生产通过。维护必须使用完整五Compose文件；回滚和具体状态见[生产部署报告](docs/DOCUMENT_PRODUCTION_DEPLOYMENT_REPORT.md)。不处理全册、不永久保存或入库。

## 15. 指定生产小样本生成及独立验收完成

真实QQ探针、完整合成输入及第6–10页修订包经候选Worker运行成功，五页生产任务0fe1b69318ae456ca642b728d286be64已正式发布取回，32题128选项、原OCR和独立审计不变。Word10页、PDF9页全部实际渲染并逐页/重点放大查看通过，PDFium153/Poppler/MuPDF均通过。用户已确认附件实际可收到并下载；客户端下载SHA、Windows本次PDF和Word字体替换仍待反馈。曾发生的合成包缺raw_ocr失败已按指定任务stderr定位，原记录保留，未调限额/沙箱。镜像与完整五Compose维护集合保持，Gateway不重建、无回滚。参见[生产部署验收报告](docs/DOCUMENT_PRODUCTION_DEPLOYMENT_REPORT.md)和非私密证据。到授权小样本为止，不处理全册、不永久保存/入库。


## 2026-10-06 正式整册任务预检（尚未完成）

继续文档分支641b5e3基线，用户已授权指定现有OCR原PDF6–169页、来源隐藏模板新版本，以及通过验证后的可回滚部署。真实整册OCR取回与页标记核实完成；原件印刷页码存在已看原页的跳转。来源隐藏草稿1.1.0与32题实际预览、独立审计保留已验证；整册实验恢复仍432告警，不能将容量试跑/自动全页渲染称正式成品。生产r3/模板1.0.0保持，未部署新模块或Skill。接续规则、真实/合成/未验证边界及测试见 [整册预检记录](docs/DOCUMENT_BOOK_PREFLIGHT_REPORT.md)。业务样本/图像仅在忽略的runtime/document-full，不上传。现存缺题号/题干片段的正文呈现选择已向用户提出，按回复继续；不得重新OCR整册或补写猜测。

## M3五页独立对照交接（2026-10-07）

在既有OCR测评分支及6963e50离线复核能力上增量完成，未改生产及外层整册文档工作区。见docs/OCR_M3_COMPARISON_REPORT.md和docs/OCR_M3_COMPARISON.md；五页私有包/证据位置、精确哈希、费用边界均在报告。当前渠道存在整页缩放和JSON协议失败；本地空间恢复选段CER优于M3直接，疑点复核仅一字符收益，安全人工候选减少未证明。保留原件、原OCR和未确认状态，等待用户查看离线包，不自动进入生产或全册。


## M3原图直接转写50页隔离实验（2026-10-07）

沿用6f7dbc2测评分支；固定种子2026100701、原PDF物理6–169中50页含23，未换样。通过同一MiniMax端点直传220dpi原PNG，51次请求的客户端图片字节/尺寸/哈希均与源图一致；服务内部缩放未知。49页原始转写成功，第136页两次返回output new_sensitive (1027)，失败/缺失usage保留。全部人工审核空白，不计算准确率，不混入历史五页结果。原图、全文响应和用户审核不入Git；详情及共享交付路径见[50页报告](docs/M3_ORIGINAL50_REPORT.md)及[操作说明](docs/M3_ORIGINAL_IMAGE_TRANSCRIPTION.md)。不改生产、不运行OCR、不生成正式题册、不入库，等待用户审核。


## OCR后端十页横向对比（2026-10-08）

保留760105f测评分支和外层整册开发成果。只测试物理9/10/12/16/23/75/81/136/150/168，220dpi同原件；MinerU4.0.10 Basic/ONNX CPU十页完成，PaddleOCR3.7.0+VL1.5及官方MonkeyOCRv2 CPU首张均300秒超时、无OOM，不扩跑。M3仅复用历史7成功/136两次失败/9和10缺失，新云调用0。有限同区域CER不代表整页准确率；困难23页仍有错误。通用适配、完整原生/默认及完整模式MD、结构JSON和离线对照包已准备，详见[横向报告](docs/OCR_BACKEND_COMPARISON10_REPORT.md)、[开发入口](docs/OCR_BACKEND_COMPARISON_RUNBOOK.md)及共享交付清单。未改生产/Skill/模板，无整册OCR或正式文档生成、保存/入库。等待用户查看，不自动扩大50页或确定最终后端。


## VL1.6真实CPU整页两页实验（2026-10-08）

基于01a7a406727f89ad72fdf46c1aab58b0b554c133测评分支，保留外层整册工作区和既有十页证据。本轮真实PaddleOCR-VL1.6固定权重c5630aba、native Paddle CPU、同220dpi1819×2573 PNG，2CPU/16GiB无额外swap、推理断网、加载180/单页1800秒；先12后23均整页完成，识别+导出1015.088/713.368秒，约9GiB RSS，无OOM/重复早停/生成上限。实际CPU仍近一核，官方其他CPU引擎未测，不把已完成说成逐字准确或生产适用。旧1.5诊断区分观察器故障与部分输出，历史M3仅复制，无新云调用。

新增通用阶段观察、资源采样、真1.6入口、原生适配和下载流式校验，20项合成回归及Ruff通过。两页离线原图/原文对照包已在Chen独立交付目录，文件大小/哈希、真实/合成/未验证、固定身份及资源详见[本轮报告](docs/PADDLEOCR_VL16_TWO_PAGE_REPORT.md)、docs/evidence/vl16-two-page-delivery.json和既有runbook增量。私有根runtime/paddleocr-vl-evaluation/vl16-two-pages-r1，业务图文/响应/权重未入Git。等待用户看两页原文；不自动扩跑原十页/整册，不测试更多新项目、不部署、不修改Skill/Word模板、不保存/入库。


## MonkeyOCRv2 CPU两页实验（2026-10-08）

基于86c3a28测评分支，原有MinerU/VL1.6/M3及外层整册成果保持。只用同字节220dpi物理12/23页，复核已有模型全部SHA与官方CPU源码6cc0c0bb，复用固定Torch2.5.1+cpu/Transformers4.57.1镜像。2CPU/16GiB无额外swap、断网；官方server_max_inflight显式1避免32区域worker争2CPU，观察器本身不串行化计算、不重复prepare或改输入，实际线程2/1、float32。

12页439.681秒页面处理、11原生块、无生成上限、约6.49GiB RSS，两个指定短语匹配原图。23页布局与12文字调用完成，但最后340×62页脚达到1536个语言步骤仍未返回；按明确异常授权主动止损，总进程746.296秒，FAILED/-15/timeout=null、无OOM/swap，分类ABORTED_EXCESSIVE_GENERATION，不声称具体重复或完整页成功。无最终原生JSON/Markdown；保留原始调用/布局坐标/实际图像与有标识部分展示，未验证的坐标关联为null，未编造产物。

24项合成回归、静态检查及真实离线浏览器两页四路对照通过（不代表文字准确率）；局部错字/题号/遗漏与受损源图边界见[报告](docs/MONKEY_CPU_TWO_PAGE_REPORT.md)。私有根runtime/paddleocr-vl-evaluation/monkey-two-pages-r1；共享新包及SHA见docs/evidence/monkey-two-page-delivery.json。新增云调用0、不重试/扩页、不部署、无Word/PDF/保存/入库。当前路线不宜直接扩大，等待用户查看。

## MinerU Standard本地CPU两页实验（2026-10-08）

基于8cf887d保留Basic、VL1.6、Monkey和历史M3及外层整册改动。复用MinerU4.0.10镜像，官方Standard/high＋ONNX小模型＋MinerU2.5-Pro-2605-1.2B Q8_0 GGUF（固定9185688a），嵌入式mineru-llama-cpp0.1.2/9a3bf2b。显式官方参数2线程/0GPU层/单槽，2CPU/16GiB无额外swap、network none、原图模型只读、单页1800秒；不修改安装包源码或生产。

同字节220dpi物理12先完成，再23独立进程，页面346.878/289.061秒，均完整原生成功，swap/OOM/截断0，约2.36/2.31GiB峰值RSS。较Basic题干/选项组织及可读性有收益，但仍有专名、困难字形、基础→范围等关键误读，不证明优于M3或全页准确。首次Helper方法定位错误的观察器初始化失败完整保留；开发网络准备失败/停止记录独立保留，未混入识别性能。已纠正历史“原126→128”证据不足表述：源23该字形接近128，不凭正常题序猜改。

通用Standard入口、实际data-URI/响应捕获、脱敏阶段摘要、26项合成回归及真实file://五路对照通过；正文/图片/响应/模型不入Git。两页原生JSON/MD、完整模式/原始响应/实际裁片、阶段资源日志和共享ZIP见[本轮报告](docs/MINERU_STANDARD_TWO_PAGE_REPORT.md)、docs/evidence/mineru-standard-delivery.json与runbook增量。私有根runtime/paddleocr-vl-evaluation/mineru-standard-two-pages-r1。无新M3/云调用、无生产/Skill/模板变更，无整册/WordPDF/永久保存/入库。客户端实际下载/看版、源字形歧义和逐字准确仍待用户；不自动优化速度、扩页或转测新模型，等待查看。
