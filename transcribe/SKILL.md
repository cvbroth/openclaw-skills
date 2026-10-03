---
name: "transcribe"
description: "把扫描版 PDF/图片 OCR 成文字，或把音频录音转写成文字。用户说转文字、识别图片文字、提取 PDF 文字、录音转写时触发。"
---

# Transcribe

把文件内容转成文字。两类任务：扫描版 PDF/图片用 OCR，音频录音用语音转写。都是 CPU 可跑，不需要 GPU。

## OCR：PDF/图片 → 文字

```bash
python3 bin/ocr_pdf.py <文件.pdf> [-o 输出.txt] [--dpi 200]
```

- 输入：PDF 或图片（png/jpg）
- 输出：按页分隔的 txt，默认写到 `<文件名>.txt`
- `--dpi` 默认 200，字小或模糊可提到 300（更慢）

## 语音转写：音频 → 文字

```bash
python3 bin/transcribe_audio.py <录音.m4a> [-o 输出.txt] [--model small]
```

- 输入：mp3/m4a/wav
- 输出：带时间戳的 txt，默认写到 `<文件名>.txt`
- `--model`：tiny/base/small/medium，默认 small（中文够用，CPU 约 0.3–0.5 倍速，即 1 小时音频转 20–40 分钟）

## 环境

首次使用先按 `references/setup.md` 装依赖（pip 一行 + 模型自动下载）。

## 规则

- 大文件放后台跑（`nohup ... &`），跑完再告诉用户
- OCR 先拿 10 页试效果，确认识别质量再全量
- 输出的 txt 很小，可直接发给用户或喂给下一步（总结、提取题目等）
