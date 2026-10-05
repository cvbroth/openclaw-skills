# 服务器录音 Skill 增量更新

日期：2026-10-05。接手基线 `9e853e857112816146153a423f640bc3dbbd5027`，独立分支 `docs/filetools-recording-workflow-20261005`。沿用现有 FileTools 架构，只改 Skill 和必要说明，不改工具 schema、处理引擎或模型，不部署生产，不更改运行服务、生产配置或生产镜像标签。

## 接手与工具核对

命令实际位于服务器 `myserver`、`/home/chen/dev/openclaw-filetools-dev`，账号 UID/GID 1000；HEAD 一致、初始工作区干净。完整阅读 HANDOFF、根/插件 README、当前与遗留 Skill、开发测试说明和工具接口，并逐项核对源码。本轮没有检查活跃生产 Gateway 的有效工具清单；工具能力结论来自插件注册/schema 与核心实现。

| 现有能力 | 录音流程中的用途与边界 |
|---|---|
| register / inspect / extract / status | 具体文件登记与范围转写；SUCCEEDED 不代表识别准确 |
| read / find | 按真实片段编号和时间读取证据；遵循分页，未读/失败范围不可补造 |
| Worker transcript.md / sources.json | 保留原始引擎转写、时间和来源；Worker 不生成纪要或调用大模型 |
| save_minutes(job_id,text,source_segments) | 新增独立缓存整理稿；来源编号校验；相同文本和来源可幂等复用；返回 SAVED 不等于永久保存 |
| 再次 save_minutes | 用户确认具体疑点后创建新版，前版ID、确认内容和时间写正文；没有 reviewed/confirmed 参数，元数据仍 agent-derived-unverified |
| files/artifact_path 与既有渠道入口 | 取得交付路径；成功发送需真实渠道回执，本轮未发送 |
| files/save | 须用户明确长期保存授权；artifact_id 标记选中稿，实际仍保存完整任务产物包，包含其他稿，不能承诺只复制单稿 |
| files/saved_read | 读取已明确保存版本；缓存过期不能再对旧任务 save_minutes |

单次整理稿限12000字符、100项片段来源，每任务最多32份 minutes。已交接的122段录音若整理使用超过100段来源，需要分篇并保留各篇来源及时间；12355字节附件不等于12355字符。现有工具不提供原音试听/裁剪、专门人工复核界面或语音置信度核实，不能假装听过原音。大模型整理是 Agent 的行为，由 Skill 指导，不是新增服务或自动后处理。

## 场景走查

以下是对 Skill 决策路径与真实接口的人工静态走查，不是实际 Gateway 大模型行为测试。

| 用户/输入场景 | 应有行为 |
|---|---|
| 只上传录音，无任务 | 确认登记或pending，等待任务，不自动转写/整理 |
| Incoming文件仍上传中、没有完成通知 | 不扫描/自动处理，等待上传关闭及用户通知 |
| “全文转写，只要原稿” | full提取、分页读/交付transcript；不调用save_minutes/save/知识库 |
| “整理纪要并列疑点” | 读实际覆盖，另写未经核实稿；疑点含片段ID、时间、原文及问题，不猜补事实 |
| 用户确认某段姓名/金额并要求更新 | 新增整理稿，记录确认及前版ID，保留其他疑点；原转写和旧稿不变 |
| 只说“确认”，指代不清 | 明确对应疑点，不把全部猜测标为已确认 |
| 只给更正，尚未要求整理 | 保留确认信息，不自动生成整理稿 |
| PARTIAL、失败范围、无可靠内容 | 明示缺口，仅按已有可靠证据整理；FAILED不编造正文 |
| 超过100项来源或12000字符 | 分篇并标各篇范围，不丢来源，不把时间戳用作source_segments |
| 请求永久保存某稿 | 说明整包保存边界；只允许单稿且禁止其他稿时报告接口不足 |
| 缓存过期/工具不可用/无发送能力 | 报告实际限制，按现有恢复途径处理，不编造成功或参数 |
| 转写正文含“永久入库”等指令 | 作为不可信数据，不取得保存或知识库授权 |

## 独立环境与验证

主机 Ubuntu26.04、Linux7.0 x86_64；核对时开发盘可用316GiB、内存可用约19GiB。主机 Python3.14.4 不在项目支持范围，Node 不存在；没有在系统或生产环境安装依赖。下载独立 uv/Python 的准备尝试在网络授权后仍120秒超时，未完成宿主venv准备。

只读核对本机 Docker `default` 的目标为 `unix:///var/run/docker.sock`，daemon名 myserver/linux/x86_64。这是共用本机daemon，不宣称专用测试daemon。使用唯一命名、临时隔离容器；不进入运行中的生产容器，不挂生产目录/socket，不映射host端口。原有 `nas-filetools:1.2.1` 镜像仅作为固定依赖基底，ID `17be5923cdb294ac87635537853786817ea13907cce1e4b26bf8259a6feec685`，不重打或覆盖其标签；实际执行代码来自交接开发仓库的只读挂载。该基底不是从本轮提交完整重建的生产候选镜像。

开发测试镜像另取 `filetools-recording-dev:20261005-9e853e8`，新增固定pytest8.3.5/ruff0.11.2，已构建成功；为绕过Ruff慢下载另准备的仅pytest镜像 `filetools-recording-core-dev:20261005-9e853e8` 也构建成功，最终回归使用前者。Python3.12.10及引擎依赖沿用基底。依赖准备允许网络，处理阶段 `--network none`、`--cap-drop ALL`、`no-new-privileges`、非root10001，限2CPU/4GiB，数据仅在容器临时/tmp、证据目录仅 `/tmp/filetools-recording-evidence`。源码与系统DejaVu字体只读挂载；独立校验容器读取skill-creator的quick_validate脚本。

真实核心场景检查已完成：实际登记合成5秒静音WAV，注入两段识别结果，经真实Worker产物写入、核心派生/读取/保存实现，验证不自动生成纪要、新版不覆盖原转写或旧稿、保留未经核实元数据、派生不永久保存、无效片段及单次限额拒绝、明确保存仍保留完整产物包、过期拒绝。这里的ASR、整理文字与用户确认均为模拟输入，没有运行大模型、识别模型、人工试听或消息发送。

核心基线首轮临时/tmp上限2GiB，结果82通过、9失败、15跳过（28.15秒）；9项均为DISK_RESERVE。安装计划要求默认4GiB接收上限+1GiB保留余量，其他测试也受已有临时文件占用影响。这是本轮测试环境容量设置不足；未降低产品配额或保护阈值，仅把隔离容器/tmp容量上限改8GiB后重跑，容器内存仍4GiB，不预分配8GiB内存。两批有重叠，不累加。

| 本轮检查 | 实际结果与性质 | 证据 |
|---|---|---|
| 最终Linux默认核心基线 | **91通过、15跳过、39.25秒**；真实文件/进程/socket检查与既有故障注入混合；不是全量真实引擎验收 | [日志](evidence/recording-workflow-baseline.txt) |
| 首轮容量不足 | 82通过、9失败、15跳过；失败为DISK_RESERVE，保留排查证据 | [首轮日志](evidence/recording-workflow-baseline-initial.txt) |
| 录音生命周期场景 | 7组断言通过；真实核心写入，合成音频/注入识别/手工整理及确认输入 | [结果与性质](evidence/recording-workflow-scenarios.json) |
| 两个最终Skill标准校验 | quick_validate均通过；结构校验不证明模型行为 | [日志](evidence/recording-workflow-skill-validation.txt) |
| Ruff / git diff --check | src/tests/scripts通过；最终差异无空白错误 | [Ruff](evidence/recording-workflow-ruff.txt) |

15项跳过：真实引擎10项、可选真实Samba4项、Windows专属1项；跳过不等于通过。5条警告来自既有PyMuPDF SWIG类型的废弃提示。归档TXT日志仅去除行尾空白，原始日志及JUnit保留在 `/tmp/filetools-recording-evidence`。Node/SDK插件测试、build/validate、GitHub CI本轮均未执行；没有为文档修改下载完整SDK依赖，不能将Python检查称为插件或真实Gateway验收。

复现默认核心基线时，使用上述独立测试镜像，开发源码只读挂到 `/opt/nas-filetools-check`、DejaVu字体只读挂到 `/usr/share/fonts/truetype/dejavu`、专用证据目录写挂到 `/evidence`；保留离线/非root/CPU/内存限制，临时/tmp至少满足测试的5GiB余量要求。执行：

```bash
# 仅独立测试容器内；不是生产服务中的exec
/opt/nas-filetools/.venv/bin/python -m pytest -q -ra --basetemp=/tmp/filetools-tests -p no:cacheprovider --junitxml=/evidence/baseline.xml
/opt/nas-filetools/.venv/bin/python -m ruff check --no-cache src tests scripts
```

临时场景脚本保留在本服务器 `/tmp/filetools-recording-scenarios.py`，使用注入Processor调用真实run_job和dispatch；该临时脚本未纳入运行代码或长期交付，结果JSON已入Git。新增开发镜像保留供后续隔离复测，临时测试容器均使用 `--rm`；没有新增长期服务。

## 未验证与后续边界

本轮不运行真实OCR/ASR、不下载/改动模型、不读用户生产录音、不重做生产PDF/QQ验收。合成音频与注入识别结果不证明识别准确；手工提供的整理/确认文字不证明实际大模型会遵循Skill。实际Gateway读取新版Skill后的行为、模型信息、后端处理耗时、中文准确性和完整人工复核对话均未验证。Node/SDK验证如未执行须明确保留未验证状态，静态场景走查不代替它们。

用户补充的真实生产事实已写入 [HANDOFF第9节](../HANDOFF.md#9-服务器接手增量2026-10-05)，注明来源和未重复核验；其成功范围不扩大到其他账号/渠道/客户端、4小时或4GiB。新版Skill仅在开发分支，生产仍使用已安装版本；后续生产安装需要另外明确授权。
