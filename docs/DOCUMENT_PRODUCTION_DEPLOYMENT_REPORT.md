# 文档能力小范围生产部署：等待 QQ 端到端验收

2026-10-06，myserver，分支 `feat/filetools-document-sample-20261006`。审核基线 `694908cadb58537379952148826180261f6a8578`，部署前 HEAD 相同、工作区无后续改动。本次用户明确授权部署及指定小样本；没有处理全册、重新OCR、永久保存、入库或修改模型/Samba/沙箱限额。历史部署方案中的“未执行”是准备轮次时点，本报告记录本次实际执行。

## 已执行与可追溯状态

- 部署前真实管理 health 为 HEALTHY、scheduler_alive=true、error=null、active_workers=0；配置工作区登记表只读核对 QUEUED/RUNNING=0。最终重建前再次检查空闲，没有取消或中断任务。
- 原 Worker ID `sha256:17be5923cdb294ac87635537853786817ea13907cce1e4b26bf8259a6feec685` 已保留；旧标签及独立基础别名不覆盖、不清理。
- 部署标签 `nas-filetools:document-candidate-20261006-12e8c61-r3`，运行中确切 ID **`sha256:dc7bb036ba656c50c0bb4e6732eb6a81d688b3bd938a73e45c212fcd519c04cd`**，与审核候选一致。包仍标1.2.1，不冒称新正式release。
- 私有备份 **`/var/lib/nas-filetools-v12/deployment-backups/document-20261006T084935Z`**，目录0700、manifest0600；九个原文件与整个Skill目录用cp -a备份，逐项核对字节哈希、所有者、权限、mtime。没有数据库恢复、模型/cache/saved删除。
- 宿主sudo需要交互认证；使用现有Docker管理权限的临时管理员辅助容器，仅挂载指定安装/Skill/备份目录，完成已授权备份和复制。此为管理员部署操作，不是放宽生产Worker或Agent沙箱。生产业务目录权限不改。
- 仅新增 `/var/lib/nas-filetools-v12/installation/1.2.1/compose.document-candidate.yaml`（只改Worker镜像），更新 `/root/.openclaw/extensions/nas-filetools/skills/file-workspace/SKILL.md`，新增其 `references/document-generation.md`。原Skill所有者/权限保持；原六个Compose/Worker/Gateway配置哈希不变，rollback.json不改。
- 初次安装 Skill SHA `f318955fe4ae42fbff6553cdc52cc68e654931f0d204846da676b24771700f8a`；reference SHA `8b613cb231e3af5a75977972d1d76dc43308cdebe6eb5cc1cb2c3f7b9eed2659`。本次源码只把固定“未部署”措辞改为实际Worker能力与分阶段验收条件；保留录音规则和保存/知识库授权。运行中Gateway能读到同一哈希，真实Chen QQ会话Skill描述中列出file-workspace，未发现缓存旧部署正文；下一条QQ请求仍明确要求重新读取Skill。
- Gateway **没有重建**；实际旧ID `sha256:817c7c3a8bf9ec233c97875de7d35e00d61862886e884bd09d69946aadd54819` 及启动时间未变。真实QQ加载结果待验收；必要时再按已授权方案受控重建，不能凭文件哈希声称模型已读取。

## 完整维护 Compose 集合

今后重建必须保留以下全部文件，避免漏掉incoming或候选：

```bash
document_compose=(docker compose --project-name openclaw
  -f /home/chen/openclaw/docker-compose.yml
  -f /home/chen/openclaw/docker-compose.override.yml
  -f /var/lib/nas-filetools-v12/installation/1.2.1/compose.filetools.yaml
  -f /home/chen/openclaw/compose.filetools-incoming.yaml
  -f /var/lib/nas-filetools-v12/installation/1.2.1/compose.document-candidate.yaml)
# 本次实际仅执行Worker：
"${document_compose[@]}" up -d --no-deps --force-recreate --pull never --no-build nas-filetools
```

合并前后配置只存在Worker镜像差异；docker inspect逐项比对全部mount/security/resource字段相同。Worker UID/GID1000、network:none、只读根、no-new-privileges/cap-drop ALL、2CPU/4GiB/pids96。Incoming两容器只读、现有workspace/model/control/socket挂载保留。脚本仍Landlock/60秒。候选三模块与三模板资产哈希逐项匹配审核源码；Python3.12.10、PyMuPDF1.25.5、python-docx1.1.2；固定Droid字体SHA `ee38813ea00c3e32add4268fff7fff9e39417b4913cb13be2415164a47807cc2`。模板questions-zh-cn/1.0.0校验通过，参数SHA `eb5804259d000e6348b597e25487cba3bf8f7215987fffd09cf38851e1331df7`。没有在Gateway临时安装库/字体。

## 真实管理健康与受限预检

生产没有名为filetools_health的注册工具。固定管理CLI也不支持health。新增 `scripts/filetools_deployment_health.mjs` 使用现有SDK只读取得唯一Chen QQ私聊真实session epoch，并与登记表已有owner匹配，再经安装的plugin client真实Unix `/v1/tool` health；不伪造入站、发送人或身份，不输出私聊标识/凭据。

部署后真实结果：HEALTHY、scheduler_alive=true、error=null、active_workers=0。独立于QQ入站，这是管理员管理通道检查。

随后在同一既有真实上下文，经正式管理register登记合成输入，真实Gateway→Unix接口→Worker受限Python加载模块/模板/字体，正式发布并通过files/artifact_path取回。预检job `61cd73551f344714be8e57401067f673`，SUCCEEDED；preflight.json为1029字节，SHA `02fda76bc8d7c86d213230dce28d8cf48be1d0b41d858242c9b6c1ab7ba0e54c`，取回一致。确认唯一FILETOOLS_INPUT内容125字节、模板published校验和固定依赖。**不是QQ消息端到端，不是文档生成性能或视觉验收。**

管理员第一次模块探针误用了不存在的list_templates，ImportError后改为仓库真实TEMPLATE_ROOT/load_template入口，通过；没有修改运行代码或据此认定Worker故障。宿主无Node，语法检查改用现有Gateway Node并通过；Skill quick_validate通过。这些探针失败与修正保留，未猜测大小/内存原因。

## 后续必须完成的真实验收

正常Chen工作区已创建两个关闭写入的独立测试副本：`document-production-smoke-20261006.txt`（合成中文）及 `document-production-p6-p10-20261006.review.json`（仅已授权五页旧OCR及已核实独立修订）。使用原有登记路径，不挂开发源码、不扫描NAS或其他缓存。业务副本和回执仅在忽略目录保存，不上传GitHub。

已向用户给出可直接发送的QQ指令：先短文，再预装generate_registered_input生成七产物。现在等待真实Chen私聊入站，尚未有本轮QQ生成job或附件回执，不制造事件。随后需核对新任务时间、32题128选项全文/顺序、原OCR与修订记录哈希、实际模板ID/版本、耗时与RSS；通过正式产物引用取回，核对字节/SHA。生产的运行检查不能替独立渲染。

实际本轮生成文件取得后，在不挂生产目录/socket的隔离开发环境执行LibreOffice Word渲染，PDFium153/pypdfium2 5.13.0 scale1.7、Poppler22.12和MuPDF1.25.6全部样本页渲染及人工放大看版，重点选项/来源/中文/页码和4/14/26题分页。此时才能记录本轮确切PDF/Word哈希和验收结果。以前用户Windows同版本对开发PDF的通过仅是历史证据，不替本轮生产文件。Word字体不嵌入，用户端替换和客户端下载只能取得实际反馈后通过。

真实：本次生产备份、部署、配置/挂载/镜像/哈希核对、真实管理健康、受限预检与正式发布取回。模拟：本轮无故障注入，不把已有开发核心回归当生产QQ。未验证：本轮QQ入站/生成/媒体交付、生产文档内容与渲染、实际生成耗时/RSS、用户下载与Word字体替换、较大输入/全册负载。生成Worker不增加LibreOffice/Poppler/PDFium；这些仍仅在独立验收环境。试题模板不承诺文章、表格、公式、论文或任意扫描件。

## 回滚状态

目前部署与健康通过，**未触发回滚**，旧镜像和私有备份可用。若后续仅文档生成失败，先核实失败范围及既有提取/录音能力，保留具体回执，不能掩盖未通过项。需回滚时等待全部任务终态，按审核方案恢复原Skill（移除原先不存在的reference），核对旧镜像ID，使用完整原四Compose集合重建Worker、移走候选override至备份；Gateway仅确有重建或缓存问题时恢复并受控重建。禁止恢复旧数据库覆盖新任务，禁止删除原件、cache、saved或模型。受限调用失败不得用扩沙箱或提限额处理。

本报告停在真实QQ请求等待阶段；全册、永久保存和知识库均未授权执行。

## QQ反馈后的执行环境澄清

用户转述小爪反馈：用主机Python探针认定模块/模板缺失，并提议手工XML及占位PDF。该反馈没有提供真实filetools_python失败job。再次核对运行中Worker仍为审核dc7bb...镜像、HEALTHY/active_workers=0；只读限定两个测试文件的登记表任务，仍仅管理员预检61cd...，未找到新的QQ受限生成任务。不能据主机探针判定Worker未部署，也不能将该反馈解释为真实受限调用已失败。转述中的“空入站”尚无独立证据，本次不读取无关会话日志或伪造入站。

增量更新Skill/reference：明确预装模块属于Worker filetools_python，主机/其他exec沙箱不代表该环境；严格FILETOOLS_INPUT；只有真实受限任务回执才能报告该调用失败；拒绝手工XML/占位PDF烟测；本轮已核实五页输入包可直接generate，不重读169页OCR或重新填写verified证据。生成器、候选镜像、模板、限额与配置不变，Gateway不重建。

更新前两文件保留权限/所有者，另备份到原私有部署备份目录的skill-context-correction-20261006/file-workspace；原最初回滚备份不覆盖。当前生产Skill SHA `73992b3af93ea8154145e741ecb32de23d899fbb504b128b63389e42a09ffc3b`，reference SHA `cfee4fa7b7a756adc33f81ed1c04d1af1986905b75abf7053012dbc61710a18a`；Skill校验通过。等待用户新QQ消息明确执行正式登记及受限调用，仍未标记QQ生成/附件/视觉通过，不触发回滚或扩权限。

## 真实QQ Worker探针已核验，文档生成继续等待

用户返回新任务58ae3a7169214aa7b54fd62ee43ce252，created_at=2026-10-06T12:18:51.318362+00:00。只读数据库及实际status均SUCCEEDED；通过真实管理files/artifact_path取回指定worker-probe.json，artifact_id=10c71d5c42e14b3a92f7007f8e00583a、file_id=687f5ad0c7504c63b39d2700019abc75。实际59字节、SHA `4b8ce34f331899aaf0ec6c982d964bbc2ac15a02fec9efc3436d1a148421e51a`与用户回执及正式引用一致，内容记录questions-zh-cn/1.0.0和font_present=true。这是新真实生产受限任务，用户反馈来自QQ；本次不伪造入站，管理员取回核验也不等于QQ附件下载通过。探针未生成文档，不用于声称短文/32题视觉或生成性能通过。

再次核对已准备业务输入包在Chen工作区：document-production-p6-p10-20261006.review.json，37053字节，SHA `bfcf84934a42fef6cc9eaeef355d0dd333e402cf9180fd34096e4c84417ba5ad`，与开发发布的独立输入包一致；仅原6–10页旧OCR、28条独立修订、19条页边证据和疑点记录。原OCR SHA仍9ca6e82cd2749b68ab3dffbd09735c235a7cccff5b59a1802a67eaf233a39f70，模板ID/版本仍questions-zh-cn/1.0.0。原核对记录继承，不要求此次Agent重新声明核对事实；不存在追加原文修订。此包可直接filetools_register({source_root:"workspace",source_path:确切文件名,mode:"snapshot"})，然后以返回attachment_id提交预装generate_registered_input及七项outputs。无需169页旧OCR登记、prepare_registered_ocr或重新制作包。

继续等待用户真实QQ请求生成合成中文Word/PDF及同一32题小样本；样本附件交付、独立渲染、客户端下载和Word字体替换仍未验证。镜像/配置/限额不变，无重建、回滚、全册或永久保存。

## 合成生成失败定位：缺少原文输入，未进入排版

用户报告任务5a4d9fb2ba3f49da8c619ea85f714f8e FAILED/SCRIPT_FAILED/artifact_count=0。管理员只读核对该任务登记记录、指定目录文件及私有stderr；不扫描其他任务、不对Agent开放私有目录。实际输入为document-production-smoke-test-20261006.review.json，818字节，SHA `e7e358edcc7735344c65b26ac81fb45da723e36b2171a28965a86cfdd6cd84d9`，由QQ测试新增，**不是**此前准备的五页包。实际代码为预装generate_registered_input两行调用。

私有execution/stderr.log明确记录ValueError: DOCUMENT_INPUT_SCHEMA_OR_EXPLICIT_SCOPE_REQUIRED，堆栈指向document_entry.generate_registered_input的validate_request阶段。输入包含document和证据列表，缺少必填顶层raw_ocr字符串，因此入口拒绝，尚未运行排版。stdout为空、operation.py及stderr实际存在但没有发布。artifact_count=0仅证明无正式发布产物，不能据此断言没有执行日志或函数不可用。此次故障不据Fault推断内存/限时/模块缺失。

纠正范围为业务输入，不改模块、镜像、配置、模板或沙箱。新增独立合成输入document-production-smoke-valid-20261006.review.json，730字节，SHA `bd3bd18744ab923674b3997abcc5854e3696480e205d7ffa574d9d0dcbb13f94`，包含真实合成原文（1题4选项）和显式模板/范围；证据列表为空，不捏造原PDF修订。已在不挂生产目录/socket的隔离候选容器用预装入口生成全部七产物，native内容一致、1页PDF；这是独立开发入口验证，未使用真实生产Landlock/QQ调用，不能当成生产受限重试或视觉验收。合成来源Page 1是测试页，不是原册核对声明。正常Chen工作区新增该业务副本，失败原件及五页包保留。

新增有效document元数据但缺raw_ocr时不生成任何产物的回归；隔离开发17项输入/模板测试通过（5条上游SWIG警告），Skill校验通过。reference增量说明原文必填及零发布的诊断边界，备份在原私有备份目录skill-input-diagnostic-20261006/file-workspace。Skill SHA保持73992b3af93ea8154145e741ecb32de23d899fbb504b128b63389e42a09ffc3b；当前reference SHA `a8bfcb485a7292590a5665c337774aeba1d169aabca7db959bff739253566608`。最初回滚备份不覆盖。

失败范围已定位到此合成包的输入校验；没有新证据显示既有提取/录音失败，也没有重新运行这些重任务，不能声称本轮已实测所有旧能力。无重建、回滚或限额提升。等待用户QQ登记修正后合成包，再经真实filetools_python生成并正式交付，成功后同样登记现成五页包；仍需独立取回生产文件实际渲染和客户端下载反馈。原始OCR与修订记录未覆盖、全册未处理。
