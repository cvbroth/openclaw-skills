> 这是87f93ac交付的V1历史记录，限额/接口不代表当前V1.1。当前说明见 [V11_REPORT](V11_REPORT.md)。本轮远程CI未执行，不能将历史或已编写工作流视为V1.1 CI通过。

# V1 开发验证记录

执行日期：2026-10-03。全部验证在 Windows 开发机及独立依赖目录进行；未连接 NAS、生产 Docker 或 QQ。生产验收清单见 ACCEPTANCE.md，所有生产项目均为 **待验收**。

## 分层结果

| 层次 | 实际结果 | 能证明的范围 |
|---|---|---|
| 静态检查 | Ruff、Python 编译、pip check、Skill 校验通过 | 语法、依赖一致性及 Skill 格式 |
| Python 核心/边界测试 | 最终定向运行 32 通过、1 跳过 | 真实文字 PDF/DOCX/文本引擎、后台子进程、来源定位、范围/分页、配额、幂等、取消、超时、重启记录恢复、清理、身份拒绝及原件保护 |
| 真实 OCR/ASR 样本测试 | 4 通过 | RapidOCR 扫描/混合 PDF/图片，Whisper small CPU 全文及指定时间范围转写 |
| 真实 Linux Unix 服务测试 | 1 跳过 | Windows 不具备目标 Linux 服务环境；已写测试，未宣称服务实测通过 |
| 插件测试 | 11 通过、1 跳过 | 真实 2026.9.4 SDK 的七个工具工厂注册、模拟可信上下文/附件登记与隔离、一项连接真实 Python 核心和后台进程的跨语言测试 |
| SDK 会话存储实测 | 上述插件测试中 1 项跳过 | Windows SDK 生命周期锁目录不可在当前受限环境安全创建；Linux SDK SQLite 存储及已注册入站 Hook 联动仍待验证 |
| 插件构建/manifest 验证 | 2026.9.4 命令实际执行通过 | 入口可导入、manifest/配置/工具声明有效；不等同 Gateway 已加载或 Agent 实际调用 |
| 现有知识库插件回归 | 49 通过、1 跳过 | 原查询/导入/临时文档工具测试无回归；符号链接测试因 Windows 权限跳过。参考仓库跟踪文件未修改 |
| 真实 OpenClaw/QQ 端到端 | **未执行，待验收** | 附件接收→Agent 工具调用→基于页码/时间证据回答，生产策略/用户映射/挂载均需验收 |

最终完整 Python 运行曾得到 35 通过、2 跳过（31.14 秒）；随后增加独占创建竞争的原件保护用例并修正失败清理，再运行核心/边界集合得到 32 通过、1 跳过（9.86 秒）。真实引擎代码未在该修正中改变。不要把两个执行记录直接累加。Python 出现 5 条 PyMuPDF SWIG 弃用警告，没有测试失败。

部分失败/取消/超时/重启测试采用可控故障或预置任务记录，以验证状态机；它们不是生产进程被杀死后的恢复实测。跨语言测试使用注入的测试传输，不是 Linux Unix socket 或 QQ/Gateway 端到端测试。CI 已编写，**没有在本轮执行远程 CI**。

## 真实样本和 CPU 耗时

文档样本由 tests/conftest.py 自制：两页文字 PDF、一页扫描 PDF、三页混合 PDF（包含同页数字文字与图像）、包含段落/表格/图片的 DOCX、印刷文字 PNG 和 Markdown。没有私人附件。

音频使用 [OpenAI Whisper 测试录音](https://github.com/openai/whisper/blob/86098128c0b4f24f0e2aa2994de830614b474227/tests/jfk.flac)，固定提交 86098128c0b4f24f0e2aa2994de830614b474227，沿用其 [MIT 许可](https://github.com/openai/whisper/blob/86098128c0b4f24f0e2aa2994de830614b474227/LICENSE)。文件 SHA256：63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715。

最新实际测量保存在 evidence/engine-benchmark.json。每个任务使用新后台子进程，包含进程启动、模型加载和产物写入，操作系统文件缓存可能已热；不是多次统计或 NAS 速度估算。

| 样本 | 范围 | 实测墙钟秒 | 结果 |
|---|---|---:|---|
| text.pdf | 2 页 | 0.640 | SUCCEEDED |
| scan.pdf | 1 页 | 2.406 | SUCCEEDED，OCR |
| mixed.pdf | 3 页 | 3.766 | SUCCEEDED，逐页直接提取/OCR/OCR |
| ordered.docx | 5 正文块 | 1.000 | PARTIAL，表格/图片顺序保留，图片文字未识别 |
| printed.png | 1 帧 | 2.500 | SUCCEEDED，OCR |
| notes.md | 3 块 | 0.703 | SUCCEEDED |
| jfk.flac | 11 秒 | 6.797 | SUCCEEDED，Whisper small/int8/CPU |

开发机：Windows 11 10.0.26200，Python 3.12.3，处理器系统标识 Intel64 Family 6 Model 154 Stepping 3, GenuineIntel；未获得可靠 CPU 商品型号。并发 1、引擎线程 2，未应用 Linux RLIMIT_AS/cgroup 内存限制。不能据此推算 Xeon NAS 的速度。先前同样的扫描样本耗时约 2.5–5.2 秒、small 音频约 9.0 秒，说明启动和缓存波动不可忽略。

OCR：RapidOCR 1.4.4 / onnxruntime 1.20.1；文字 PDF：PyMuPDF 1.25.5；Word：python-docx 1.1.2；转写：faster-whisper 1.1.1。small 离线快照 revision 536b0662742c02347bc0e980a01041f333bce120；另实际测试过 tiny.en 快照 0d3d19a32d3338f10357c0889762bd8d64bbdeba。安装/下载与处理阶段分开，处理通过不可变本地快照，不依赖 GPU。

## 复现

在独立 Python 3.12 环境安装 requirements.lock.txt 约束下的 .[engines,test]，预装 FFmpeg、准备离线 small 快照：

```bash
python -m ruff check src tests scripts
python -m pytest tests/test_core.py tests/test_boundaries.py -q
FILETOOLS_REAL_ENGINES=1 FILETOOLS_AUDIO_SAMPLE=/test/jfk.flac \
  FILETOOLS_WHISPER_MODEL=/cache/immutable-small-snapshot FILETOOLS_AUDIO_EXPECT=country \
  python -m pytest tests/test_engines.py -q
python -m pytest tests/test_service.py -q
python scripts/benchmark_samples.py --output /test/benchmark \
  --audio /test/jfk.flac --model /cache/immutable-small-snapshot
```

音频下载脚本 fetch_test_audio.py 固定提交和校验和并保存许可。样本/缓存不要放进生产 Gateway。插件目录使用 Node 24.16.0：npm ci --ignore-scripts，FILETOOLS_TEST_PYTHON 指向独立 Python 后运行 npm test，再执行 plugin:build / plugin:validate。SDK 存储测试在 Linux 只创建测试目录中的会话数据库，生产插件只使用公开只读 getSessionEntry。

## 已知限制与待验收

- 本轮实际引擎样本是英文印刷文本及英文录音；中文、噪声/口音、手写、复杂版式和家庭真实附件质量均待验收。V1 不承诺照片画面理解、手写、公式、复杂表格或扫描版式完整还原。
- 群聊 V1 保守拒绝工具：共享群历史无法仅靠文件读取 ACL 提供私人回答隔离。已编写私聊正向及群聊拒绝验收矩阵；支持群聊需后续确认 sender 会话和私密回复设计。
- 2026.9.4 普通 message_received 实际 mapper 没有 runId，现实现通过公开只读会话存储和首次 session_start 绑定 epoch。缺失 sender/account/direct-session/sessionId、存储读取失败或 lifecycle 缺失均拒绝。生产镜像 3a9d69d 的实际字段和 QQ 插件仍待验收。
- 随 /new、idle/daily 重置一起收到的附件可能被旧 epoch 拒绝；新会话建立后需重发。Gateway 重启会丢失尚未上传的内存附件登记，已上传任务保留。
- DOCX 只处理正文块并保留图片，图片-only 块不做 OCR；混合文档标 PARTIAL，纯图片文档标 FAILED。页眉/页脚、修订和复杂表格几何未完整实现。
- 临时任务默认 72 小时清理，永不自动删除原件/原件快照。快照会累计；每 scope 配额不能限制无限新增会话，须配置独立卷/全局磁盘配额及报警。异常断电留下的 incoming/未登记快照或任务目录可能需管理员核对后维护，工具不提供任意路径删除。
- 同 UID 任意命令执行可绕过 socket 的逻辑身份保护。V1 不是加密身份或强沙箱；Agent 不应挂载 state、原件、NAS Source 或 Docker socket。
- Ubuntu wheel 安装、Docker 构建/镜像 digest、systemd/容器资源上限、真实 Unix 服务和进程树取消/崩溃恢复、离线断网首次加载均待验收。WSL 权限受限，Docker Desktop 守护进程未运行，本轮未启动或改造这些环境。

V2 只记录路线图，未新增生成 Word/PDF 或保留版式转换工具。数据库、Embedding、搜索及现有明确授权导入均未扩展或部署。
