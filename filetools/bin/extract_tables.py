#!/usr/bin/env python3
"""提取 PDF 里的表格，存成 csv 或 md。

用法:
    python3 extract_tables.py 财报.pdf [-o tables] [--format csv]
"""
import argparse
import csv
import os


def main():
    ap = argparse.ArgumentParser(description="提取 PDF 表格")
    ap.add_argument("input", help="PDF 路径（文字版）")
    ap.add_argument("-o", "--output", default="tables", help="输出目录")
    ap.add_argument("--format", choices=["csv", "md"], default="csv")
    args = ap.parse_args()

    import pdfplumber
    os.makedirs(args.output, exist_ok=True)
    n = 0
    with pdfplumber.open(args.input) as pdf:
        for pi, page in enumerate(pdf.pages):
            for table in page.extract_tables() or []:
                n += 1
                rows = [[(c or "").strip() for c in r] for r in table]
                if args.format == "csv":
                    path = os.path.join(args.output, f"p{pi + 1}_t{n}.csv")
                    with open(path, "w", newline="", encoding="utf-8-sig") as f:
                        csv.writer(f).writerows(rows)
                else:
                    path = os.path.join(args.output, f"p{pi + 1}_t{n}.md")
                    with open(path, "w", encoding="utf-8") as f:
                        for r in rows:
                            f.write("| " + " | ".join(r) + " |\n")
                print(f"第 {pi + 1} 页表格 -> {path}")
    print(f"完成，共 {n} 个表格")


if __name__ == "__main__":
    main()
