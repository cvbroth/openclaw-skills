# OpenClaw Skills

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

## 部署到 OpenClaw

1. 把 `filetools` 文件夹拷到 OpenClaw 的 skills 目录
2. 按 `filetools/references/setup.md` 装依赖（一次就行）
