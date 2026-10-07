"""Offline experimental review of one native PP result; never a production tool."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nas_filetools.ocr_review import reconcile  # noqa: E402


def overlay(image_path, native, result, destination):
    from PIL import Image, ImageDraw
    with Image.open(image_path) as source:
        image = source.convert('RGB')
    if image.size != (native['width'],native['height']):
        raise ValueError('IMAGE_NATIVE_COORDINATE_SIZE_MISMATCH')
    draw = ImageDraw.Draw(image)
    for name, color in [('recovered','green'),('pending_fragments','red')]:
        for row in result[name]:
            draw.rectangle(row['bbox'],outline=color,width=3)
            draw.text((row['bbox'][0],row['bbox'][1]-12),f"{name}:{row['raw_index']}",fill=color)
    image.save(destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--markdown', type=Path, required=True)
    parser.add_argument('--physical-page', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rules', type=Path, help='experimental JSON thresholds; data only')
    parser.add_argument('--image', type=Path, help='optional private coordinate review overlay; requires existing Pillow')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output directory exists; never overwrite evidence')
    rules = json.loads(args.rules.read_bytes()) if args.rules else None
    native = json.loads(args.native.read_bytes())
    result = reconcile(native, args.physical_page, args.markdown.read_text(), rules)
    result['native_sha256'] = hashlib.sha256(args.native.read_bytes()).hexdigest()
    result['original_markdown_sha256'] = hashlib.sha256(args.markdown.read_bytes()).hexdigest()
    args.output.mkdir(parents=True)
    (args.output / 'repaired.md').write_text(result.pop('repaired_markdown'))
    (args.output / 'review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    if args.image:
        overlay(args.image,native,result,args.output/'overlay.png')


if __name__ == '__main__':
    main()
