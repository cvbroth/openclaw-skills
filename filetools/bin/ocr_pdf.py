#!/usr/bin/env python3
"""扫描版 PDF/图片 OCR 转文字。

用法:
    python3 ocr_pdf.py 试题册.pdf
    python3 ocr_pdf.py 试题册.pdf -o result.txt --dpi 300
    python3 ocr_pdf.py 扫描页.png
"""
import argparse
import sys

import numpy as np


def pixmap_to_array(pix):
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4:  # RGBA -> RGB
        img = img[:, :, :3]
    return img


def main():
    ap = argparse.ArgumentParser(description="扫描版 PDF/图片 OCR 转文字")
    ap.add_argument("input", help="PDF 或图片路径")
    ap.add_argument("-o", "--output", default=None, help="输出 txt 路径")
    ap.add_argument("--dpi", type=int, default=200, help="渲染清晰度，默认 200")
    args = ap.parse_args()

    import fitz  # PyMuPDF：PDF 和图片都能打开

    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()  # 默认支持中英文，CPU 运行

    doc = fitz.open(args.input)
    total = len(doc)
    out = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=args.dpi)
        result, _ = engine(pixmap_to_array(pix))
        out.append(f"\n===== 第 {i + 1} 页 =====\n")
        if result:
            out.extend(line[1] for line in result)
        print(f"进度: {i + 1}/{total}", flush=True)

    out_path = args.output or args.input.rsplit(".", 1)[0] + ".txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"完成，结果在 {out_path}")


if __name__ == "__main__":
    main()
