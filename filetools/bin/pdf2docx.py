#!/usr/bin/env python3
"""PDF 转 Word（保留版式，仅文字版 PDF 有效）。

用法:
    python3 pdf2docx.py 报告.pdf
    python3 pdf2docx.py 报告.pdf -o 报告.docx --start 0 --end 10
"""
import argparse


def main():
    ap = argparse.ArgumentParser(description="PDF 转 Word（保留版式）")
    ap.add_argument("input", help="PDF 路径（文字版）")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--start", type=int, default=0, help="起始页（从0开始）")
    ap.add_argument("--end", type=int, default=None, help="结束页（不含）")
    args = ap.parse_args()

    from pdf2docx import Converter
    out = args.output or args.input.rsplit(".", 1)[0] + ".docx"
    cv = Converter(args.input)
    cv.convert(out, start=args.start, end=args.end)
    cv.close()
    print(f"完成: {out}")


if __name__ == "__main__":
    main()
