"""Trusted fixed-configuration Gateway adapter. JSON stdin/stdout; no engine dependencies."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from nas_filetools.contracts import Fault, Limits, strict  # noqa: E402
from nas_filetools.shared_workspace import management_call  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        raw = json.loads(Path(args.config).read_text(encoding="utf-8"))
        ceiling = Limits(**raw.get("limits", {})).max_control_bytes
        payload = sys.stdin.buffer.read(ceiling+1)
        if len(payload)>ceiling:
            raise Fault("CONTROL_LIMIT")
        request = json.loads(payload)
        strict(request, ("identity", "operation", "params"), ("identity", "operation", "params"))
        result = management_call(args.config, request["identity"], request["operation"], request["params"])
    except Exception as error:
        code = error.code if isinstance(error, Fault) else "SOURCE_PERMISSION_DENIED" if isinstance(error, PermissionError) else "MANAGEMENT_ERROR"
        result = {"status": "ERROR", "code": code, "recovery": "Check mapped roots/permissions; retry registration with the same request ID."}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
