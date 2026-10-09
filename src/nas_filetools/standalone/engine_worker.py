"""One bounded engine child. Receives trusted args, never decides project layout."""

import json
from pathlib import Path
import resource
import sys
from .adapters import recognize


def main():
    request = json.loads(Path(sys.argv[1]).read_text())
    try:
        if request["engine"]["type"] == "pdf-text":
            import fitz
            from ..artifact_project import digest

            with fitz.open(request["source"]) as doc:
                page = doc[request["physical_page"] - 1]
                text = page.get_text("text", sort=False)
                native = page.get_text("blocks", sort=False)
                result = {
                    "status": "SUCCEEDED",
                    "text": text,
                    "quality": None,
                    "error": None,
                    "usage": None,
                    "raw_response": None,
                    "input": {
                        "source_sha256": digest(request["source"]),
                        "physical_page": request["physical_page"],
                        "page_size_pt": list(page.rect[2:]),
                    },
                    "native": {
                        "blocks": native,
                        "order": "PDF native order; not guaranteed logical reading order",
                    },
                    "blocks": [
                        {
                            "id": f"p{request['physical_page']}-b{i + 1:04d}",
                            "type": "text",
                            "text": b[4],
                            "reading_order": i,
                            "coordinates": list(b[:4]),
                            "coordinate_system": "PDF points; source physical page",
                        }
                        for i, b in enumerate(native)
                        if b[6] == 0
                    ],
                }
        else:
            result = recognize(request["image"], request["engine"], request["parameters"])
    except Exception as exc:
        # Exception text may contain URLs/credentials; expose only type/stage.
        result = {
            "status": "FAILED",
            "text": "",
            "blocks": [],
            "quality": None,
            "error": {
                "category": "local",
                "stage": "engine",
                "code": type(exc).__name__,
                "message": "Engine failed; no speculative cause classification.",
            },
        }
    result["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    # NumPy values in RapidOCR native outputs require scalar/list normalization.
    def encode(value):
        if hasattr(value, "tolist"):
            return value.tolist()
        raise TypeError(type(value).__name__)

    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False, default=encode), encoding="utf-8")


if __name__ == "__main__":
    main()
