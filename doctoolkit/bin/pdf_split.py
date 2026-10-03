#!/usr/bin/env python3
"""PDF 拆分 / 取页 / 合并。

用法:
    python3 pdf_split.py split 大文件.pdf --pages 1-10,15   # 取指定页（页码从1开始）
    python3 pdf_split.py split 大文件.pdf --every 50        # 每50页拆一份
    python3 pdf_split.py merge a.pdf b.pdf -o 合并.pdf      # 合并
"""
import argparse


def parse_pages(spec, total):
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            pages.update(range(int(a) - 1, int(b)))
        else:
            pages.add(int(part) - 1)
    return sorted(p for p in pages if 0 <= p < total)


def cmd_split(args):
    import fitz
    doc = fitz.open(args.input)
    total = len(doc)
    base = args.input.rsplit(".", 1)[0]
    if args.every:
        for start in range(0, total, args.every):
            end = min(start + args.every, total)
            nd = fitz.open()
            nd.insert_pdf(doc, from_page=start, to_page=end - 1)
            out = f"{base}_p{start + 1}-{end}.pdf"
            nd.save(out)
            nd.close()
            print(out)
    else:
        pages = parse_pages(args.pages, total)
        nd = fitz.open()
        for p in pages:
            nd.insert_pdf(doc, from_page=p, to_page=p)
        out = args.output or f"{base}_extract.pdf"
        nd.save(out)
        nd.close()
        print(f"完成: {out}（{len(pages)} 页）")


def cmd_merge(args):
    import fitz
    out = fitz.open()
    for f in args.inputs:
        d = fitz.open(f)
        out.insert_pdf(d)
        d.close()
    out.save(args.output)
    out.close()
    print(f"完成: {args.output}")


def main():
    ap = argparse.ArgumentParser(description="PDF 拆分 / 取页 / 合并")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("split", help="拆分/取页")
    s.add_argument("input")
    s.add_argument("--pages", default=None, help="页码，如 1-10,15（从1开始数）")
    s.add_argument("--every", type=int, default=None, help="每 N 页拆一份")
    s.add_argument("-o", "--output", default=None)
    m = sub.add_parser("merge", help="合并多个 PDF")
    m.add_argument("inputs", nargs="+")
    m.add_argument("-o", "--output", required=True)
    args = ap.parse_args()
    if args.cmd == "split":
        if not args.pages and not args.every:
            ap.error("split 需要 --pages 或 --every")
        cmd_split(args)
    else:
        cmd_merge(args)


if __name__ == "__main__":
    main()
