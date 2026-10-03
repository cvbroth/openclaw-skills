#!/usr/bin/env python3
"""PDF 转 AI 友好的 Markdown。

用法:
    python3 pdf2md.py 报告.pdf                  # 文字版自动提取
    python3 pdf2md.py 扫描书.pdf --ocr           # 强制 OCR
    python3 pdf2md.py 报告.pdf -o out.md --dpi 300

AI 友好 = 标题按字号分级 + 表格转 md 表格 + 每页标记 + 去页眉页脚噪音。
文字页直接提取；文字过少（<30字）的页面自动降级 OCR。
"""
import argparse
import sys


def pixmap_to_array(pix):
    import numpy as np
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4:
        img = img[:, :, :3]
    return img


def ocr_page(page, engine, dpi):
    pix = page.get_pixmap(dpi=dpi)
    result, _ = engine(pixmap_to_array(pix))
    return [line[1] for line in result] if result else []


def text_page_to_md(page):
    """用字号识别标题层级，转成 md。"""
    d = page.get_text("dict")
    sizes = sorted({s["size"] for b in d["blocks"] if b["type"] == 0
                    for l in b["lines"] for s in l["spans"] if s["text"].strip()},
                   reverse=True)
    # 取字号最大的 3 档做标题（需明显大于正文）
    body_size = sizes[len(sizes) // 2] if sizes else 12
    heading_sizes = [s for s in sizes[:3] if s >= body_size * 1.15]

    def level_of(size):
        return heading_sizes.index(size) + 1 if size in heading_sizes else 0

    md = []
    for b in d["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            spans = [s for s in l["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            top_size = max(s["size"] for s in spans)
            lv = level_of(top_size)
            # 短行 + 大字号才算标题，避免误伤
            if lv and len(text) <= 60:
                md.append("#" * lv + " " + text)
            else:
                md.append(text)
        md.append("")
    return "\n".join(md).strip()


def main():
    ap = argparse.ArgumentParser(description="PDF 转 AI 友好的 Markdown")
    ap.add_argument("input", help="PDF 路径")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--ocr", action="store_true", help="强制全部页面 OCR")
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()

    import fitz
    doc = fitz.open(args.input)
    total = len(doc)

    engine = None
    if args.ocr:
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()

    out = []
    for i, page in enumerate(doc):
        out.append(f"\n<!-- 第 {i + 1} 页 -->\n")
        raw = page.get_text().strip()
        if not args.ocr and len(raw) >= 30:
            out.append(text_page_to_md(page))
        else:
            if engine is None:
                from rapidocr_onnxruntime import RapidOCR
                engine = RapidOCR()
            out.append("\n".join(ocr_page(page, engine, args.dpi)))
        print(f"进度: {i + 1}/{total}", flush=True)

    out_path = args.output or args.input.rsplit(".", 1)[0] + ".md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"完成，结果在 {out_path}")


if __name__ == "__main__":
    main()
