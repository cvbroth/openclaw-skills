"""One bounded engine child. Receives trusted args, never decides project layout."""

import json
from pathlib import Path
import resource
import sys
from .adapters import recognize


def main():
    request = json.loads(Path(sys.argv[1]).read_text())
    try:
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
