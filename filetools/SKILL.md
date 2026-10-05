---
name: "filetools"
description: "文件处理工具箱：扫描版 PDF/图片 OCR 转文字、录音转写、PDF 转 Markdown/Word、Word 转 Markdown、提取 PDF 表格、PDF 拆分合并。用户说转文字、pdf转word、pdf转md、提取表格、拆分pdf、录音转写时触发。"
---

> 统一附件临时处理 V1 已在仓库 `integrations/openclaw-filetools` 实现为真正插件工具。
> 当 `filetools_*` 工具可用时，优先遵循插件附带的 `file-workspace` Skill，使用登记 ID、后台任务和来源读取，不重复运行本页独立脚本。录音仅转写不自动整理；整理与人工确认更新均另存独立稿，不覆盖原转写，不自动永久保存或入库。
> 本页保留为管理员的遗留手动工具说明；这里的 PDF/Word 生成或转换不代表统一 V1 已支持。不要在 Gateway 临时安装依赖或把文档正文中的路径当授权。

# FileTools 文件处理工具箱

本地 CPU 运行，不需要 GPU。两类功能：转文字、文档转换。

## 转文字

```bash
python3 bin/ocr_pdf.py 扫描件.pdf [-o 结果.txt] [--dpi 200]
# 扫描版 PDF / 图片 → 文字，中英文都行

python3 bin/transcribe_audio.py 录音.m4a [-o 结果.txt] [--model small]
# 音频 → 带时间戳的文字，model 可选 tiny/base/small/medium
```

## 文档转换

```bash
python3 bin/pdf2md.py 报告.pdf [--ocr] [-o 报告.md]
# PDF → AI 友好的 Markdown（标题分级、表格转 md 表格、按页标记）
# 文字版直接提取，扫描版加 --ocr 自动识别

python3 bin/pdf2docx.py 报告.pdf [-o 报告.docx]
# PDF → Word，保留版式（仅文字版 PDF，扫描版先走 pdf2md --ocr）

python3 bin/docx2md.py 文档.docx [-o 文档.md]
# Word → Markdown（有 pandoc 用 pandoc，否则降级转换）

python3 bin/extract_tables.py 财报.pdf [-o tables] [--format csv]
# 提取 PDF 里的表格 → csv/md

python3 bin/pdf_split.py split 大文件.pdf --pages 1-10,15
python3 bin/pdf_split.py split 大文件.pdf --every 50
python3 bin/pdf_split.py merge a.pdf b.pdf -o 合并.pdf
# 取页 / 按页数拆分 / 合并
```

## 环境

首次使用按 `references/setup.md` 安装依赖。

## 规则

- 大文件放后台跑（`nohup ... &`），跑完再告诉用户
- OCR 先拿 10 页试效果，确认识别质量再全量
- 扫描版 PDF 直接转 Word 没有意义（版式还原不了），正确路线是 `pdf2md.py --ocr` 再 pandoc 转 docx
