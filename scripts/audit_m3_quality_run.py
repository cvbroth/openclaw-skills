"""Export only whitelisted metadata from a private M3 quality experiment."""

import argparse
import base64
import json
from pathlib import Path

from m3_transcription_quality import PROMPT, base, parse, split_sections


def audit(root):
    manifest = json.loads((root / "manifest.json").read_bytes())
    records = []
    for source in sorted(manifest["images"], key=lambda x: x["physical_page"]):
        physical = source["physical_page"]
        image = (root / source["image"]).read_bytes()
        assert base.sha(image) == source["sha256"] and len(image) == source["bytes"]
        for attempt in sorted((root / "attempts" / f"page-{physical}").glob("attempt-*")):
            receipt = json.loads((attempt / "receipt.json").read_bytes())
            payload = json.loads((attempt / "request.json").read_bytes())
            assert payload["model"] == base.MODEL
            assert len(payload["messages"]) == 1 and "system" not in payload and "tools" not in payload
            content = payload["messages"][0]["content"]
            assert len(content) == 2 and content[0]["type"] == "image" and content[1]["type"] == "text"
            assert content[1]["text"] == PROMPT + "\n本张PDF物理页码：" + str(physical)
            assert base64.b64decode(content[0]["source"]["data"], validate=True) == image
            assert receipt["submitted"]["sha256"] == source["sha256"]
            assert [receipt["submitted"]["width"], receipt["submitted"]["height"]] == [
                source["width"],
                source["height"],
            ]
            assert payload["service_tier"] == "standard" and payload["thinking"] == {"type": "disabled"}
            assert payload["max_tokens"] == 12000 and payload["temperature"] == 1
            assert base.sha((attempt / "request.json").read_bytes()) == receipt["request_body_sha256"]
            raw = attempt / "response.raw.json"
            if raw.exists():
                assert base.sha(raw.read_bytes()) == receipt["response_sha256"]
            parsed = json.loads((attempt / "parse-receipt.json").read_bytes())
            row = {
                key: receipt.get(key)
                for key in (
                    "attempt",
                    "status",
                    "http_status",
                    "elapsed_seconds",
                    "requested_model",
                    "returned_model",
                    "stop_reason",
                    "usage",
                )
            }
            row.update(
                {
                    "physical_page": physical,
                    "parse_status": parsed["parse_status"],
                    "source_sha256": source["sha256"],
                    "source_dimensions": [source["width"], source["height"]],
                    "source_bytes": source["bytes"],
                    "submitted_byte_equality": True,
                    "request_sha256": receipt["request_body_sha256"],
                    "response_sha256": receipt.get("response_sha256"),
                }
            )
            if receipt["status"] == "succeeded":
                response = json.loads(raw.read_bytes())
                combined, _ = base.extract_response(response)
                assert (attempt / "transcription.txt").read_text() == combined
                assert receipt["returned_model"] == base.MODEL
                if parsed.get("transcription_parse_status") == "succeeded":
                    text, _ = split_sections(combined)
                    assert (attempt / "transcription.md").read_text() == text
                    row.update(
                        {
                            "transcription_characters": len(text),
                            "transcription_sha256": base.sha(text.encode()),
                        }
                    )
                if parsed["parse_status"] == "succeeded":
                    text, quality = parse(combined, physical)
                    assert (attempt / "transcription.md").read_text() == text
                    assert json.loads((attempt / "quality.json").read_bytes()) == quality
                    row.update(
                        {
                            "transcription_characters": len(text),
                            "transcription_sha256": base.sha(text.encode()),
                            "overall_quality": quality["overall_quality"],
                            "suggested_action": quality["suggested_action"],
                            "assessment_confidence": quality["assessment_confidence"],
                        }
                    )
            records.append(row)
    assert len(records) <= 60
    return {
        "schema": "m3-quality50-public-audit-v1",
        "source_pdf_sha256": manifest["source_pdf_sha256"],
        "manifest_sha256": base.sha((root / "manifest.json").read_bytes()),
        "seed": manifest["seed"],
        "pages": manifest["physical_pages"],
        "historical_overlap": manifest["overlap_pages"],
        "calls": len(records),
        "all_actual_request_images_byte_equal": True,
        "same_prompt_except_physical_page": True,
        "no_ocr_reference_or_history_input": True,
        "provider_internal_image_processing": "unknown",
        "human_accuracy": "not-measured",
        "attempts": records,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(audit(args.directory), ensure_ascii=False, indent=2) + "\n")
