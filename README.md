# OpenClaw Skills

自用的 OpenClaw 技能合集，全部本地 CPU 可跑，不需要 GPU。

## transcribe — 转文字

扫描版 PDF/图片 OCR 成文字，音频录音转写成文字。

```bash
# 环境
pip3 install pymupdf rapidocr_onnxruntime faster-whisper
sudo apt install -y ffmpeg

# PDF/图片 OCR
python3 transcribe/bin/ocr_pdf.py 试题册.pdf

# 音频转写
python3 transcribe/bin/transcribe_audio.py 会议录音.m4a
```

## doctoolkit — 文档工具箱

PDF 转 Markdown/Word、Word 转 Markdown、提取 PDF 表格、PDF 拆分合并。

```bash
# 环境
sudo apt install -y pandoc
pip3 install pymupdf pdf2docx pdfplumber python-docx

# PDF → AI 友好的 Markdown（扫描版自动 OCR）
python3 doctoolkit/bin/pdf2md.py 报告.pdf --ocr

# PDF → Word / Word → Markdown
python3 doctoolkit/bin/pdf2docx.py 报告.pdf
python3 doctoolkit/bin/docx2md.py 文档.docx

# 提取表格 / 拆分合并
python3 doctoolkit/bin/extract_tables.py 财报.pdf
python3 doctoolkit/bin/pdf_split.py split 大文件.pdf --every 50
```

## 部署到 OpenClaw

把 `transcribe` / `doctoolkit` 文件夹拷到 OpenClaw 的 skills 目录即可。
