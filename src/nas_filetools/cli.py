"""Administrative CLI and the same Unix protocol used by the plugin."""

import argparse
import http.client
import json
import os
import signal
import socket
import sys
import threading
import uuid
from pathlib import Path

from .contracts import Fault, Limits, owner
from .service import SOCKET, serve
from .store import Store
from .worker import ServiceLock


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=60)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def main():
    parser = argparse.ArgumentParser(description="Temporary NAS file tools (trusted operator only)")
    parser.add_argument("--socket", default=SOCKET)
    parser.add_argument("--identity-file", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    service = sub.add_parser("serve")
    service.add_argument("--root", required=True)
    service.add_argument("--config", type=Path)
    clean = sub.add_parser("cleanup", help="Offline cleanup; refuses a running service")
    clean.add_argument("--root", required=True)
    clean.add_argument("--config", type=Path)
    register = sub.add_parser("register", help="Trusted local diagnostic upload, never expose to an Agent")
    register.add_argument("file", type=Path)
    register.add_argument("--attachment-id", default=None)
    request = sub.add_parser("call")
    request.add_argument("operation", choices=["inspect", "extract", "status", "cancel", "read", "find", "save_minutes", "files", "python", "capabilities", "health", "diagnostics"])
    request.add_argument("--params", default="{}", help="JSON object")
    for name in ("install", "diagnose"):
        entry = sub.add_parser(name)
        entry.add_argument("--config", type=Path, required=True)
        entry.add_argument("--local-only", action="store_true", help="Workspace tests only; does not install runtime")
        if name == "install":
            entry.add_argument("--apply", action="store_true", help="Apply printed installation plan; may recreate Gateway")
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--record", type=Path, required=True)
    rollback.add_argument("--apply", action="store_true")
    migration = sub.add_parser("migrate")
    migration.add_argument("--old-root", required=True)
    migration.add_argument("--new-root", required=True)
    migration.add_argument("--identity-map", required=True)
    migration.add_argument("--config", type=Path)
    migration.add_argument("--apply", action="store_true")
    shared_migration = sub.add_parser("migrate-workspaces", help="Copy V1.1 snapshots/saved versions to explicit real Agent workspaces")
    shared_migration.add_argument("--old-root", required=True)
    shared_migration.add_argument("--agent-map", required=True)
    shared_migration.add_argument("--config", type=Path, required=True)
    shared_migration.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if args.command in ("install", "diagnose"):
            from . import operations
            result = operations.install(args.config, args.apply, args.local_only) if args.command == "install" else operations.diagnose(args.config, args.local_only)
        elif args.command == "rollback":
            from .operations import rollback
            result = rollback(args.record, args.apply)
        elif args.command == "migrate-workspaces":
            from .operations_v12 import migrate
            result = migrate(args.config, args.old_root, args.agent_map, args.apply)
        elif args.command == "migrate":
            from .operations import migrate
            limits = Limits(**json.loads(args.config.read_text())) if args.config else Limits()
            result = migrate(args.old_root, args.new_root, limits, args.identity_map, args.apply)
        elif args.command == "serve":
            settings = json.loads(args.config.read_text()) if args.config else {}
            limits = Limits(**settings.get("limits", settings))
            stop = threading.Event()
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
            signal.signal(signal.SIGINT, lambda *_: stop.set())
            serve(args.root, limits, args.socket, stop, settings.get("workspaces"))
            return
        elif args.command == "cleanup":
            lock = ServiceLock(args.root)
            try:
                settings = json.loads(args.config.read_text()) if args.config else {}
                limits = Limits(**settings.get("limits", settings))
                if settings.get("workspaces"):
                    from .shared_workspace import WorkspaceHub
                    result = {"status": "CLEANED", "agents": WorkspaceHub(args.root, limits, settings["workspaces"]).cleanup()}
                else:
                    result = Store(args.root, limits).cleanup()
            finally:
                lock.close()
        else:
            if not args.identity_file:
                raise Fault("IDENTITY_REQUIRED")
            if os.name == "posix" and args.identity_file.stat().st_mode & 0o077:
                raise Fault("IDENTITY_FILE_PERMISSIONS")
            identity = json.loads(args.identity_file.read_text(encoding="utf-8"))
            owner(identity)
            client = UnixConnection(args.socket)
            try:
                client.request("POST", "/v1/tool", body=json.dumps({"identity": identity,
                    "operation": "capabilities", "params": {}}).encode())
                capabilities = json.loads(client.getresponse().read(2*1024**2))
                if capabilities.get("status") != "CAPABILITIES":
                    raise Fault("SERVICE_CAPABILITIES_UNAVAILABLE")
                limits = capabilities["limits"]
                if args.command == "register":
                    size = args.file.stat().st_size
                    if not args.file.is_file() or args.file.is_symlink() or not 0 < size <= limits["max_receive_bytes"]:
                        raise Fault("SIZE_OR_FILE_TYPE")
                    client.timeout = limits["upload_timeout_seconds"]+30
                    client.close()
                    with args.file.open("rb") as file:
                        import hashlib
                        digest = hashlib.file_digest(file, "sha256").hexdigest()
                        file.seek(0)
                        client.request("POST", "/v1/attachment", body=file, headers={
                            "Content-Length": str(size), "X-Filetools-Identity": json.dumps(identity),
                            "X-Filename": json.dumps(args.file.name, ensure_ascii=True),
                            "X-Content-SHA256": digest,
                            "X-Attachment-Id": args.attachment_id or uuid.uuid4().hex})
                else:
                    payload = json.dumps({"identity": identity, "operation": args.operation,
                                          "params": json.loads(args.params)}, ensure_ascii=False).encode()
                    if len(payload) > limits["max_control_bytes"]:
                        raise Fault("REQUEST_LIMIT")
                    client.request("POST", "/v1/tool", body=payload)
                response = client.getresponse()
                body = response.read(limits["max_response_bytes"]+1)
                if response.status != 200 or len(body) > limits["max_response_bytes"]:
                    raise Fault("INVALID_RESPONSE")
                result = json.loads(body)
            finally:
                client.close()
        print(json.dumps(result, ensure_ascii=False))
        if result.get("status") == "ERROR":
            sys.exit(1)
    except Exception as error:
        print(json.dumps({"status": "ERROR", "code": error.code if isinstance(error, Fault) else "CLI_ERROR"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
