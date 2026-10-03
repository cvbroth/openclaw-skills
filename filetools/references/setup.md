# 环境安装（一次就行）

```bash
# 系统依赖：pandoc（文档互转）、ffmpeg（音频解码）
sudo apt update && sudo apt install -y pandoc ffmpeg

# Python 依赖（清华镜像快一些）
pip3 install pymupdf pdf2docx pdfplumber python-docx \
  rapidocr_onnxruntime faster-whisper \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

- RapidOCR / faster-whisper 的模型第一次运行时自动下载
- 全部 CPU 运行，不需要 GPU
- 验证：`python3 bin/pdf2md.py --help` 能打出帮助即成功

## 各工具依赖速查

| 工具 | 需要 |
|---|---|
| ocr_pdf.py | pymupdf + rapidocr_onnxruntime |
| transcribe_audio.py | faster-whisper + ffmpeg |
| pdf2md.py | pymupdf（+ rapidocr_onnxruntime，如需 OCR） |
| pdf2docx.py | pdf2docx |
| docx2md.py | pandoc（推荐）或 python-docx |
| extract_tables.py | pdfplumber |
| pdf_split.py | pymupdf |
