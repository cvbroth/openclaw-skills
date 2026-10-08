"""One explicit experimental metadata repair; never edits source GGUF or tensors.

Requires pinned gguf 0.19.0. Implements upstream PR17195 author's documented
workaround, not the unmerged C++ patch. Full field/tensor comparison is mandatory.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def digest(data):
    return hashlib.sha256(data).hexdigest()


def repair(source, output, report):
    import gguf

    if output.exists() or source.resolve() == output.resolve():
        raise ValueError("REFUSE_OVERWRITE")
    before = gguf.GGUFReader(source, "r")
    tokens = before.fields["tokenizer.ggml.tokens"].contents()
    if tokens[59253] != "<|user|>" or "tokenizer.ggml.eot_token_id" in before.fields:
        raise ValueError("UNEXPECTED_BASELINE_METADATA")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "gguf.scripts.gguf_new_metadata",
            "--special-token-by-id",
            "eot",
            "59253",
            str(source),
            str(output),
        ],
        check=True,
    )
    after = gguf.GGUFReader(output, "r")
    added = set(after.fields) - set(before.fields)
    removed = set(before.fields) - set(after.fields)
    changed = [
        key
        for key in before.fields
        if key in after.fields and before.fields[key].contents() != after.fields[key].contents()
    ]
    # GGUF virtual fields include byte offsets, which move when metadata grows.
    actual_changed = [key for key in changed if not key.startswith("GGUF.")]
    assert added == {"tokenizer.ggml.eot_token_id"} and not removed and not actual_changed
    assert after.fields["tokenizer.ggml.eot_token_id"].contents() == 59253
    assert len(before.tensors) == len(after.tensors)
    tensor_records = []
    for left, right in zip(before.tensors, after.tensors):
        assert left.name == right.name and left.tensor_type == right.tensor_type
        assert left.shape.tolist() == right.shape.tolist()
        a, b = digest(left.data), digest(right.data)
        assert a == b
        tensor_records.append({"name": left.name, "sha256": a})
    result = {
        "repair": "add tokenizer.ggml.eot_token_id=59253 only",
        "gguf_package": "0.19.0",
        "upstream": "https://github.com/ollama/ollama/pull/17195",
        "source_sha256": hashlib.file_digest(source.open("rb"), "sha256").hexdigest(),
        "output_sha256": hashlib.file_digest(output.open("rb"), "sha256").hexdigest(),
        "output_bytes": output.stat().st_size,
        "added_fields": sorted(added),
        "changed_nonvirtual_fields": actual_changed,
        "all_tensor_bytes_equal": True,
        "tensor_count": len(tensor_records),
        "tensor_checks": tensor_records,
    }
    report.write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    repair(args.source, args.output, args.report)
