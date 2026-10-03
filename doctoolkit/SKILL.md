---
name: "doctoolkit"
description: "文档格式工具箱：PDF 转 Markdown/Word、Word 转 Markdown、提取 PDF 表格、PDF 拆分合并。用户说 pdf 转 word、pdf 转 md、提取表格、拆分 pdf 时触发。"
---

# DocToolkit

文档格式一站式转换。全部本地 CPU 运行，不需要 GPU。

## 工具一览

| 脚本 | 功能 | 用法示例 |
|---|---|---|
| `bin/pdf2md.py` | PDF → AI 友好的 Markdown（文字版直接提取，扫描版自动 OCR） | `python3 bin/pdf2md.py 报告.pdf` |
| `bin/pdf2docx.py` | PDF → Word（保留版式，仅文字版 PDF） | `python3 bin/pdf2docx.py 报告.pdf` |
| `bin/docx2md.py` | Word → Markdown | `python3 bin/docx2md.py 文档.docx` |
| `bin/extract_tables.py` | 提取 PDF 表格 → csv/md | `python3 bin/extract_tables.py 财报.pdf` |
| `bin/pdf_split.py` | PDF 拆分/取页/合并 | `python3 bin/pdf_split.py split a.pdf --pages 1-10` |

音频转写、图片 OCR 用 `transcribe` 技能（已另装）。

## 常用流程

**试题册/扫描书 → AI 可用的 md**：
```bash
python3 bin/pdf2md.py 试题册.pdf --ocr -o 试题册.md
```

**PDF → Word**：
```bash
python3 bin/pdf2docx.py 合同.pdf -o 合同.docx
```

**大 PDF 先拆小再处理**：
```bash
python3 bin/pdf_split.py split 大文件.pdf --every 50
```

## 环境

首次使用按 `references/setup.md` 安装依赖。

## 规则

- `pdf2md.py` 的"AI 友好"指：标题按字号分级（# ## ###）、表格转 md 表格、每页加 `<!-- 第N页 -->` 标记、去掉页眉页脚噪音
- 扫描版 PDF 转 Word 没有意义（pdf2docx 不认图片字），先走 `pdf2md.py --ocr`，再用 pandoc 转 docx
- 大文件放后台跑（`nohup ... &`）
- OCR 相关先拿 10 页试效果再全量
