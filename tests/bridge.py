"""Testing adapter only: synthetic Gateway transport. Never install/expose as a production tool."""
import base64
import json
import sys
import time

from nas_filetools.contracts import Fault, Limits
from nas_filetools.engines import probe
from nas_filetools.service import dispatch
from nas_filetools.store import Store
from nas_filetools.worker import ServiceLock, Supervisor


def main():
    payload = json.load(sys.stdin)
    store = Store(sys.argv[1], Limits())
    lock = ServiceLock(store.root)
    try:
        if payload["operation"] == "register":
            params = payload["params"]
            file = store.root / "incoming" / params["filename"]
            file.write_bytes(base64.b64decode(params["bytes"]))
            result = store.register(payload["identity"], params["attachment_id"], params["filename"], file,
                                    probe(file, store.limits))
            file.unlink()
        else:
            result = dispatch(store, payload["identity"], payload["operation"], payload["params"])
            if payload["operation"] == "extract" and result["status"] in ("QUEUED", "RUNNING"):
                supervisor = Supervisor(store)
                try:
                    for _ in range(200):
                        supervisor.tick()
                        result = store.status(payload["identity"], result["job_id"])
                        if result["status"] not in ("QUEUED", "RUNNING"):
                            break
                        time.sleep(0.05)
                finally:
                    supervisor.close()
    except Fault as error:
        result = {"status": "ERROR", "code": error.code}
    finally:
        lock.close()
    print(json.dumps(result))


if __name__ == "__main__":
    main()
