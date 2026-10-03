"""Explicit operator-only model download; processing workers are offline by default."""
import argparse
import json
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

parser = argparse.ArgumentParser()
parser.add_argument("--model", choices=["tiny", "tiny.en", "base", "small"], default="small")
parser.add_argument("--cache", required=True)
parser.add_argument("--revision", help="Immutable Hugging Face revision; resolved once if omitted")
args = parser.parse_args()
repository = f"Systran/faster-whisper-{args.model}"
revision = args.revision or HfApi().model_info(repository).sha
downloaded = snapshot_download(repository, revision=revision, cache_dir=args.cache,
    allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*", "preprocessor_config.json"])
Path(args.cache).mkdir(parents=True, exist_ok=True)
manifest = {"repository": repository, "revision": revision, "snapshot": downloaded,
            "model": args.model, "instruction": "Use the immutable snapshot path as whisper_model for offline operation."}
(Path(args.cache) / f"{args.model}-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps(manifest))
