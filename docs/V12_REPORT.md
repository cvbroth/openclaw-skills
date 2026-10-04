# OpenClaw FileTools V1.2 开发交付报告

本轮完成本地源码、测试、插件/通用 Skill、安装诊断与迁移回滚入口。没有连接或部署生产服务器，没有修改现有检索仓库、生产 OpenClaw/QQBot、Embedding/索引或私人/Family 导入链路。没有推送 GitHub、创建 PR 或执行远程 CI。

## 基线与审查入口

| 项目 | 核对结果 |
|---|---|
| 开发仓库 | cvbroth/openclaw-skills |
| V1.1 基线 | ec6ea15f2ec833473bc776cbbb3e7f533ae86373 |
| 前序 V1 | 87f93acad75c7b92a091fe673e67326d6d640143 |
| 开发前远程 main | 83014f7843f0fe0bcfbf872b3a3cf22c7cbd2d6f；V1.1 分支与本地基线一致 |
| 本轮分支 | feat/filetools-v1.2 |
| 参考检索项目 | 623aa73abcd0dc7f4854a58a8a42e8b6c4725072，tracked 文件未修改 |
| 开发约束 | 已检查仓库开发文档；未发现 AGENTS.md/CONTRIBUTING.md；完整读取用户 V1.2 要求 |

最终源码提交号在外部交付 `COMMIT.json` 和 Git bundle 记录；该报告随源码提交，不把自身提交号写成循环占位。交付报告副本会写出完整提交号。源码ZIP是该提交的git archive，不含虚拟环境、模型、node_modules、测试业务文件或凭据。

审查顺序：[方案](V12_PLAN.md) → [架构取舍](V12_ARCHITECTURE.md) → [工具/产物契约](V12_INTERFACE.md) → [安装诊断迁移回滚](V12_INSTALL.md) → [验证复现](V12_TESTING.md) → [生产验收](V12_ACCEPTANCE.md)。另有 [支持与限额](V12_SUPPORT.md) 和 [普通用户指南](V12_USER_GUIDE.md)。V11文档保留为历史版本。

## 最终实现

核心保持成熟PDF/DOCX/OCR/ASR引擎，仅整理管理、运行和发布边界。一人一Agent；没有新账号、角色、管理网页、办公平台、MCP或下载服务。每Agent实际工作区有 `filetools/{snapshots,cache,saved,registry.sqlite}`；main/chen不合并、不跨Agent去重。

可信Gateway固定管理CLI负责登记/复制/保存；源码共享安装一次，用Python标准库即可运行管理。独立worker处理重任务，全局并发1；仍用Unix socket HTTP。正常任务只传登记ID和参数，不再次上传原件。处理容器只挂Agent的filetools子树、固定模型、socket/配置及明确NAS只读引用根。

登记支持配置根内绝对/相对路径、已有file_id复用、snapshot/reference。snapshot完整SHA同Agent去重，保留接收事件，尝试reflink失败安全复制；不是硬链接。reference保留根/相对路径/版本与SHA，缺失、变化及未挂载明确报错，不删除外部原件。分类涵盖pdf/word/text/images/audio/video/spreadsheets/datasets/archives/other；分类不代表专用解析已支持。

目标SDK真实注册10个工具：register、inspect、extract、status、cancel、read、find、files、python、save_minutes，前缀filetools_。模型参数没有Agent/user/session/注册表根；身份来自可信绑定和实际会话代次。旧渠道到达适配保留，支持canonical path及可信workspaceDir相对引用；附件本身只登记、确认、等待需求，不自动提取或入库。只开放明确绑定私聊，群聊拒绝。

临时Python本次输入只读、本次执行目录可写。Linux用Landlock ABI≥3/seccomp，拒绝登记表、saved、其他任务/Agent、发布区与网络访问。先回收子进程，再校验、同文件系统原子发布、登记正式输出，返回Gateway真实路径。Windows用Job Object、正常退出也结束整个进程树；development不冒充文件/网络沙箱。Linux监督进程与worker都设subreaper，取消后对已记录后代定向waitpid，Docker部署启用init；未完成回收拒绝确认。

MD/TXT正文按实际内容/UTF-8/大小判断可读，Python output标签不再导致拒绝；XLSX返回可实际读取的文件。普通read路径可用，已知read/read_file钩子提供短租约与成功续期；任意OS/shell读取不可观测，Skill要求真实使用后touch。status/no-hit/失败不续期；过期或丢失产物不再显示可用路径。保存版本有独立文件ID、来源和图片依赖，缓存清理后仍可读。

安装是一个配置和入口，发现实际Agent工作区/Docker bind/UID/GID；兼容agents.entries和旧agents.list，缺省用目标SDK agents list查询。仅改变专属子树所有权，两个运行配置均为实际UID/GID及0640。不存在/空plugins.allow保持开放语义，非空才追加；渲染Compose检查现有Gateway镜像和worker必要挂载，保留原插件/知识库挂载。诊断检查每Agent双容器可见性、登记表/socket/引擎/插件loaded，仍不把诊断当QQ全链路验收。

## 要求覆盖

| 流程/问题 | 实现与本地证据 |
|---|---|
| 普通附件→登记→范围处理→来源读→保存→清缓存 | 共享布局真实PDF/DOCX/图片/录音用例；PDF页码/音频时间；保存文本独立读取 |
| 重复请求/接收/现有快照或产物 | 请求幂等、同AgentSHA去重、接收事件保留、产物直接关联无重复快照；main/chen实际独立SQLite |
| 无任务附件、NAS目标、来源不可信 | SDK钩子/注入渠道上下文回归；只登记不提取；reference实际文件变化/删除拒绝旧结果 |
| 相对路径、根边界、变化/未完成/权限 | 真实CLI与文件、复制期间实际变更、Linux真实symlink及无读权限；文本伪造/SDK身份字段由测试注入 |
| shared目录与IDs控制、MD/XLSX取回 | 本地双容器真实Unix HTTP/共享卷；Gateway管理替身实际read/hash/ZIP核对XLSX单元格 |
| 子进程正常/失败/超时/取消 | Windows Job Object；Linux实际Landlock对应回归，延迟写入与PID消失；development双fork/setsid真实回收 |
| 访问/过期/清理/重建 | 成功read/touch续期、轮询不续期、租约/活动输入保护；缓存过期和丢失显式状态；原件/saved保留 |
| 白名单/镜像/兼容 | 3种allow策略模型测试；实际SDK工厂/生命周期测试；参考知识插件49项通过；真实生产loaded与活跃调用仍待验收 |
| 安装、迁移、回滚 | 本地std-only安装/诊断、实际旧业务目录迁移、saved独立/未知Agent暂停；生成Compose/配置替身回归；实际Gateway安装/回滚未运行 |
| 大文件/长音频 | 201MiB真实写入/独立快照/full SHA；4GiB计数；4小时计划/块恢复部分模拟，真实录音仅短英文 |

## 测试结果与证据

最终批次以 `docs/evidence/v12-verification.json`、JUnit和日志为准；通过数不是生产能力清单。

| 检查 | 最终结果 | 边界 |
|---|---|---|
| Windows Python全套 | 75通过，19跳过，0失败 | 项目虚拟环境；默认真实引擎未开启；跳过Linux/socket/权限等 |
| 本机Docker Linux全套 | 93通过，1跳过，0失败 | 离线真实引擎开关已开启；其中10个真实引擎用例；唯一跳过Windows专属能力检查 |
| Windows真实引擎专门批次 | 10通过，0跳过 | 合成文档/图片及固定JFK英文11秒；非中文长录音 |
| 最后补充过期纪要检查 | 2通过，0跳过 | 全套之后增加过期save_minutes拒绝保护，针对过期路径和正常保存闭环回归；不重复累加全套数量 |
| 插件SDK/管理集成，Windows | 15通过，1跳过 | 2个真实Python核心/worker桥接；身份/渠道传输为注入；Linux会话锁用例跳过 |
| 目标SDK生命周期，Linux | 14通过，0跳过 | 实际SDK会话存储及注册入站钩子；测试事件/客户端仍注入 |
| 双容器共享目录/socket | PASSED | 管理替身与真实worker，同UID测试卷；实际MD/XLSX读取、保存/清理/隔离；未发QQ |
| 参考知识库插件 | 49通过，1跳过 | 原检索仓库测试，Windows symlink权限跳过；不是在线检索服务验收 |
| 静态/依赖/Skill/插件 | PASS | ruff、compileall、pip check、Skill验证、真实SDK build/validate、git diff --check |
| GitHub CI | 未执行 | 已更新工作流，推送后才会运行 |
| 生产OpenClaw/QQ | 待验收 | 没有生产连接，真实发送/下载、实际启用状态未确认 |

开发中实际发现并修复：Windows只读产物故障注入需要正确清除只读属性；共享输出fsync使用可写句柄；reference inspection不得复用未校验源版本；保存输出必须分配独立产物ID；两个运行配置的所有权/模式；过期路径不应作为可用产物；Linux取消路径留下被杀死但未回收的僵尸后代。报告只引用修复后的最终批次，中间失败不会被算成通过。

真实Linux在本机Docker Desktop/WSL2 `6.18.40.1-microsoft-standard-WSL2`、x86_64，Python3.12.10；运行时network:none/cap-drop ALL/no-new-privileges，2CPU/4GiB。源码只读挂载，测试文件在容器内部/tmp；固定模型只读。Dockerfile实际构建通过；本地镜像不是交付物，部署必须从最终源码重新构建并记录digest。apt实测FFmpeg7:5.1.9-0+deb12u1、libseccomp2 2.5.4-1+deb12u1；底层tag/apt随时间可变，不声称无限期位级复现。

## 真实引擎计时

Windows开发机Python3.12.3；Linux为同开发机的本地虚拟容器，线程2/重任务1/CPU2。表为整任务wall秒，包括子进程启动/模型加载；不是受控硬件基准，未测NAS峰值、未推算Xeon速度。DOCX因为图片-only正文块未识别而PARTIAL，图片仍保留。

| 自制/许可样本 | Windows秒 | 本机Linux秒 | 结果 |
|---|---:|---:|---|
| text.pdf，2页 | 0.890 | 1.941 | SUCCEEDED |
| scan.pdf，1页 | 2.828 | 2.484 | SUCCEEDED |
| mixed.pdf，3页含混合页 | 4.031 | 3.728 | SUCCEEDED |
| ordered.docx，段落/表格/图片 | 1.328 | 2.254 | PARTIAL |
| printed.png，印刷字 | 3.547 | 2.516 | SUCCEEDED |
| notes.md | 1.000 | 1.034 | SUCCEEDED |
| jfk.flac，英文约11秒 | 6.156 | 8.414 | SUCCEEDED |

源样本与时间/状态/SHA在脱敏benchmark JSON；具体公开音频固定于 [Whisper测试样本提交](https://github.com/openai/whisper/tree/86098128c0b4f24f0e2aa2994de830614b474227/tests)，下载脚本同时保存MIT许可与来源SHA。small模型固定revision536b0662742c02347bc0e980a01041f333bce120，CPU int8，运行离线；RapidOCR wheel带ONNX模型。

## 模拟、限制与待验收

1. 四小时音频只是生成计划元数据；24秒分块/断点用真实FFmpeg与注入ASR。3–4小时中文真实录音、整本OCR、NAS CPU/内存/磁盘峰值 **未执行**。4GiB完整吞吐 **未执行**，不能用201MiB或计数测试替代。
2. channels/sender/session事件、发送回执、部分失败/超限、Docker发现命令及allow有效性谓词存在替身。Linux SDK会话数据库是真实，客户端仍是注入。双容器Gateway是管理替身；没有目标managed Gateway完整端到端。
3. 已核对目标 [QQBot v2.0.3渠道适配](https://github.com/tencent-connect/openclaw-qqbot/blob/v2.0.3/src/channel.ts) 和 [媒体发送源码](https://github.com/tencent-connect/openclaw-qqbot/blob/v2.0.3/src/outbound/media-send.ts)：现有sendMedia链路处理允许根内本地文件并路由sendFile；本插件复用现有message入口及Gateway文件引用，没有另造发送服务。**真实QQ发送权限、最终落盘、回执和客户端下载仍待生产验收**。模拟回执不能称已发送。
4. 当前群聊拒绝；一人一Agent私聊绑定验证后启用。主机sandbox off，普通read/exec权限由既有OpenClaw管理；本工具不宣称整个Agent工作区天然隔离。
5. Windows development无文件/网络隔离，只用于受信本地测试；生产必须Linux Landlock+seccomp，缺失明确失败。首次下载/模型/镜像需网络，准备后运行离线；不能向现有检索虚拟环境或Gateway临时装依赖。
6. reference完整SHA校验对大文件有I/O成本；reflink仅尝试，普通复制仍安全但占独立空间。源上传需遵循关闭/最终名发布约定，工具不能凭大小不变证明上传已完成。
7. DOCX图片保留但不自动OCR；页眉/脚注/批注/修订/复杂表格和布局未可靠覆盖。扫描PDF非空文字不证明完整。照片画面、手写、公式、多栏阅读顺序不承诺可靠。
8. V1.1迁移保留旧cache/任务/音频检查点原处；不把旧路径任务伪装成新布局可续作。持久快照和saved复制校验，可新任务重处理；长任务停机前应保存或在旧worker完成。未知Agent暂停，不自动合并身份。失败复制保留诊断文件/旧数据，管理员审查后再恢复。
9. 实际NAS上的Compose增量安装/回滚、已有插件loaded/活跃工具、实际用户权限效果未运行。JSON5不重写；需要可审查JSON。没有部署就没有“部署通过”。
10. V2只记录MD/简单文本生成Word/PDF及保版式转换风险路线图；本轮不做上述转换、不自动向量入库、不扩大办公平台。

## 后续生产信息及步骤

已知硬件/版本无需重复提交。只需补真实sender/account/启用Agent绑定、Gateway实际UID/GID与已有Python路径、Compose来源、允许的NAS根、QQ canonical落点和发送工具权限；提供匿名真实中文录音/代表性附件后记录实测。最少只读命令在INSTALL，避免分享凭据/完整配置或私人正文。

管理员后续按INSTALL先计划和备份，再安装、诊断；按ACCEPTANCE核查逐Agent共享目录、原QQ/知识库工具、私聊/群聊拒绝、真实发送下载、长任务/资源与恢复。回滚保留新增业务filetools、模型/迁移备份，恢复旧插件和Compose，不丢新业务文件。迁移与回滚有明确CLI，不要求用户手写.ready文件。

## 本地提交与手工推送

已提供本地feat/filetools-v1.2提交、Git bundle、V1.1→V1.2补丁、源码ZIP、COMMIT.json和SHA256SUMS。完整仓库目录所有权由Windows隔离账号产生时，只信任这个具体目录，勿设safe.directory通配符。确认仓库后可手工推送：

```powershell
git config --global --add safe.directory C:/Users/18296/Documents/Codex/2026-10-03/nas-openclaw-v1-https-github-com/work/openclaw-skills
Set-Location 'C:\Users\18296\Documents\Codex\2026-10-03\nas-openclaw-v1-https-github-com\work\openclaw-skills'
git switch feat/filetools-v1.2
git log -1 --oneline
git push -u origin feat/filetools-v1.2
```

上述是用户后续操作指令，本轮没有执行push。不要把V1.2强行覆盖main；先审查差异与生产验收材料。
