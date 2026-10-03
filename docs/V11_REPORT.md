# OpenClaw FileTools V1.1 开发交付报告

执行：2026-10-03 至 2026-10-04，Asia/Shanghai。本版完成本地开发与可用环境验证，未连接生产、未部署、未改生产配置/数据，也未修改现有检索仓库。Linux/Docker/QQ 生产可用性仍需验收，不能将本报告当成已上线证明。

源码版本为 nas-filetools / 插件 1.1.0，分支 `feat/filetools-v1.1`。最终提交号在随交付生成的 `COMMIT.json` 和 Git bundle 中记录；报告处于该提交本身，因此不把自身提交号写成循环占位。外部交付报告会列完整提交号。没有本轮远程推送授权，未推送 GitHub。

## 基线与核对

| 项目 | 本轮基线/目标 |
|---|---|
| openclaw-skills V1 | `87f93acad75c7b92a091fe673e67326d6d640143`，来自 feat/filetools-v1 |
| vector-search-engine | `623aa73abcd0dc7f4854a58a8a42e8b6c4725072`，只读参考 |
| 本地真实 SDK | OpenClaw 2026.9.4，Node 24.16.0 |
| 用户确认的生产目标 | OpenClaw 2026.9.4 / 3a9d69d、QQBot v2.0.3、Ubuntu26.04 x86_64、现有 Docker 自定义镜像 |

读取两仓库开发说明、README、现有引擎、插件/Skill、可信身份/附件登记、查询及授权导入接口。未发现 AGENTS.md/CONTRIBUTING。公开 GitHub API 再核对 V1 分支及检索 HEAD，均与上表一致，没有后续 V1 修复被遗漏。一次 git fetch TLS 中断未拿到新 refs，随后用公开 API 校验；不将失败 fetch 说成成功更新。

实施顺序为：基线/接口核对 → Agent 文件区与流式归档 → 生命周期和 V1 缺陷回归 → 长音频与通用 Python → 部署/诊断/迁移/回滚 → 真实引擎及分层测试 → 本地源码提交和交付。

## 关键改动与取舍

1. 沿用可信 QQ sender/account/channel → Agent 映射。配置只需数据根、已有 Agent、已有可信绑定；没有第二套账号密码或管理网站。快照/保存按 Agent，任务按真实 sessionKey+sessionId；群聊、陌生身份及缺可信上下文拒绝。
2. 到达事件后台归档、流式哈希和登记，再按用户任务提取。只有附件时等待指令；同消息附任务可继续。独立 inbox/snapshots/cache/saved 与十类目录，未知格式可以归档但不假装已支持解析。
3. 同 Agent 全 SHA 去重、每次上传事件、稳定 file_id；会话 attachment_id 和 job_id 权限分别管理。并发复制、失败登记、缺失快照及已提交精确删除中断有回归。快照和注册长期保留，避免 V1 幽灵文件。
4. 闲置 TTL72h、每小时清理；有效读取/使用续期，状态/健康/无命中不续期。活动任务/读取保护。新会话可明确 list/select 自己的历史文件；缓存过期从快照重提取。
5. 保存完整来源/图片依赖束，MD改相对链接；保存失败保留缓存，版本不覆盖，原件删除不删保存成果。转写原文与模型纪要分开，保存不触发任何向量导入。
6. 音频按600秒+2秒重叠解码与转写、释放数组、检查点校验配置与原件、全局词时间归属、失败区间标记及 resume。整个服务并发1，CPU-only2线程，预算分总处理时长与无进展超时。
7. 通用 filetools_python 补充 Excel 等操作：处理登记原件副本、保存脚本/日志/操作来源、检查输出/声明断言，保留XLSX。专用提取优先，不写每种Excel业务工具，不自动联网装依赖。执行子目录与权威来源发布目录分开，避免脚本伪造任务结果。
8. 独立 SQLite、进程、Python3.12 worker镜像和固定离线模型。Linux Landlock/libseccomp、进程限制、Docker cgroup/pids为生产边界；Windows development 模式只用于可信测试，目录和提示词不是沙箱。
9. 真实 SDK 注册9个工具与入站 hooks，Skill更新问答/保存/历史选择/脚本操作规则。中央Limits由capabilities传给CLI/JS；4GiB原件与512KiB控制文本分开，11,000汉字纪要回归通过。调度器异常停止服务，spawn失败落FAILED，排队启动再检查容量。
10. 单入口安装计划/apply及诊断，自动识别已有Compose/持久挂载/UID/GID、保留自定义镜像和其他插件/模型配置；备份、增量Compose、独立依赖与模型准备。V1迁移预览、独立新根、旧SQLite备份、可信owner映射、旧接收时间保留；回滚恢复运行环境并保留新数据，拒绝覆盖安装后的其他配置修改。

资源默认：接收4GiB、完整音频6h、PDF10000页、重任务1、2线程/4GiB、每Agent快照100GiB/保存50GiB/缓存20GiB、磁盘预留1GiB/80%告警。页数、像素、解压、文本、输出、控制请求、返回长度及任务预算独立限制，详见接口文档和 deploy/filetools.example.json。没有估算或承诺 NAS 实际处理速度。

## 实际测试与证据边界

最终执行统计见 `docs/evidence/v11-verification.json`；命令对应的 JUnit 与插件文本输出随源码提交。下表类别不能相互替代。

| 类别 | 实际结果 | 验证边界 |
|---|---|---|
| 静态/依赖/格式 | Ruff、compileall、pip check、git diff检查、Skill校验通过 | 不证明引擎或生产运行成功；PyMuPDF有5项SWIG弃用提示 |
| Python全量回归 | 60通过、3跳过，51.47秒；另补充inbox标记边界定向1通过 | 包含下述真实文件/引擎和故障注入；Linux项跳过；补充脚本定向6通过与全量重叠，不能加总当新用例 |
| 真实 OCR/ASR | 4项引擎测试通过 | 扫描PDF、混合PDF、印刷图、11秒英文JFK全文/时间范围，CPU int8离线small模型 |
| 真实文件与后台处理 | PDF/DOCX/MD，601页PDF末页范围，201MiB流式inbox登记、去重/SHA，真实Python XLSX计算列/多表/原件未变，通过 | 201MiB是写入和复制实际字节；未做完整4GiB传输，Windows未施加Linux内存/cgroup限制 |
| 生命周期/失败恢复 | 保存依赖/版本/失败，TTL/清理/取消/重启，Agent/会话拒绝，11000汉字纪要，通过 | 实际本地SQLite/文件/工作进程；失败、时间推进和进程启动异常等使用受控故障注入 |
| 长音频边界 | 生成4小时区间计划、生成音频真实FFmpeg分段解码+注入识别器的重复归属/检查点/部分失败，通过 | 不是3–4小时真实ASR，不证明中文准确率；短录音ASR是真引擎 |
| 脚本资源 | 实际崩溃、无输出、超时、输出超限、XLSX目标断言通过 | Windows可信development测试；Linux文件/网络/内存限制未实测 |
| 安装/迁移本地行为 | 重复工作区初始化/旧数据保留、真实V1 SQLite迁移/备份、标准库无site-packages入口，通过 | local-only明确runtime_installed:false/runtime_verified:false，不是Docker安装成功 |
| 运维恢复模拟 | 2项：真实文件备份/恢复、配置摘要冲突拒绝、原自定义Compose/持久配置预检，通过 | Docker响应和owner修改为模拟；没有容器/UID/GID/Linux真实回滚 |
| OpenClaw插件 | 14通过、1跳过；真实2026.9.4插件build/validate通过 | 真SDK工厂/声明；可信事件和传输大部分注入，1项调用真实Python核心。不等于Gateway/QQ端到端 |
| 知识库插件回归 | 49通过、1跳过，参考仓库跟踪文件干净 | 本地现有插件契约测试；不代表生产检索/导入已验收 |
| GitHub CI | 未执行 | 工作流已更新为V1.1，含Linux真实服务/隔离与固定样本/模型测试；没有伪称远程CI通过 |
| Linux/Docker/QQ/NAS | 未执行，待验收 | WSL不可用、Docker Linux引擎未运行；本轮没有连接生产弥补环境不足 |

Python跳过：Windows符号链接创建、真实Unix服务协议、真实LinuxLandlock/seccomp。插件跳过：实际SDK会话存储生命周期锁。知识库跳过：符号链接。实际Linux运行不能由这些跳过项或mock推导通过。

针对需求的可审查入口：

| 要求 | 主要源码/测试入口 | 当前证据 |
|---|---|---|
| 初始化、流式归档、去重、Agent隔离、未知格式 | workspace.py/catalog.py；test_v11.py 初始化/类型/201MiB用例 | 真实本地文件与SQLite；渠道到达为插件模拟事件 |
| 到达即归档、附件与指令同消息、真实会话代次 | runtime.mjs/index.mjs；runtime.test.mjs 到达/epoch/绑定用例 | 真SDK+模拟上下文；QQ/session-store真实运行待验收 |
| V1健康假正常、启动失败、新会话配额、纪要字节限制、幽灵文件 | worker.py/service.py；test_v11.py scheduler/start/11000/TTL，runtime.test.mjs epoch quota | 故障注入及真实核心行为通过；Linux监督恢复待验收 |
| 缓存续期/清理/重建、保存依赖/失败/版本、精确删除 | workspace.py/store.py；test_v11.py TTL/saved/active/interrupted_delete | 真实文件与后台任务，受控时间/失败注入通过 |
| Python副本编辑与输出检查、失败/超时/资源限额 | scripts.py/script_launcher.py；test_v11.py python_xlsx/script_* | 真实Windows脚本；Linux强隔离/内存限制待验收 |
| 长音频分段/检查点/全局时间/部分失败，大册指定页 | audio.py/engines.py；test_audio_chunks.py，test_v11.py large_pdf | 真短ASR/真实601页PDF；长ASR生成/注入边界，生产性能待验收 |
| 部署/诊断/迁移/回滚、既有知识库兼容 | operations.py/diagnostics.py/filetools_admin.py；test_operator.py/test_v11.py；参考仓库原插件测试 | 本地迁移真文件、Docker恢复模拟；Linux运行与现有生产服务待验收 |

这些入口用于审查代码和重现，不将缺失的环境验收补成通过。

## 真实引擎耗时

完整记录 `docs/evidence/v11-engine-benchmark.json`。这是Windows开发机单任务CPU工作进程墙钟（含spawn/模型加载及I/O，系统缓存可能已热；并行测试可能影响耗时），不是Xeon NAS测速，不含QQ上传。

| 样本 | 结果 | 秒 |
|---|---|---:|
| 自制文字PDF，2页 | SUCCEEDED | 0.875 |
| 自制扫描PDF，1页 | SUCCEEDED | 2.860 |
| 自制混合PDF，3页 | SUCCEEDED | 5.157 |
| 自制DOCX，表格/图片/5正文块 | PARTIAL | 2.375 |
| 自制印刷文字PNG | SUCCEEDED | 2.984 |
| 自制UTF-8 MD | SUCCEEDED | 1.454 |
| 固定许可英文JFK FLAC，11秒 | SUCCEEDED | 11.359 |

DOCX的PARTIAL如实标明图片未OCR，文本顺序与图片附件保留，没有称完整还原。录音来自 OpenAI Whisper MIT仓库固定提交 `86098128c0b4f24f0e2aa2994de830614b474227`；SHA256 `63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715`，下载脚本/许可记录可复现。文档与图片为自制样本；字体依赖开发机Arial或Linux DejaVu。Whisper模型固定revision `536b0662742c02347bc0e980a01041f333bce120`，准备清单记录文件SHA；同路径不允许更换模型内容后复用结果。

## 未验证项与已知限制

- Linux安装apply/diagnose、真实容器挂载/UID/GID、内核Landlock/seccomp、进程树取消/内存/pids、实际SDK会话存储、QQ接收到回答，全为待验收。安装入口已有实现和本地/模拟验证，但尚无真实Linux安装成功证据。
- 中文/方言/噪声/手写/公式/复杂表格/真实家庭附件，3–4小时真实ASR、6小时资源边界、4GiB完整传输与NAS真实速度，待验收。无匿名真实样本不阻塞开发，但不能补写为通过。
- OpenClaw canonical media不含独立原始客户端filename；记录可信暂存basename及消息ID。若渠道改名，原名可能无法还原，需生产核对。QQ原生语音可能只有URL或已有转写；没有可信本地原始字节就不能归档。本版不自行下载任意URL；音频文件附件/inbox可用。
- 既有自动附件预览可能仍运行；插件Skill避免再次主动提取同任务，但需真实Gateway核对是否发生自动重复处理。
- 分类不等于解析。正式提取支持PDF、DOCX、UTF-8 MD/TXT、PNG/JPEG/WebP/BMP/TIFF、MP3/M4A/WAV/FLAC/OGG；DOC/XLS/ODS/数据集等未提供通用解析，只可归档或在能力范围内受控Python补充。DOCX页眉/文本框及图片文字、扫描复杂阅读顺序不保证完整。
- 脚本输出验证只覆盖声明断言，不证明所有业务语义；openpyxl不重算公式，宏/图表/复杂版式未承诺保留。XLSX保存后可取得元数据，本版没有自动QQ二进制回传。
- 目录不是强隔离，同UID不受控exec或socket持有者仍处于可信权限边界。需审查既有Gateway exec策略，不能开放服务socket/数据根到公网。Windows development脚本只跑可信代码。
- 配额为使用量检查与任务启动检查；脚本总输出/引擎日志用轮询，可能短时超过阈值，不是硬文件系统配额。崩溃的未登记暂存/快照残留计入物理容量，保留诊断，管理员核对后清理；inbox原文件不自动删除。
- 自动安装仅支持目标Linux Docker/Compose及标准JSON Gateway配置；单文件配置挂载无法提供持久插件目录时明确拒绝。JSON5、未可读Compose、多候选或后续配置修改，需要管理员提供兼容路径/选择/合并。默认安装仍需Docker/目录管理权限、网络构建/首次模型下载和Gateway重建。
- 保存区没有新建登录/文件浏览网站；Samba权限配置和保存成果交付由现有NAS运维提供。新格式不能原地交给V1；回滚必须恢复旧运行环境并保留新根。

## 安装、诊断、迁移与回滚入口

完整步骤、前提和副作用见 [V11_INSTALL](V11_INSTALL.md)。单份配置示例 `deploy/install.example.json`，管理员替换实际data_root/Agent/QQ可信绑定；不能把示例sender上线。

```bash
python3 scripts/filetools_admin.py install --config /etc/nas-filetools-install.json
python3 scripts/filetools_admin.py install --config /etc/nas-filetools-install.json --apply
python3 scripts/filetools_admin.py diagnose --config /etc/nas-filetools-install.json
```

第一条仅预检/计划，后两条须在后续获得部署授权的环境执行，本轮未执行生产命令。迁移默认预览，原件SHA和旧owner映射核验通过后备份SQLite/复制新根；回滚使用安装生成的rollback.json恢复旧插件/配置/原Compose，只停新worker，保留新产物。卸载默认保留全部数据，清理只针对缓存。

普通用户首次使用、大文件完成标记、保存/删除/表格例子见 [V11_USER_GUIDE](V11_USER_GUIDE.md)。完整来源与参数见 [V11_INTERFACE](V11_INTERFACE.md)，重要取舍见 [V11_ARCHITECTURE](V11_ARCHITECTURE.md)，后续验收逐项见 [V11_ACCEPTANCE](V11_ACCEPTANCE.md)。历史V1文档已加版本说明，不能再拿旧64MiB/500页/七工具限额当V1.1现状。

## 后续需要的生产信息和证据

已知硬件/版本无需再次提供。部署前仍需：现有Compose源文件/服务名与持久state挂载、Gateway真实运行UID/GID、标准JSON配置位置、每人Agent及QQ channel/account/sender可信绑定、各Agent工具allow/deny与exec策略、专用数据根/磁盘空余/个人Samba inbox权限、是否可首次联网下载镜像/模型、内核Landlock ABI及libseccomp。提供信息时隐藏token/password/env值。

需要匿名真实PDF/DOCX/图片/中文录音与预期答案，以及真实私聊入站canonical media/会话代次证据。群聊本版验收目标为保守拒绝；如要群聊可用，另开授权设计。本轮未扩展V2文档生成/版式转换，仅保留路线图。

## 源码交付与手动推送

交付Git bundle、源码ZIP、COMMIT.json、SHA256SUMS、报告/用户/运维/接口/架构/验收文档和测试证据；不包含虚拟环境、node_modules、模型缓存、生产配置或大测试原件。验证bundle和校验和后可审查或重新clone。未创建/推送PR。

当前Windows开发仓库可由用户手动推送；若再次遇到V1的dubious ownership，仅为这一个已知目录添加safe.directory，不要设置通配符：

```powershell
git config --global --add safe.directory C:/Users/18296/Documents/Codex/2026-10-03/nas-openclaw-v1-https-github-com/work/openclaw-skills
Set-Location 'C:\Users\18296\Documents\Codex\2026-10-03\nas-openclaw-v1-https-github-com\work\openclaw-skills'
git switch feat/filetools-v1.1
git log -1 --oneline
git push -u origin feat/filetools-v1.1
```

推送只上传开发分支，不是生产部署；GitHub CI需在推送后另看真实结果。
