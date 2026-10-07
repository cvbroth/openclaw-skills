"""Two bounded photometric experiments; same pixels/coordinates, no deskew guess."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter


def prepare(images, output, pages):
    if output.exists():
        raise ValueError('OUTPUT_EXISTS: preserve earlier experiments')
    rows = []
    for page in pages:
        source = images / f'page-{page}.png'
        with Image.open(source) as image:
            original = image.convert('RGB')
        gray = original.convert('L')
        for name, img, params in [
            ('contrast125', gray, {'grayscale': True, 'contrast': 1.25, 'median_size': None}),
            ('median3-contrast125', gray.filter(ImageFilter.MedianFilter(3)),
             {'grayscale': True, 'contrast': 1.25, 'median_size': 3}),
        ]:
            result = ImageEnhance.Contrast(img).enhance(1.25).convert('RGB')
            directory = output / name
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / source.name
            result.save(destination)
            rows.append({'physical_page': page, 'variant': name, 'parameters': params,
                         'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                         'image_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
                         'size': list(original.size), 'bytes': destination.stat().st_size,
                         'processed_to_original': [[1,0,0],[0,1,0],[0,0,1]],
                         'coordinate_basis': 'unchanged original pixels; no crop/resize/rotation'})
    (output / 'preprocessing-manifest.json').write_text(json.dumps(rows, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pages', nargs='+', type=int, required=True)
    args = parser.parse_args()
    prepare(args.images, args.output, args.pages)
