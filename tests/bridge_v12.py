"""Test transport driver. Real core/worker, synthetic runtime identity, no HTTP byte upload."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from nas_filetools.contracts import Fault, Limits  # noqa: E402
from nas_filetools.service import dispatch  # noqa: E402
from nas_filetools.shared_workspace import WorkspaceHub, WorkspaceSupervisor  # noqa: E402


def main():
    request = json.load(sys.stdin)
    config = json.loads(Path(sys.argv[1]).read_text())
    hub = WorkspaceHub(Path(sys.argv[1]).parent/"control", Limits(**config["limits"]), config["workspaces"])
    try:
        if request["operation"] == "count_jobs":
            with hub.for_identity(request["identity"]).db() as db:
                result = {"status": "COUNT", "jobs": db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]}
        else:
            result = dispatch(hub, request["identity"], request["operation"], request["params"])
            if result["status"] == "QUEUED":
                supervisor = WorkspaceSupervisor(hub)
                try:
                    for _ in range(800):
                        supervisor.tick()
                        result = dispatch(hub, request["identity"], "status", {"job_id": result["job_id"]})
                        if result["status"] not in ("QUEUED", "RUNNING"):
                            break
                        time.sleep(.025)
                finally:
                    supervisor.close()
    except Fault as error:
        result = {"status": "ERROR", "code": error.code}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
