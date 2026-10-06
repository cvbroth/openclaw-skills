# 文档生成生产候选与部署方案

2026-10-06，分支 feat/filetools-document-sample-20261006；保留12e8c614db898ed93d0823cbb2a41e227b156707及此前录音/文档成果。**本轮只读生产核对、离线候选构建和开发验证；没有部署、重启、生产生成、全册处理或永久保存。** 用户Windows验收补入 [兼容报告](DOCUMENT_READER_COMPAT_REPORT.md)，原漏显根因仍未知。

## 实际安装与最小变更

只读docker inspect及指定容器内包元数据/白名单配置查询，未读业务附件、凭据或完整环境变量。Gateway OpenClaw2026.9.4，插件nas-filetools1.2.1，manifest加载 `./skills`。Gateway镜像ID `sha256:817c7c3a8bf9ec233c97875de7d35e00d61862886e884bd09d69946aadd54819`，配置用户node；UID/GID1000沿用已核实的生产事实。Worker配置用户1000:1000，镜像nas-filetools:1.2.1，ID `sha256:17be5923cdb294ac87635537853786817ea13907cce1e4b26bf8259a6feec685`；包1.2.1、Python3.12.10、PyMuPDF1.25.5、python-docx1.1.2、Pillow11.1.0、NumPy1.26.4。

Worker network:none、read_only:true、no-new-privileges、2CPU/4GiB/pids96；脚本Landlock、60秒、输出256MiB、线程2、单重任务并发沿用。固定配置中的workspace_mode:false是基值，实际shared mapped_store强制workspace_mode:true；不需要修改此配置。生产scripts.py/script_launcher.py哈希与仓库一致，现有Landlock允许读sys.prefix，Python `-I`可导入虚拟环境site-packages中的预装模块，无需PYTHONPATH、额外挂载或沙箱扩权。

| 确切位置 / 候选变更 | 用途与边界 |
|---|---|
| Worker镜像内 `/opt/nas-filetools/.venv/lib/python3.12/site-packages/nas_filetools/document_sample.py`、`document_entry.py`、`document_templates.py` | 新增预装生成器、显式范围单输入包装/短调用及模板校验入口；模板由专用templates目录和版本清单加载；不替换其他核心模块 |
| Worker镜像内 `/opt/nas-filetools/.venv/lib/python3.12/site-packages/nas_filetools/templates/` | 专用目录含catalog/schema及published/questions-zh-cn/1.0.0.json；只读加载已发布版本，Agent只能选择ID/版本；管理流程见[模板说明](DOCUMENT_TEMPLATES.md) |
| Worker镜像内 `/usr/share/fonts/truetype/filetools/DroidSansFallback.ttf` | 从固定PyMuPDF自带字体提取，SHA `ee38813ea00c3e32add4268fff7fff9e39417b4913cb13be2415164a47807cc2`；生产当前不存在，不需要NAS字体挂载/联网下载 |
| 宿主 `/root/.openclaw/extensions/nas-filetools/skills/file-workspace/SKILL.md`，容器 `/home/node/.openclaw/extensions/nas-filetools/skills/file-workspace/SKILL.md` | manifest实际Skill位置；宿主根由现有bind映射确认。生产旧Skill SHA `5dc0e1ef5cf0e9e8ec02c47753b7bd7739d6cfc061f87cc7234f311cb30d3b39`，对应交接基线；候选保留并带上此前录音更新 |
| 同Skill目录 `references/document-generation.md` | 新增真实短调用/输入证据格式与未部署边界说明；随Skill一起备份/恢复 |
| 新增宿主 `/var/lib/nas-filetools-v12/installation/1.2.1/compose.document-candidate.yaml` | 仅覆盖nas-filetools服务镜像；仓库候选文件为deploy/compose.document-candidate.yaml，不覆盖原安装回滚记录 |

管理代码 `/var/lib/nas-filetools-v12/installation/1.2.1/manager` → Gateway `/opt/nas-filetools-management:ro`、worker.json/gateway.json均不改。Gateway不装库/字体、不换插件JS或镜像。保留全部既有Compose文件、socket/model/control及chen共享工作区挂载：Worker `/workspaces/chen/filetools`，Gateway `/home/node/.openclaw/workspace-chen/filetools`；两边Incoming `/srv/storage/users/chen/FileTools-Incoming` → `/nas/filetools/chen/Incoming:ro`，source_root incoming。原件、Samba、保存/知识库授权不改；上传完成关闭后通知，无自动扫描。

## 候选包与实际调用

已用现有Worker不可变ID建立独立别名 `filetools-document-base:20261006-17be592`，离线构建 `nas-filetools:document-candidate-20261006-12e8c61-r3`。本机image inspect ID `sha256:dc7bb036ba656c50c0bb4e6732eb6a81d688b3bd938a73e45c212fcd519c04cd`，493996203字节。这是本机候选，没有推送镜像注册表、没有覆盖nas-filetools:1.2.1或managed:latest。Dockerfile继承原ENTRYPOINT/CMD，只加三模块、已发布模板及字体，版本不冒称新正式release。

可复建命令（本轮已执行；其他主机需先合法取得同一基础镜像）：

```bash
docker tag sha256:17be5923cdb294ac87635537853786817ea13907cce1e4b26bf8259a6feec685 filetools-document-base:20261006-17be592
docker build --network none -f deploy/Dockerfile.document-candidate -t nas-filetools:document-candidate-20261006-12e8c61-r3 .
docker image inspect nas-filetools:document-candidate-20261006-12e8c61-r3 --format '{{.Id}}'
```

审核部署包包括该Dockerfile、只改镜像的Compose override、三模块、模板目录和现有Skill/新增reference，均在Git；私密样本、修订及渲染图仅在ignored runtime/document-sample。候选不是生产实例；部署前必须核对image ID、源码/Skill哈希，不能用标签名代替确认。

小爪流程沿用十个现有工具：具体文件register → inspect确定范围 → extract或复用OCR产物file_id → read分段/原页核对结构及疑点 → 对OCR attachment用filetools_python调用prepare_registered_ocr（原OCR+独立修订作为数据） → status取得正式reviewed-input.json file_id → register该file_id → filetools_python两行调用generate_registered_input → status及审计/内容验证 → 独立渲染和人工验收 → files/artifact_path → 当前真实message媒体入口及QQ下载校验。版本化模板ID/版本在业务包中显式选择，实际ID/版本/SHA进入生成记录；未发布或附件inline样式拒绝。入口/输出列表见 [Skill调用参考](../integrations/openclaw-filetools/skills/file-workspace/references/document-generation.md)。OCR的Page N标记可直接识别，不改写页号；缓存过期时不猜替代文件。原始OCR不覆盖，修订证据不会被生成器自动认定为真实核对。

不需要新工具、每次重拼模板、跨任务读缓存或Gateway任意exec。**接口缺口仍有**：无正式原页人工复核界面、无注册的跨阅读器视觉验证工具；受限Python仍是现有通用代码工具，模板选择约束由正式入口与Skill执行，不能声称它禁止所有自行排版代码；当前失败核心回执可能只给SCRIPT_FAILED/Fault，拿不到日志时不能判定具体原因。这些不通过扩权限解决。生产需要现有可用页图读取/管理员辅助核对、独立验收回执；尚未完成时只能交付明确标记待验收稿。

## 依赖与验收边界

| 用途 | 进入候选生产Worker | 仅开发验证 |
|---|---|---|
| Word生成 | 已有python-docx1.1.2；集中模板；固定字体名 | LibreOffice7.4.7.2实际打开/导出Word；fontconfig提供字体发现 |
| PDF生成 | 已有PyMuPDF1.25.5 / MuPDF1.25.6；固定Droid字体；原生子集/去重保存 | 不用LibreOffice替换生成路径 |
| 内容、顺序、页码、字体映射、裁切边界 | generate_sample内置validate_pair；CPU/RSS与时间指标 | document_layout_checks深入分页核查 |
| 跨引擎显示 | 没有新独立引擎；不声称视觉验收完成 | PDFium153（pypdfium2 5.13.0）、Poppler22.12.0及MuPDF逐页栅格，像素候选+人工放大看版；fontTools4.55.3资源诊断 |

模板打包检查另外使用独立开发镜像filetools-document-package-test:20261006-template，补入pyproject固定setuptools75.8.2和wheel0.45.1，仅用于离线wheel构建核查；它们不加入候选生产镜像。最初验证镜像缺setuptools.build_meta导致打包未完成，独立准备后重验，不能冒称原镜像已具备构建后端。

字体来自已经固定的上游运行包，不增设字体下载源；沿用上游软件许可材料，不将字体另作独立附件分发。实际OS/2 fsType=8，Word仍不嵌入字体，未验证用户端字体替换。运行时不承诺Word分页与PDF相同；一份开发渲染报告不能替今后每份文件验收。若未来要自动生产渲染，应另审查Worker验证模块/依赖增量及限额，当前候选不包含该改动。跨阅读器显示差异必须停止视觉通过结论，保留确切哈希/环境，修复后重验。

## 60秒与开发验证证据

实际候选容器：network none、只读根、UID1000、cap-drop ALL/no-new-privileges、2CPU/4GiB、开发源码ro及样本rw、/tmp tmpfs8GiB；不挂生产目录/socket。沿用真实Landlock、脚本60秒和RLIMIT_AS4096MiB。RSS是Linux该脚本进程ru_maxrss（含库导入），不是容器整体峰值；生成内部计时不含模块导入，核心墙钟含调度/回收/发布及本地取回，不含生产排队/QQ。未提高限额。

| 相同32题样本 | 生成秒 | 核心墙钟秒 | 子进程峰值RSS KiB |
|---|---:|---:|---:|
| 1 | 1.616321 | 2.358572 | 135008 |
| 2 | 1.612421 | 2.362474 | 134728 |
| 3 | 1.533380 | 2.397044 | 135012 |

该样本适配60秒；不能线性推算全册或共享服务高负载。只读主机时点available约20687MiB，开发盘余313GiB，是瞬时资源信息，不是生产容量承诺。全册性能待另行授权验证。

真实候选核心包装、发布file_id再登记、三次短调用、七产物正式发布取回均SUCCEEDED、字节/SHA一致；合成两段中文短文通过同一受限Python写入器、生成及发布，仅是字形/基本调用smoke，不是通用文章模板。原OCR、structured.json、issues.md与已交付版完全一致（32题/128选项/顺序保留）。候选样本PDF158059字节，生成时间引起PDF文件标识/WordZIP归档变化，不能冒用用户验收过的3ee...哈希。新产物三引擎9页自动6287字像素/搜索通过，开发LibreOffice Word10页及PDF9页内容、黑色、页码/边界检查通过；实际栅格已生成。本轮没有重新逐页人工看版，仍保留manual_review required。非私密记录见 [候选检查证据](evidence/document-deployment-checks.txt)。

真实=只读生产元数据、隔离库/沙箱/发布/渲染；测试可信identity为固定注入，直接调用核心dispatch/Supervisor，没有真实Gateway身份绑定、Unix HTTP或QQ渠道链路；模拟=既有回归中的故障注入，不能当生产故障实测；未验证=生产真实调用、Skill热加载、新附件每页视觉、人端Word替换、QQ送达、完整全册/负载、CI。初轮合成短文测试曾因使用不存在的Word样式stem而SCRIPT_FAILED；修正为真实Normal样式后通过，不归因大小/内存；初次Docker FROM裸sha误作注册表标签，已改独立本地基础别名。保留失败边界，不掩饰退出码。

最终相关测试36通过、5条上游SWIG警告，21.09秒；Ruff、Skill quick_validate、发布模板校验通过。独立离线wheel实际构建并核对三份模板资产在包内；没有在生产安装此wheel。录音专节逐字与12e8基线一致，模板23项参数与原代码默认值逐项一致。完整源码部署包及文件校验清单将由本轮提交导出到ignored runtime，仅含可审核源码/模板/文档，不含私密样本或完整镜像；镜像候选保留在本机Docker。

## 部署和回滚操作清单（尚未执行；需用户审核后授权）

1. 暂停新的FileTools处理请求，等现有任务终态；只读status确认重任务空闲，避免中断ASR/OCR。记录当前镜像ID、Skill哈希、四份Compose文件来源、安装配置哈希与健康回执。如果部署前已有后续改动，停止审查差异，不覆盖本轮之后的配置。
2. 管理员在私有新目录 `/var/lib/nas-filetools-v12/deployment-backups/document-<时间戳>`（0700）备份以下原文件与整个file-workspace Skill目录，保留所有者/权限：四份Compose（下列命令列出）、`installation/1.2.1/{worker.json,gateway.json,rollback.json}`。不要输出/提交配置内容，不改旧rollback.json。若需要登记表备份，仅在暂停写入后使用SQLite backup，不复制活跃DB当一致备份；本次无schema迁移，回滚不需要恢复DB，不覆盖新产物或saved。预留旧Worker基础别名、旧Gateway镜像，禁止prune旧镜像。
3. 核对候选ID和Git提交，将候选override复制到上述安装路径；替换指定Skill目录中的SKILL.md并加入reference（不是整包重新install）。部署后若技能未刷新，先新建测试会话确认；如仍旧版，只按现有Compose重建Gateway，不编造reload命令。Gateway受控重建也属于待批准部署动作。
4. 以下是完整四文件列表再追加候选的真实服务名命令；仅生产部署获批后执行。不使用filetools_admin install覆盖现有1.2.1记录。先审查合并配置，只核对nas-filetools镜像及volume/限额，不打印完整配置/环境；确保既有mounts全保留后只重建Worker：

备份与复制示例（管理员在指定开发checkout执行，仅未来获批后）：

```bash
document_backup=/var/lib/nas-filetools-v12/deployment-backups/document-$(date +%Y%m%d-%H%M%S)
sudo install -d -m 0700 "$document_backup"
sudo cp -a --parents /home/chen/openclaw/docker-compose.yml /home/chen/openclaw/docker-compose.override.yml /home/chen/openclaw/compose.filetools-incoming.yaml /var/lib/nas-filetools-v12/installation/1.2.1/compose.filetools.yaml /var/lib/nas-filetools-v12/installation/1.2.1/worker.json /var/lib/nas-filetools-v12/installation/1.2.1/gateway.json /var/lib/nas-filetools-v12/installation/1.2.1/rollback.json /root/.openclaw/extensions/nas-filetools/skills/file-workspace "$document_backup/"
sudo install -m 0644 deploy/compose.document-candidate.yaml /var/lib/nas-filetools-v12/installation/1.2.1/compose.document-candidate.yaml
sudo cp integrations/openclaw-filetools/skills/file-workspace/SKILL.md /root/.openclaw/extensions/nas-filetools/skills/file-workspace/SKILL.md
sudo install -d -m 0755 /root/.openclaw/extensions/nas-filetools/skills/file-workspace/references
sudo install -m 0644 integrations/openclaw-filetools/skills/file-workspace/references/document-generation.md /root/.openclaw/extensions/nas-filetools/skills/file-workspace/references/document-generation.md
# 核对Skill两文件保持原服务可读权限；不递归更改/root权限。
```

宿主stat已确认这些安装配置/rollback文件存在；备份内容本轮未读取。管理员备份目录不得变成Agent可读或Git目录。这些命令需要管理员对指定安装路径的写权限；本轮没有核验/使用sudo生产写权限。若备份不存在则停止回滚审查，不能猜原文件。

```bash
cd /home/chen/openclaw
document_compose=(docker compose --project-name openclaw
  -f /home/chen/openclaw/docker-compose.yml
  -f /home/chen/openclaw/docker-compose.override.yml
  -f /var/lib/nas-filetools-v12/installation/1.2.1/compose.filetools.yaml
  -f /home/chen/openclaw/compose.filetools-incoming.yaml
  -f /var/lib/nas-filetools-v12/installation/1.2.1/compose.document-candidate.yaml)
"${document_compose[@]}" up -d --no-deps --force-recreate nas-filetools
# 仅确认Skill未刷新、且已批准Gateway重建时：
# 必须先确认stockanalyse-openclaw-managed:latest仍指向运行中原817c...ID；漂移则停止审查。
"${document_compose[@]}" up -d --no-deps --force-recreate openclaw-gateway
```

5. 健康检查：docker inspect镜像/UID/2CPU4GiB/只读根/网络/pids与挂载逐项比对；查看限定启动日志（不输出业务正文）；通过已有可信管理适配的health操作确认scheduler_alive/无error，inspect/status验证原会话仍可读。健康接口需要可信identity，不伪造QQ sender/session；由原管理调用提供，当前用户工具没有filetools_health。确认新会话真实Skill内容/短调用可见、incoming仍ro、录音规则仍可见，不运行NAS扫描。失败立即进入下述回滚，健康通过也不能代替文档验收。
6. 回滚：先停发新请求并等任务终态；恢复备份Skill整个目录（移除本轮新增reference，确认旧hash）；从完整Compose命令去掉最后候选文件，用原四文件重建nas-filetools。先核对原tag仍指向旧17be...ID；若漂移，使用保留的 `filetools-document-base:20261006-17be592` 写临时只改镜像的rollback override追加，核对ID后再重建，不能盲拉latest。若Gateway曾重建/缓存新版Skill，恢复Skill后按原四文件受控重建Gateway并核对原817c...ID。移走本轮override至备份目录，不删除数据。健康和旧提取/录音调用复验；按status核对INTERRUPTED任务，不能声称RUNNING全部成功。**不回滚/删除业务原件、registry、cache、saved、模型或Samba，不用旧DB覆盖部署后新任务。** 配置如未改不覆盖；如意外漂移须审查后恢复具体备份，不覆盖后来合法变更。

回滚命令骨架（document_backup必须指向实际本次备份；管理员在确认无后续合法变更后执行）：

```bash
sudo cp -a "$document_backup/root/.openclaw/extensions/nas-filetools/skills/file-workspace/." /root/.openclaw/extensions/nas-filetools/skills/file-workspace/
if ! sudo test -e "$document_backup/root/.openclaw/extensions/nas-filetools/skills/file-workspace/references/document-generation.md"; then
  sudo rm -f /root/.openclaw/extensions/nas-filetools/skills/file-workspace/references/document-generation.md
fi
document_rollback=(docker compose --project-name openclaw
  -f /home/chen/openclaw/docker-compose.yml
  -f /home/chen/openclaw/docker-compose.override.yml
  -f /var/lib/nas-filetools-v12/installation/1.2.1/compose.filetools.yaml
  -f /home/chen/openclaw/compose.filetools-incoming.yaml)
# 原Worker标签ID核对无漂移后：
"${document_rollback[@]}" up -d --no-deps --force-recreate nas-filetools
# 仅Gateway确曾更新且旧镜像ID已核对后：
"${document_rollback[@]}" up -d --no-deps --force-recreate openclaw-gateway
sudo mv /var/lib/nas-filetools-v12/installation/1.2.1/compose.document-candidate.yaml "$document_backup/compose.document-candidate.applied.yaml"
```

标签漂移时的只改镜像rollback override例：`services: {nas-filetools: {image: "filetools-document-base:20261006-17be592"}}`，保存到私有备份目录并追加为最后一个-f；Gateway标签漂移同理先为已保留817c...镜像建立独立回滚别名，再追加只改openclaw-gateway.image的override，不能重建后才核对ID。

## 部署后分阶段验收（待授权，未执行）

1. 真实Chen私聊：只选指定合成中文输入，经Gateway→Worker受限Python→status→artifact_path→启用的QQ媒体入口。核对运行限额、原件不变、生成页码/中文；用户下载Word/PDF，比较每份字节/SHA。两段短文只验证调用/字形，不声明题库模板通用。
2. 仅当前已授权第6–10页小样本：复用旧OCR和独立原页修订；部署前将指定开发业务副本通过用户授权的正常上传/指定工作区输入路径提供，不能挂载开发仓库或扫描生产缓存。使用新可信测试会话，description包含候选发布标识（现有幂等fingerprint包括payload），核对新job创建时间，不能拿旧缓存回执冒充候选实际执行。使用实际file_id回执、输入包装和预装短调用，核对32题/128选项/原OCR与修订记录及模板ID/版本，测实际耗时/RSS。正式发布后取回到隔离验证环境，LibreOffice渲染Word，PDFium/Poppler/MuPDF逐页并人工放大检查第4/14/26题等边界，记录确切产物SHA；有差异则不能通过。用户QQ附件下载再次比对哈希，并在原Windows条件复验。
3. 上述真实验收成功后才提出较大样本测试的具体范围/资源方案；全册仍需单独用户确认，不自动执行。试题结构模板仅承诺已验证同类输入。生产验收结果必须新记录，不复用本轮开发报告称今后每份文件均已验收。

到此仅候选与可审核操作方案完成，等待用户审核和另行部署授权。
