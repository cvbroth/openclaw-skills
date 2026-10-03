"""Fetch the publicly MIT-licensed Whisper regression audio at a fixed source commit."""
import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

COMMIT = "86098128c0b4f24f0e2aa2994de830614b474227"
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
base = f"https://raw.githubusercontent.com/openai/whisper/{COMMIT}"
for source, name in [("tests/jfk.flac", "jfk.flac"), ("LICENSE", "WHISPER-LICENSE")]:
    with urllib.request.urlopen(f"{base}/{source}", timeout=30) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise RuntimeError("Test asset exceeds its download limit")
    (args.output / name).write_bytes(data)
audio = args.output / "jfk.flac"
manifest = {"repository": "openai/whisper", "commit": COMMIT, "path": "tests/jfk.flac", "license": "MIT",
            "sha256": hashlib.sha256(audio.read_bytes()).hexdigest()}
(args.output / "audio-origin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps(manifest))
