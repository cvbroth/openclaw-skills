# OpenClaw Skills

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
