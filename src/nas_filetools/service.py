"""Local Unix HTTP service. Only the trusted Gateway/administrative CLI can reach this socket."""

import json
import os
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from .contracts import Fault, owner, strict, valid_id
from .store import Store
from .worker import ServiceLock, Supervisor

SOCKET = "/run/nas-filetools/service.sock"


def dispatch(store, identity, operation, params):
    owner(identity)
    with store.lock:
        store.agent(identity)
        if operation == "capabilities":
            strict(params, ())
            return {"status": "CAPABILITIES", "version": "1.1.0", "limits": {
                k: v for k, v in store.limits.dict().items() if k not in ("whisper_model", "model_cache", "script_python")}}
        if operation == "diagnostics":
            strict(params, ())
            from .diagnostics import runtime_check
            return runtime_check(store)
        if operation == "files":
            strict(params, ("action", "area", "file_id", "job_id", "artifact_id", "saved_id", "attachment_id", "inbox_id", "offset"), ("action",))
            return store.files(identity, **params)
        if operation == "python":
            from .scripts import request
            return request(store, identity, params)
        if operation == "inspect":
            strict(params, ("attachment_id",))
            return store.inspect(identity, params.get("attachment_id"))
        if operation == "extract":
            strict(params, ("attachment_id", "config"), ("attachment_id", "config"))
            return store.submit(identity, params["attachment_id"], params["config"])
        if operation in ("status", "cancel"):
            strict(params, ("job_id",), ("job_id",))
            return getattr(store, operation)(identity, params["job_id"])
        if operation == "save_minutes":
            strict(params, ("job_id", "text", "source_segments"), ("job_id", "text", "source_segments"))
            return store.save_minutes(identity, params["job_id"], params["text"], params["source_segments"])
        if operation in ("read", "find"):
            strict(params, ("job_id", "artifact_id", "pages", "time_range", "paragraphs", "offset", "max_chars", "keyword"),
                   ("job_id",))
            return store.read(identity, params["job_id"], {k: v for k, v in params.items() if k != "job_id"},
                              find=operation == "find")
    raise Fault("UNKNOWN_OPERATION")


class LocalServer(ThreadingMixIn, HTTPServer):
    address_family = getattr(socket, "AF_UNIX", socket.AF_INET)
    daemon_threads = True
    # Bound sockets, including slow/hostile clients. A second slot permits control calls during upload.
    slots = threading.BoundedSemaphore(2)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def serve(root, limits, socket_path=SOCKET, stop_event=None):
    if os.name != "posix":
        raise Fault("LINUX_SERVICE_REQUIRED", "NAS service requires Linux; core/worker tests run on Windows.")
    os.umask(0o077)
    service_lock = ServiceLock(root)
    store = Store(root, limits)
    supervisor = Supervisor(store)
    stop = stop_event or threading.Event()
    state = {"error": None, "last_tick": time.time()}
    upload_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log document content, sender IDs or paths in shared logs.

        def do_POST(self):
            self.connection.settimeout(20)
            temporary = None
            uploading = False
            try:
                if self.headers.get("Transfer-Encoding") or not self.headers.get("Content-Length", "").isdigit():
                    raise Fault("INVALID_LENGTH")
                length = int(self.headers["Content-Length"])
                if self.path == "/v1/attachment":
                    if not 0 < length <= limits.max_bytes:
                        raise Fault("SIZE_LIMIT")
                    identity = json.loads(self.headers.get("X-Filetools-Identity", "{}"))
                    owner(identity)
                    store.agent(identity)
                    import shutil
                    if shutil.disk_usage(store.root).free < length+limits.disk_reserve_bytes:
                        raise Fault("DISK_RESERVE")
                    identifier = valid_id(self.headers.get("X-Attachment-Id"))
                    filename = json.loads(self.headers.get("X-Filename", '""'))
                    from pathlib import Path
                    if not isinstance(filename, str) or Path(filename).name != filename or len(filename) > 200:
                        raise Fault("INVALID_FILENAME")
                    if not upload_lock.acquire(blocking=False):
                        raise Fault("UPLOAD_BUSY")
                    uploading = True
                    temporary = store.root / "incoming" / (uuid.uuid4().hex + Path(filename).suffix.lower())
                    with temporary.open("xb") as file:
                        deadline = time.monotonic() + limits.upload_timeout_seconds
                        remaining = length
                        while remaining:
                            wait = deadline - time.monotonic()
                            if wait <= 0:
                                raise Fault("UPLOAD_TIMEOUT")
                            self.connection.settimeout(min(20, wait))
                            chunk = self.rfile.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise Fault("INCOMPLETE_UPLOAD")
                            file.write(chunk)
                            remaining -= len(chunk)
                        file.flush()
                        os.fsync(file.fileno())
                    import hashlib
                    from .contracts import HASH
                    expected = self.headers.get("X-Content-SHA256", "")
                    with temporary.open("rb") as file:
                        actual = hashlib.file_digest(file, "sha256").hexdigest()
                    if not HASH.fullmatch(expected) or actual != expected:
                        raise Fault("ATTACHMENT_CHANGED")
                    message_id = json.loads(self.headers.get("X-Source-Message-Id", '""'))
                    if not isinstance(message_id, str) or len(message_id) > 200:
                        raise Fault("INVALID_SOURCE_REFERENCE")
                    # Arrival archives even unsupported formats; no OCR/ASR/document parse at ingress.
                    info = {"deferred_inspection": True}
                    if message_id:
                        info["source_message_id"] = message_id
                    result = store.register(identity, identifier, filename, temporary, info)
                elif self.path == "/v1/tool":
                    if not 0 < length <= limits.max_control_bytes:
                        raise Fault("REQUEST_LIMIT")
                    payload = json.loads(self.rfile.read(length))
                    strict(payload, ("identity", "operation", "params"), ("identity", "operation", "params"))
                    if payload["operation"] == "health":
                        owner(payload["identity"])
                        store.agent(payload["identity"])
                        strict(payload["params"], ())
                        result = {"status": "HEALTHY" if thread.is_alive() and not state["error"] else "UNHEALTHY",
                                  "scheduler_alive": thread.is_alive(), "last_tick_at": state["last_tick"],
                                  "error": state["error"], "active_workers": len(supervisor.processes)}
                    else:
                        result = dispatch(store, payload["identity"], payload["operation"], payload["params"])
                else:
                    raise Fault("UNKNOWN_ROUTE")
            except Fault as error:
                result = {"status": "ERROR", "code": error.code}
            except (ValueError, TypeError, KeyError):
                result = {"status": "ERROR", "code": "INVALID_REQUEST"}
            except Exception:
                result = {"status": "ERROR", "code": "SERVICE_ERROR"}
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
                if uploading:
                    upload_lock.release()
            body = json.dumps(result, ensure_ascii=False).encode()
            if len(body) > limits.max_response_bytes:
                body = b'{"status":"ERROR","code":"RESPONSE_LIMIT"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

    def background():
        scheduler_loop(supervisor, stop, state)

    from pathlib import Path
    endpoint = Path(socket_path)
    endpoint.parent.mkdir(parents=True, exist_ok=True)
    # Singleton lock protects this service state, but do not unlink another live listener.
    if endpoint.exists():
        with socket.socket(socket.AF_UNIX) as check:
            try:
                check.connect(str(endpoint))
            except ConnectionRefusedError:
                if not endpoint.is_socket():
                    raise Fault("UNSAFE_SOCKET")
                endpoint.unlink()
            else:
                raise Fault("SOCKET_IN_USE")
    server = LocalServer(str(endpoint), Handler)
    os.chmod(endpoint, 0o660)
    server.timeout = 0.5
    thread = threading.Thread(target=background, daemon=True)
    thread.start()
    try:
        while not stop.is_set():
            server.handle_request()
    finally:
        stop.set()
        thread.join(5)
        try:
            supervisor.close()
        finally:
            server.server_close()
            endpoint.unlink(missing_ok=True)
            service_lock.close()
    if state["error"]:
        raise Fault("SCHEDULER_FAILED", state["error"])


def scheduler_loop(supervisor, stop, state):
    """Fatal metadata/scheduler faults stop the listener; per-job engine faults are isolated by workers."""
    try:
        while not stop.wait(0.2):
            supervisor.tick()
            state["last_tick"] = time.time()
    except Exception as error:
        state["error"] = error.code if isinstance(error, Fault) else type(error).__name__
        stop.set()
