"""Read an explicitly supplied OCR/review package in independent development.

This is not a registered tool or a production sandbox escape. No OCR, filesystem
search, text correction, publication, saving, or template installation occurs.
"""
import argparse
import hashlib
import json
import resource
import time
from collections import Counter
from pathlib import Path

from nas_filetools.document_sample import PAGE_MARK, structure_ocr


def inspect(input_path, pages, experimental_mixed=False):
    started = time.monotonic()
    data = Path(input_path).read_bytes()
    review = json.loads(data) if Path(input_path).suffix == ".json" else {"raw_ocr": data.decode("utf-8")}
    raw = review["raw_ocr"]
    markers = [int(m.group(1) or m.group(2)) for line in raw.splitlines()
               if (m := PAGE_MARK.match(line.strip()))]
    selected = [page for page in markers if pages[0] <= page <= pages[1]]
    if selected != list(range(pages[0], pages[1] + 1)):
        raise ValueError("OCR_SCOPE_NOT_CONTIGUOUS_OR_DUPLICATED")
    model = structure_ocr(raw, pages, review.get("margin_evidence"), review.get("reviewed_edits"),
                          mixed=experimental_mixed)
    inventory = []
    for block in model["blocks"]:
        fragments = block["fragments"]
        row = {"kind": block["kind"], "pages": sorted({r["page"] for r in fragments}),
               "lines": sorted({r["line"] for r in fragments}),
               "raw_fragments": [{"page": r["page"], "line": r["line"], "raw": r["raw"]} for r in fragments]}
        if block["kind"] == "question":
            row.update(number=block["number"], question_type=block.get("question_type", "choice"),
                       options=[part["label"] for part in block["parts"] if part["kind"] == "option"])
        inventory.append(row)
    report = {"scope": list(pages), "input_sha256": hashlib.sha256(data).hexdigest(),
              "raw_ocr_sha256": hashlib.sha256(raw.encode()).hexdigest(), "scope_markers": selected,
              "experimental_mixed": experimental_mixed, "production_schema": "reviewed-single-choice-v1",
              "production_mixed_support": False, "structural_acceptance": not model["issues"],
              "blocks": dict(Counter(b["kind"] for b in model["blocks"])),
              "issue_counts": dict(Counter(i["code"] for i in model["issues"])),
              "issues": model["issues"], "inventory": inventory,
              "elapsed_seconds": round(time.monotonic() - started, 6),
              "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "original_page_review": "not performed by this script",
              "visual_review": "not performed", "publication": "not performed"}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--pages", type=int, nargs=2, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--experimental-mixed", action="store_true")
    args = parser.parse_args()
    if args.pages[0] < 1 or args.pages[0] > args.pages[1]:
        parser.error("invalid explicit scope")
    result = inspect(args.input, tuple(args.pages), args.experimental_mixed)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("scope", "blocks", "issue_counts", "structural_acceptance")}))


if __name__ == "__main__":
    main()
