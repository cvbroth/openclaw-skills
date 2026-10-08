"""Import a user-exported comment receipt into an explicit DEVELOPMENT project."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nas_filetools.artifact_project import import_feedback

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    print(import_feedback(args.project, json.loads(args.receipt.read_text())))
