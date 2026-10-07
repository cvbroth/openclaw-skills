"""Validate a human/developer receipt into a new local revision. No production writes."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nas_filetools.ocr_review_bundle import import_receipt  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--receipt", type=Path, required=True)
    p.add_argument("--reviewer-type", choices=["human", "developer-agent"], required=True)
    p.add_argument("--reviewer-name", required=True)
    a = p.parse_args()
    result = import_receipt(a.bundle, json.loads(a.receipt.read_bytes()), a.reviewer_type, a.reviewer_name)
    print(
        json.dumps(
            {
                "revision": result["revision"],
                "revision_hash": result["revision_hash"],
                "human_page_confirmations": sum(
                    x["review_status"] == "human-page-confirmed" for x in result["pages"]
                ),
            }
        )
    )
