"""Mature DOCX/PDF raster preview stage. No OCR, model calls, or substitute Word PDF."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import fitz
from ..artifact_project import digest


def render(request):
    source, out = Path(request["source"]), Path(request["output"])
    out.mkdir(parents=True, exist_ok=True)
    if digest(source) != request["sha256"]:
        raise ValueError("ARTIFACT_HASH_CHANGED")
    pdf = source
    engine = {"pdf_raster": fitz.version, "dpi": 120}
    if request["format"] == "docx":
        profile = out / "lo-profile"
        command = [
            "libreoffice",
            "-env:UserInstallation=" + profile.resolve().as_uri(),
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out),
            str(source),
        ]
        subprocess.run(
            command,
            check=True,
            timeout=120,
            env={**os.environ, "HOME": "/tmp", "XDG_CACHE_HOME": "/tmp", "GSETTINGS_BACKEND": "memory"},
        )
        pdf = out / (source.stem + ".pdf")
        if not pdf.is_file():
            raise ValueError("DOCX_RENDER_PDF_MISSING")
        engine["docx_renderer"] = subprocess.check_output(
            ["libreoffice", "--version"], text=True, timeout=10
        ).strip()
    pages = []
    with fitz.open(pdf) as document:
        if not 0 < len(document) <= 1000:
            raise ValueError("PREVIEW_PAGE_LIMIT")
        for n, page in enumerate(document, 1):
            if page.rect.width * page.rect.height * (120 / 72) ** 2 > 20_000_000:
                raise ValueError("PREVIEW_PIXEL_LIMIT")
            path = out / f"page-{n}.png"
            page.get_pixmap(matrix=fitz.Matrix(120 / 72, 120 / 72), alpha=False).save(path)
            pages.append(
                {
                    "output_page": n,
                    "file": path.name,
                    "sha256": digest(path),
                    "width_pt": page.rect.width,
                    "height_pt": page.rect.height,
                }
            )
    return {
        "status": "SUCCEEDED",
        "pages": pages,
        "renderer": engine,
        "rendered_pdf_sha256": digest(pdf),
        "source_sha256": request["sha256"],
    }


def main():
    request = json.loads(Path(sys.argv[1]).read_text())
    start = time.monotonic()
    try:
        result = render(request)
    except Exception as exc:
        # Persist actual bounded stage error, excluding input text and credentials.
        result = {
            "status": "FAILED",
            "error": {
                "category": "local",
                "stage": "preview",
                "code": type(exc).__name__,
                "message": str(exc)[:300],
            },
        }
    result["elapsed_seconds"] = time.monotonic() - start
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
