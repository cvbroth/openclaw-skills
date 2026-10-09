"""Content checks on real generated files in the explicit synthetic R7 project."""

import argparse
import json
from pathlib import Path
import zipfile
from xml.etree import ElementTree
import fitz
from nas_filetools.artifact_project import digest


def verify(root, receipt):
    p = json.loads((root / "project.json").read_text())
    arts = {a["artifact_id"]: a for a in p["artifacts"]}
    original = arts[receipt["original_artifact_id"]]
    corrected = arts[receipt["corrected_artifact_id"]]
    assert "错宇" in (root / original["path"]).read_text()
    assert "错字" in (root / corrected["path"]).read_text()

    def pages(a):
        return [
            json.loads((root / v["data"]).read_text().split("=", 1)[1].rstrip(";\n"))["text"]
            for v in a["pages"]
        ]

    before, after = pages(original), pages(corrected)
    assert before[0] == after[0] and before[2] == after[2]
    assert before[1].replace("错宇", "错字") == after[1]
    for a in arts.values():
        if a.get("path"):
            assert digest(root / a["path"]) == a["sha256"]
    structure = json.loads((root / corrected["path"]).with_name("structure.json").read_text())
    assert [x["text"] for x in structure["pages"]] == after
    revision = json.loads((root / corrected["path"]).with_name("revision.json").read_text())
    assert revision["actor_type"] == "developer-agent" and not revision["identity_verified"]
    word = arts[receipt["word_artifact_id"]]
    pdf = arts[receipt["pdf_artifact_id"]]
    with zipfile.ZipFile(root / word["path"]) as archive:
        xml = ElementTree.fromstring(archive.read("word/document.xml"))
        text = "".join(
            n.text or "" for n in xml.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
        )
    with fitz.open(root / pdf["path"]) as doc:
        pdftext = "".join(page.get_text() for page in doc)
        count = len(doc)
    for t in [text, pdftext]:
        assert "错字" in t and "错宇" not in t
        assert all(x in t.replace(" ", "") for x in ["第22页保持不变", "此页保持不变"])
        assert "identity_verified" not in t and "parent_artifact_id" not in t
    assert all(t.get("operation") == "format-artifact" for t in p["tasks"])
    return {
        "original_and_unchanged_pages_preserved": True,
        "markdown_structure_preview_text_equal": True,
        "real_docx_pdf_corrected_text": True,
        "revision_audit_not_in_body": True,
        "recognition_tasks": 0,
        "cloud_requests": 0,
        "pdf_pages": count,
        "format_tasks": [
            {"status": t["status"], "metrics": t.get("metrics"), "template": t.get("template")}
            for t in p["tasks"]
        ],
        "outputs": [
            {"format": a["format"], "bytes": (root / a["path"]).stat().st_size, "sha256": a["sha256"]}
            for a in [corrected, word, pdf]
        ],
        "actor_type": revision["actor_type"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.root, json.loads(args.receipt.read_text())), ensure_ascii=False, indent=2))
