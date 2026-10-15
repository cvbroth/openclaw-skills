"""Isolated Pandoc document transaction. No alternate export engine."""

import json
from pathlib import Path
import resource
import sys
import time
from .pandoc_export import generate


def main():
    start = time.monotonic()
    try:
        generate(json.loads(Path(sys.argv[1]).read_text()))
        result = {"status": "SUCCEEDED"}
    except Exception as exc:
        result = {
            "status": "FAILED",
            "error": {
                "category": "local",
                "stage": getattr(exc, "stage", "prepare"),
                "code": type(exc).__name__,
                "message": str(exc)[:2000],
            },
        }
    result.update(
        elapsed_seconds=time.monotonic() - start,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    )
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
