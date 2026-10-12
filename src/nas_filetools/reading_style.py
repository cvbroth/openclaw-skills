"""Versioned reading typography shared by the viewer and Markdown direct export."""

import json
from pathlib import Path
from .artifact_project import digest
from .document_entry import FONT_PATH
from .document_fonts import fallback_records

STYLE = {
    "id": "filetools-reading",
    "version": "1.0.0",
    "font_family": "Droid Sans Fallback",
    "body_pt": 10.5,
    "line_multiple": 1.85,
    "paragraph_em": 1.0,
    "heading_scale": [1.6, 1.35, 1.15],
    "heading_margin_em": [0.67, 0.83, 1.0],
    "list_indent_pt": 0,
    "paper_mm": [210, 297],
    "margin_mm": 15,
}


def snapshot():
    return {
        **STYLE,
        "font_path": str(FONT_PATH),
        "font_sha256": digest(FONT_PATH),
        "fallbacks": fallback_records(),
    }


def emit_reading_assets(folder):
    import shutil

    folder = Path(folder)
    chain = [("FT Reading", Path(FONT_PATH))] + [(r["name"], Path(r["path"])) for r in fallback_records()]
    css = ""
    for i, (name, path) in enumerate(chain):
        if path.is_file():
            target = folder / f"reading-font-{i}.ttf"
            if not target.exists() or digest(target) != digest(path):
                shutil.copyfile(path, target)
            css += f'@font-face{{font-family:"{name}";src:url("reading-font-{i}.ttf")}}\n'
    css += (
        ".reading{font-family:" + ",".join(json.dumps(name) for name, _ in chain) + ",sans-serif;"
        f"--reading-base-px:{STYLE['body_pt'] * 4 / 3};font-size:{STYLE['body_pt'] * 4 / 3}px;line-height:{STYLE['line_multiple']};"
        "color:#243145}"
        f".reading p{{margin:{STYLE['paragraph_em']}em 0;white-space:pre-wrap}}"
        ".reading b{font-weight:bold}.reading i{font-style:italic}"
    )
    for i, (scale, margin) in enumerate(zip(STYLE["heading_scale"], STYLE["heading_margin_em"]), 1):
        css += (
            f".reading h{i}{{font-size:{scale}em;margin:{margin}em 0;font-weight:bold;white-space:pre-wrap}}"
        )
    (folder / "reading.css").write_text(css)
