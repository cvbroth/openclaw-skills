"""Render only an explicit list of authorized physical PDF pages at 220 dpi."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import fitz

parser = argparse.ArgumentParser()
parser.add_argument('--pdf', type=Path, required=True)
parser.add_argument('--pages', type=int, nargs='+', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
if len(set(args.pages)) != len(args.pages) or any(page < 1 for page in args.pages):
    raise SystemExit('pages must be distinct positive physical page numbers')
args.output.mkdir(parents=True, exist_ok=True)
pdf = fitz.open(args.pdf)
rows = []
for physical in args.pages:
    if physical > pdf.page_count:
        raise SystemExit(f'page {physical} exceeds PDF page count')
    started = time.monotonic()
    pix = pdf[physical - 1].get_pixmap(matrix=fitz.Matrix(220/72, 220/72), alpha=False, annots=False)
    target = args.output / f'page-{physical}.png'
    pix.save(target)
    rows.append({'physical_page': physical, 'dpi': 220, 'width': pix.width, 'height': pix.height,
                 'bytes': target.stat().st_size,
                 'sha256': hashlib.file_digest(target.open('rb'), 'sha256').hexdigest(),
                 'render_seconds': time.monotonic() - started})
(args.output / 'input-pages.json').write_text(json.dumps(rows, indent=2) + '\n')
print(json.dumps({'pdf_pages': pdf.page_count, 'rendered_pages': len(rows), 'pages': rows}, indent=2))
