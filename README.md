# OpenClaw Skills

## 录音 Skill 服务器增量更新（2026-10-05，未部署）

沿用现有 file-workspace 工具：仅转写不自动整理；按用户要求生成独立整理稿，疑点带时间戳交人工确认，确认后新增整理稿版本，原转写保留。不自动永久保存或入库。当前工具的缓存、复核与整包保存限制，以及服务器独立测试/模拟/未验证结果见 [更新报告](docs/RECORDING_WORKFLOW_UPDATE.md)；用户补充的真实生产 PDF/录音验证见 [交接增量](HANDOFF.md#9-服务器接手增量2026-10-05)。下方各版本报告保留各自历史时点。

## 文件工具 V1.2.1 修订（本地交付，生产待验收）

修复附件登记 pending/失败回执、root 诊断标记权限及只读 NAS 输入映射；新增兼容的目录登记 `select:false` 和回执分页。可选管理员入口提供 saved-only Samba 结果共享的计划、应用、诊断和数据保留回滚，沿用已有账号和单 Worker，不自动修改个人/Family 共享、知识库或生产服务器。

- [修订接口与架构取舍](docs/V121_INTERFACE.md)
- [安装、个人 Incoming 与 Samba 结果共享、迁移回滚](docs/V121_INSTALL.md)
- [普通用户说明](docs/V121_USER_GUIDE.md)
- [真实／模拟测试与生产待验收](docs/V121_TESTING.md)
- [开发交付报告](docs/V121_REPORT.md)

旧 `shared-v1.2` 配置兼容，核心安装入口不变。Samba 为可选：`python3 scripts/filetools_admin.py samba-results --config <配置>` 默认只读计划，系统应用／回滚需显式 `--action apply|rollback --apply`。以下V1.2/V1.1文档作为历史记录保留。

## 统一文件工作区 V1.2（本地开发交付，生产待验收）

在实际 Agent workspace 下管理快照、引用、共享缓存和独立保存版本，Gateway 固定管理 CLI 与单个 CPU worker 共用核心，控制请求只传ID。10个真实工具和通用 file-workspace Skill 支持自主选择读取/提取/Python，正文来源和交付路径明确，不自动向量入库。一人一Agent，main与chen不合并。

- [架构与信任边界](docs/V12_ARCHITECTURE.md)
- [工具、产物与错误契约](docs/V12_INTERFACE.md)
- [单配置安装、诊断、迁移回滚](docs/V12_INSTALL.md)
- [支持范围、资源和V2路线图](docs/V12_SUPPORT.md)
- [普通用户指南](docs/V12_USER_GUIDE.md)
- [本地测试与复现](docs/V12_TESTING.md)
- [生产验收清单](docs/V12_ACCEPTANCE.md)
- [开发报告](docs/V12_REPORT.md)

使用 `deploy/install.v12.example.json` 和 `python3 scripts/filetools_admin.py install|diagnose --config <配置>`。安装默认只生成计划，`--apply`才改运行环境；本轮没有部署生产。独立Python3.12环境，固定依赖在pyproject/requirements.lock，插件目标OpenClaw2026.9.4。完整复现及真实/模拟边界见开发报告。

下方V1.1说明及docs/V11_*保留为历史交付记录；V1.2新部署必须使用shared-v1.2配置。

## 统一文件处理 V1.1（开发交付，生产待验收）

新增独立 CPU 文件处理核心、SQLite 后台任务、OpenClaw 2026.9.4 插件和 Skill：支持 PDF/DOCX/UTF-8 MD/TXT、图片印刷文字 OCR、音频转写，一人一 Agent 持久快照/保存区与会话任务隔离、默认 72 小时闲置缓存，不自动进入永久知识库。模型使用真正注册的 filetools_* 工具，不传服务器路径或身份。群聊保守拒绝，具体限制见文档。

- [基线与生产信息](docs/BASELINE.md)
- [架构与重要取舍](docs/V11_ARCHITECTURE.md)
- [工具/产物契约](docs/V11_INTERFACE.md)
- [格式支持、资源和质量限制 / V2 路线图](docs/SUPPORT.md)
- [独立安装、资源控制与回滚](docs/V11_INSTALL.md)
- [部署后验收步骤](docs/V11_ACCEPTANCE.md)
- [开发验证报告](docs/V11_REPORT.md)
- [普通用户说明](docs/V11_USER_GUIDE.md)
- [OpenClaw 插件](integrations/openclaw-filetools/README.md)

开发复现：独立 Python 3.12 venv，`pip install -c requirements.lock.txt -e '.[engines,test]'`；`python -m pytest -q` 和 `python -m ruff check src tests scripts`。真实引擎用 `FILETOOLS_REAL_ENGINES=1`；真实音频另指定 FILETOOLS_AUDIO_SAMPLE、FILETOOLS_WHISPER_MODEL（离线 snapshot）及预期关键词 FILETOOLS_AUDIO_EXPECT。普通单元测试不下载模型。

安装/诊断入口：`python3 scripts/filetools_admin.py install|diagnose --config <单份配置>`。4 GiB归档、历史快照选择、保存版本、长音频检查点和受控Python副本操作见V1.1文档；生产运行仍待验收。

下列原独立脚本继续保留，未被统一 V1 接管或重写。

## filetools — 文件处理工具箱

本地 CPU 可跑，不需要 GPU。两类功能：

**转文字**
```bash
python3 filetools/bin/ocr_pdf.py 扫描件.pdf              # 扫描版 PDF/图片 OCR → 文字
python3 filetools/bin/transcribe_audio.py 录音.m4a       # 音频 → 带时间戳的文字
```

**文档转换**
```bash
python3 filetools/bin/pdf2md.py 报告.pdf --ocr          # PDF → AI 友好的 Markdown
python3 filetools/bin/pdf2docx.py 报告.pdf              # PDF → Word（保留版式）
python3 filetools/bin/docx2md.py 文档.docx              # Word → Markdown
python3 filetools/bin/extract_tables.py 财报.pdf        # 提取表格 → csv/md
python3 filetools/bin/pdf_split.py split 大.pdf --every 50  # 拆分/取页/合并
```

## 原独立脚本的历史安装方法

以下只适用于旧独立脚本。统一 V1.1 使用上方独立安装入口；不要照此向正在运行的 Gateway 或检索环境安装依赖。旧版式转换不属于统一 V1.1 的验收能力。

1. 把 `filetools` 文件夹拷到 OpenClaw 的 skills 目录
2. 按 `filetools/references/setup.md` 装依赖（一次就行）
