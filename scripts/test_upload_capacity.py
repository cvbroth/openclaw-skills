"""Real bounded HTTP upload; enqueue stub deliberately prevents recognition calls."""

import argparse
import hashlib
import http.client
import json
from pathlib import Path
import resource
import socket
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

from PIL import Image
from nas_filetools.standalone.config import load
from nas_filetools.standalone.http import Handler
from nas_filetools.standalone.tasks import Projects


def run(config, output):
    limit = 512 * 1024 * 1024
    with tempfile.TemporaryDirectory(prefix="upload-capacity-") as temporary:
        root = Path(temporary)
        settings = load(config)
        assert settings["service"]["upload_bytes"] == limit
        manager = Projects(root / "data", settings)
        # Exercise registration/validation with the same handler; not a conversion test.
        manager.enqueue = lambda pid, *args, **kwargs: {"project_id": pid, "task_id": "upload-only-test"}
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.manager = manager
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        path = root / "synthetic-capacity.png"
        Image.new("RGB", (32, 32), "white").save(path)
        with path.open("r+b") as f:
            f.truncate(limit)  # Legal PNG followed by inert padding, not a 512MiB scanned document.
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=60)
        endpoint = "/api/uploads?filename=synthetic-capacity.png&engine=local&pages=1"
        try:
            start = time.monotonic()
            with path.open("rb") as stream:
                connection.request("POST", endpoint, stream, {"Content-Length": str(limit)})
                response = connection.getresponse()
                data = json.loads(response.read())
            elapsed = time.monotonic() - start
            assert response.status == 202, data
            project = manager.get(data["project_id"])
            artifact = next(
                a for a in project["artifacts"] if a["artifact_id"] == project["source_artifact_id"]
            )
            source = manager.path(project["project_id"]) / artifact["path"]
            digest = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
            assert source.stat().st_size == limit and artifact["sha256"] == digest
            assert hashlib.file_digest(source.open("rb"), "sha256").hexdigest() == digest
            assert project["tasks"] == []
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            connection.putrequest("POST", endpoint)
            connection.putheader("Content-Length", str(limit + 1))
            connection.endheaders()
            response = connection.getresponse()
            rejected = json.loads(response.read())
            assert response.status == 413 and rejected["limit_bytes"] == limit
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            connection.putrequest("POST", endpoint)
            connection.putheader("Content-Length", str(limit))
            connection.endheaders()
            connection.send(b"partial" * 100)
            connection.sock.shutdown(socket.SHUT_WR)
            response = connection.getresponse()
            incomplete = json.loads(response.read())
            assert response.status == 400 and "incomplete upload" in incomplete["reason"]
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            connection.request("POST", endpoint, b"not an image")
            response = connection.getresponse()
            invalid = json.loads(response.read())
            assert response.status == 400 and "UPLOAD_VALIDATION" in invalid["reason"]
            assert not list((manager.root / "uploads").iterdir())
            result = {
                "accepted_bytes": limit,
                "accepted_status": 202,
                "seconds": elapsed,
                "file_sha256": digest,
                "over_limit_bytes": limit + 1,
                "over_limit_status": 413,
                "incomplete_status": 400,
                "invalid_file_status": 400,
                "temporary_upload_files_remaining": 0,
                "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "memory_scope": "isolated server and streaming client in same process, includes validation/hash",
                "upload_read_chunk_bytes": 65536,
                "pdf_max_pages": settings["service"]["max_pages"],
                "task_max_selected_pages": settings["conversion"]["max_selected_pages"],
                "engine_calls": 0,
                "conversion_verified": False,
                "fixture": "32x32 PNG with inert trailing padding; byte-capacity test, not large-document conversion",
            }
            destination = Path(output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result))
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            manager.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.config, args.output)
