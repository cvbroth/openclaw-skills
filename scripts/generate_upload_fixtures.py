"""Non-business fixtures for source-layer classification and explicit local OCR."""

import argparse
from pathlib import Path
import fitz
from PIL import Image, ImageDraw, ImageFont


def run(output):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
    image = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 40), "Synthetic scan page", fill="black", font=font)
    draw.text((30, 100), "FILETOOLS 123", fill="black", font=font)
    image.save(root / "scan.png")
    pdf = fitz.open()
    pdf.new_page().insert_text((30, 50), "Synthetic selectable text paragraph. No model needed. " * 2)
    pdf.new_page().insert_image(fitz.Rect(0, 0, 595, 842), filename=str(root / "scan.png"))
    page = pdf.new_page()
    page.insert_image(page.rect, filename=str(root / "scan.png"))
    page.insert_text((30, 300), "Synthetic OCR text layer; not guaranteed accurate. " * 2)
    page = pdf.new_page()
    page.insert_text((30, 50), "Synthetic text with a small illustration. " * 2)
    page.insert_image(fitz.Rect(300, 100, 550, 350), filename=str(root / "scan.png"))
    pdf.new_page()
    pdf.save(root / "source-types.pdf")
    pdf.close()
    (root / "invalid.pdf").write_bytes(b"Not a PDF. Synthetic validation failure.")
    small = Image.new("RGB", (650, 180), "white")
    draw = ImageDraw.Draw(small)
    draw.text((25, 30), "FILETOOLS 123", fill="black", font=font)
    draw.text((25, 90), "Synthetic OCR", fill="black", font=font)
    small.save(root / "local-ocr.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.output)
