"""Real Unix HTTP service/CLI integration, automatically skipped on Windows."""
import hashlib
import json
import os
import subprocess
import sys
import time

import pytest

from nas_filetools.cli import UnixConnection

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Real Unix socket/service integration requires Linux")


def request(socket, route, body, headers=None):
    client = UnixConnection(str(socket))
    try:
        client.request("POST", route, body=body, headers=headers or {})
        reply = client.getresponse()
        assert reply.status == 200
        return json.loads(reply.read())
    finally:
        client.close()


def test_real_service_lifecycle_and_protocol(tmp_path, identity):
    endpoint = tmp_path / "s.sock"
    process = subprocess.Popen([sys.executable, "-m", "nas_filetools.cli", "--socket", str(endpoint),
                                "serve", "--root", str(tmp_path / "state")],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not endpoint.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(0.05)
        assert endpoint.exists()
        assert endpoint.stat().st_mode & 0o777 == 0o660
        content = b"Cedar evidence\n\nBackup complete"
        headers = {"Content-Length": str(len(content)), "X-Filetools-Identity": json.dumps(identity),
                   "X-Attachment-Id": "a" * 32, "X-Source-Message-Id": '"canonical-message"', "X-Filename": '"notes.txt"',
                   "X-Content-SHA256": hashlib.sha256(content).hexdigest()}
        bad = request(endpoint, "/v1/attachment", content, {**headers, "X-Content-SHA256": "b" * 64})
        assert bad["code"] == "ATTACHMENT_CHANGED"
        uploaded = request(endpoint, "/v1/attachment", content, headers)
        assert uploaded["status"] == "INSPECTED"
        def call(operation, params, scope=identity):
            return request(endpoint, "/v1/tool", json.dumps({"identity": scope, "operation": operation,
                                                            "params": params}).encode())
        job = call("extract", {"attachment_id": "a" * 32, "config": {"mode": "full"}})
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status = call("status", {"job_id": job["job_id"]})
            if status["status"] not in ("QUEUED", "RUNNING"):
                break
            time.sleep(0.05)
        assert status["status"] == "SUCCEEDED"
        read = call("read", {"job_id": job["job_id"], "paragraphs": [1, 1]})
        assert read["evidence"][0]["text"] == "Cedar evidence"
        denied = call("read", {"job_id": job["job_id"]}, {**identity, "session_hash": "b" * 64})
        assert denied["code"] == "NOT_FOUND"
        invalid = call("inspect", {"path": "/etc/passwd"})
        assert invalid["code"] == "INVALID_PARAMETERS"
        assert call("extract", {"attachment_id": "a" * 32, "config": {"mode": "full"}})["reused"]
    finally:
        process.terminate()
        stdout, stderr = process.communicate(timeout=10)
        assert stdout == b"", stdout
        assert process.returncode == 0, stderr
    assert not endpoint.exists()
