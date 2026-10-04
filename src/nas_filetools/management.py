"""Channel-neutral file registration in a trusted, explicitly mapped Agent workspace."""
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

from .catalog import copy_stream, digest_file, identify, timestamp
from .contracts import Fault, owner, strict, valid_id
from .workspace import category_v12

SYSTEM_NAMES = {"agents.md", "soul.md", "user.md", "memory.md", "identity.md", "bootstrap.md", "tools.md", "heartbeat.md"}


def stable_stat(path):
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def resolve_source(store, source_path, root_id="workspace", trusted_media=False):
    spec = store.limits.source_roots.get(root_id)
    if not isinstance(spec, dict) or not spec.get("path") or spec.get("kind") == "media" and not trusted_media:
        raise Fault("SOURCE_ROOT_DENIED")
    if not isinstance(source_path, str) or not source_path or "\0" in source_path:
        raise Fault("INVALID_SOURCE_PATH")
    given = Path(source_path)
    if ".." in given.parts:
        raise Fault("SOURCE_PATH_ESCAPE")
    root = Path(spec["path"]).resolve()
    candidate = given if given.is_absolute() else root/given
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise Fault("SOURCE_PATH_ESCAPE") from None
    current = root
    for piece in relative.parts:
        current = current/piece
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise Fault("SOURCE_SYMLINK_DENIED")
    if not candidate.resolve().is_relative_to(root):
        raise Fault("SOURCE_PATH_ESCAPE")
    if not candidate.is_file():
        raise Fault("SOURCE_NOT_FOUND")
    if candidate.name.lower().endswith((".part", ".tmp", ".crdownload", ".download")) or any(p.casefold() == "uploading" for p in relative.parts):
        raise Fault("SOURCE_INCOMPLETE", "Publish the final filename only after upload closes.")
    if spec.get("kind") == "workspace" and (candidate.name.casefold() in SYSTEM_NAMES or
            any(p.startswith(".") or p.casefold() in {"skills", "memory", "node_modules", "__pycache__", "venv"} for p in relative.parts)):
        raise Fault("SYSTEM_FILE_EXCLUDED")
    if not 0 < candidate.stat().st_size <= store.limits.max_receive_bytes:
        raise Fault("RECEIVE_SIZE_LIMIT")
    return candidate, root_id, relative.as_posix()


def snapshot_copy(source, destination, maximum, expected_size, expected_sha):
    """Reflink is opportunistic, never a hardlink or symlink; fallback uses bounded buffers."""
    destination = Path(destination)
    cloned = False
    if os.name == "posix":
        import fcntl
        try:
            with Path(source).open("rb") as incoming, destination.open("xb") as output:
                fcntl.ioctl(output.fileno(), 0x40049409, incoming.fileno())  # Linux FICLONE.
                output.flush()
                os.fsync(output.fileno())
            cloned = True
        except OSError:
            destination.unlink(missing_ok=True)
    if not cloned:
        with Path(source).open("rb") as incoming:
            copy_stream(incoming, destination, maximum, expected_size, expected_sha)
    if destination.stat().st_size != expected_size or digest_file(destination) != expected_sha:
        raise Fault("SOURCE_CHANGED")
    return "reflink" if cloned else "stream-copy"


def reference_path(store, record):
    details = json.loads(record["info"])
    reference = details["external_reference"]
    try:
        path, _, _ = resolve_source(store, reference["relative_path"], reference["root_id"])
    except Fault as error:
        if error.code == "SOURCE_ROOT_DENIED":
            raise Fault("REFERENCE_ROOT_UNAVAILABLE", "Use snapshot mode or configure the approved NAS reference mount.") from None
        raise
    before = stable_stat(path)
    if path.stat().st_size != record["size"] or digest_file(path) != record["sha"] or stable_stat(path) != before:
        raise Fault("REFERENCE_CHANGED", "Register a new version or snapshot before processing.")
    return path


def associate(store, identity, record, filename, identifier=None, source=None, selected=True):
    if record["state"] != "LIVE":
        raise Fault("FILE_UNAVAILABLE")
    if record["mode"] == "reference":
        reference_path(store, record)
    elif record["mode"] == "artifact":
        with store.db() as db:
            job = db.execute("SELECT expires,status FROM jobs WHERE id=?", (json.loads(record["info"])["job_id"],)).fetchone()
        if not job or job["expires"] <= time.time() or job["status"] not in ("SUCCEEDED", "PARTIAL"):
            raise Fault("CACHE_EXPIRED")
    elif not (store.root/record["path"]).is_file():
        raise Fault("FILE_UNAVAILABLE")
    scope = owner(identity)
    if not selected:
        if identifier:
            with store.db() as db:
                db.execute("INSERT INTO attachments VALUES(?,?,?,?,?,?,?,?,?,?,0)", (identifier, scope, filename,
                    record["sha"], record["size"], record["info"], time.time(), record["id"], store.agent(identity),
                    json.dumps({"filename": filename, "origin": "catalog-registration", **(source or {})})))
        return {"status": "REGISTERED", "file_id": record["id"], "filename": filename,
                "mode": record["mode"], "bytes": record["size"], "sha256": record["sha"], "category": record["category"],
                "kind": json.loads(record["info"])["kind"], "selected": False, "reused": True}
    with store.db() as db:
        existing = db.execute("SELECT id FROM attachments WHERE owner=? AND file_id=? AND active=1", (scope, record["id"])).fetchone()
        if existing and identifier is None:
            return {**store.inspect(identity, existing[0], lightweight=True), "status": "REGISTERED", "mode": record["mode"], "reused": True}
        if db.execute("SELECT COUNT(*) FROM attachments WHERE owner=? AND active=1", (scope,)).fetchone()[0] >= store.limits.max_references_per_session:
            raise Fault("SESSION_REFERENCE_LIMIT")
        identifier = identifier or uuid.uuid4().hex
        db.execute("INSERT INTO attachments VALUES(?,?,?,?,?,?,?,?,?,?,1)", (identifier, scope, filename, record["sha"],
            record["size"], record["info"], time.time(), record["id"], store.agent(identity), json.dumps({
                "filename": filename, "received_at": timestamp(), "origin": "registered-file", "message_id": None, **(source or {})})))
    return {**store.inspect(identity, identifier, lightweight=True), "status": "REGISTERED", "mode": record["mode"], "reused": True}


def register_source(store, identity, params, trusted_media=False):
    strict(params, ("source_path", "source_root", "file_id", "mode", "request_id", "source", "filename", "select"))
    selected = params.get("select", True)
    if not isinstance(selected, bool):
        raise Fault("INVALID_PARAMETERS")
    if not store.limits.workspace_mode:
        raise Fault("WORKSPACE_MAPPING_REQUIRED")
    if bool(params.get("file_id")) == bool(params.get("source_path")):
        raise Fault("CHOOSE_FILE_OR_PATH")
    if params.get("mode", "snapshot") not in ("snapshot", "reference"):
        raise Fault("INVALID_REGISTRATION_MODE")
    if not isinstance(params.get("source", {}), dict):
        raise Fault("INVALID_PARAMETERS")
    with store.lock:
        agent, scope = store.agent(identity), owner(identity)
        if params.get("file_id"):
            with store.db() as db:
                row = db.execute("SELECT * FROM files WHERE id=? AND agent=?", (valid_id(params["file_id"]), agent)).fetchone()
                if not row:
                    raise Fault("NOT_FOUND")
                name = db.execute("SELECT filename FROM attachments WHERE file_id=? LIMIT 1", (row["id"],)).fetchone()
            return associate(store, identity, dict(row), name[0] if name else Path(row["path"]).name, selected=selected)
        path, root_id, relative = resolve_source(store, params["source_path"], params.get("source_root", "workspace"), trusted_media)
        filename = params.get("filename", path.name)
        if not isinstance(filename, str) or Path(filename).name != filename or any(c in filename for c in "\\/\0\r\n") or not 1 <= len(filename) <= 200:
            raise Fault("INVALID_FILENAME")
        # Managed originals/products can only be reused through existing complete records.
        try:
            managed_relative = str(path.relative_to(Path(str(store.root).removeprefix("\\\\?\\"))))
        except ValueError:
            managed_relative = None
        if managed_relative is not None:
            with store.db() as db:
                row = db.execute("SELECT * FROM files WHERE agent=? AND path=? AND state='LIVE'", (agent, managed_relative)).fetchone()
            if not row:
                raise Fault("UNPUBLISHED_MANAGED_FILE", "Use a published artifact or registered file ID.")
            return associate(store, identity, dict(row), filename, selected=selected)
        before = stable_stat(path)
        sha = digest_file(path)
        if stable_stat(path) != before:
            raise Fault("SOURCE_CHANGED")
        mode = params.get("mode", "snapshot")
        fingerprint_fields = [root_id, relative, sha, mode, filename, params.get("source", {})]
        if not selected:
            fingerprint_fields.append("catalog-only")
        fingerprint = hashlib.sha256(json.dumps(fingerprint_fields, sort_keys=True).encode()).hexdigest()
        request_id = valid_id(params.get("request_id", fingerprint[:32]))
        with store.db() as db:
            previous = db.execute("SELECT * FROM registration_requests WHERE scope=? AND request_id=?", (scope, request_id)).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise Fault("REQUEST_CONFLICT")
                result = json.loads(previous["result"])
                if selected:
                    store.attachment(identity, result["attachment_id"])
                else:
                    row = db.execute("SELECT * FROM files WHERE id=? AND agent=?", (result["file_id"], agent)).fetchone()
                    if not row or row["state"] != "LIVE":
                        raise Fault("FILE_UNAVAILABLE")
                return {**result, "reused": True}
        if mode == "snapshot":
            result = store.register(identity, request_id, filename, path, {"origin": "canonical-attachment" if trusted_media else "local-registration",
                "source_message_id": params.get("source", {}).get("message_id") if trusted_media else None,
                "source_description": params.get("source", {}), "source_root": root_id, "source_relative_path": relative}, selected=selected)
        else:
            detected = identify(path, filename)
            details = {**detected, "units": 0, "preview": [], "deferred_inspection": True,
                       "external_reference": {"root_id": root_id, "relative_path": relative}, "source_description": params.get("source", {}),
                       "source_version": list(before)}
            file_id = uuid.uuid4().hex
            with store.db() as db:
                db.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?,?)", (file_id, agent, sha, before[2],
                    category_v12(detected["category"]), "", json.dumps(details), timestamp(), "LIVE", "reference"))
                row = dict(db.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone())
            try:
                result = associate(store, identity, row, filename, request_id, selected=selected)
            except Exception:
                with store.db() as db:
                    db.execute("DELETE FROM files WHERE id=?", (file_id,))
                raise
        if stable_stat(path) != before:
            # Never advertise a content/version that changed during registration.
            with store.db() as db:
                db.execute("UPDATE attachments SET active=0 WHERE owner=? AND id=?", (scope, request_id))
            raise Fault("SOURCE_CHANGED")
        result.update(status="REGISTERED", mode=mode, selected=selected, source_root=root_id, source_relative_path=relative,
                      content_trust="untrusted", source_description_trust="untrusted")
        with store.db() as db:
            registered = db.execute("SELECT path,sha,category,info FROM files WHERE id=?", (result["file_id"],)).fetchone()
        result.update(sha256=registered["sha"], category=registered["category"], kind=json.loads(registered["info"])["kind"])
        result.update(file_reference=({"gateway_path": str(path), "external": True} if mode == "reference" else
            public_reference(store, store.root/registered["path"])))
        with store.db() as db:
            db.execute("INSERT INTO registration_requests VALUES(?,?,?,?)", (scope, request_id, fingerprint, json.dumps(result)))
        return result


def readable_text(path, limits):
    detected = identify(path, Path(path).name)
    if detected["kind"] != "text" and detected["type_confidence"] != "bounded-text-heuristic":
        raise Fault("BINARY_ARTIFACT", "Use the published file reference for binary results.")
    if Path(path).stat().st_size > limits.max_text_bytes:
        raise Fault("TEXT_SIZE_LIMIT")
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except UnicodeError:
        raise Fault("TEXT_ENCODING_UNSUPPORTED") from None
    if "\0" in text or any(ord(c)<32 and c not in "\t\r\n" for c in text):
        raise Fault("BINARY_ARTIFACT")
    return text


def public_reference(store, path):
    relative = Path(path).relative_to(store.root).as_posix()
    if not store.limits.workspace_mode:
        return {"management_relative_path": relative}
    return {"workspace_relative_path": "filetools/"+relative,
            "gateway_path": str(Path(store.limits.gateway_workspace)/"filetools"/relative)}


def artifact_access(store, identity, action, params):
    row = store.job(identity, params.get("job_id"))
    if row["expires"] <= time.time():
        raise Fault("CACHE_EXPIRED")
    manifest = store.manifest(row)
    identifier = valid_id(params.get("artifact_id"))
    selected = next((a for a in manifest["artifacts"] if a["artifact_id"] == identifier), None)
    if not selected:
        raise Fault("UNREADABLE_ARTIFACT")
    path = store.task(row["id"])/selected["file"]
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(store.task(row["id"]).resolve()):
        raise Fault("ARTIFACT_UNAVAILABLE")
    result = {"status": "TOUCHED" if action == "touch" else "FILE_REFERENCE", "artifact_id": identifier,
              "job_id": row["id"], "file_id": selected.get("file_id"), "format": selected.get("format") or identify(path, path.name)["actual_type"],
              "bytes": path.stat().st_size, "sha256": digest_file(path), **public_reference(store, path)}
    if selected["kind"] != "sources" and selected.get("sha256") and result["sha256"] != selected["sha256"]:
        raise Fault("ARTIFACT_CHANGED", "Use a fresh verified result or register the intended new version.")
    if action == "touch":
        store.touch(row["id"])
    return result


def register_products(store, identity, manifest, live=False, folder=None, mode="artifact"):
    """Published files become directly managed products; no second snapshot copy."""
    if not store.limits.workspace_mode:
        return
    with store.db() as db:
        for artifact in manifest["artifacts"]:
            if artifact["kind"] == "sources" or artifact.get("file_id"):
                continue  # Its self-referential manifest is managed metadata, not a business output.
            path = (Path(folder) if folder else store.task(manifest["job_id"]))/artifact["file"]
            if not path.is_file() or path.is_symlink():
                raise Fault("ARTIFACT_UNAVAILABLE")
            detected = identify(path, path.name)
            file_id = uuid.uuid4().hex
            relative = str(path.relative_to(store.root))
            details = {**detected, "job_id": manifest["job_id"], "input_file_id": manifest["file_id"], "artifact_id": artifact["artifact_id"],
                       "units": 0, "deferred_inspection": True, "cache_expires": manifest["expires_at"] if mode == "artifact" else None}
            db.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?,?)", (file_id, store.agent(identity), digest_file(path), path.stat().st_size,
                category_v12(detected["category"]), relative, json.dumps(details), timestamp(), "LIVE" if live else "PUBLISHED", mode))
            artifact.update(file_id=file_id, format=detected["actual_type"], bytes=path.stat().st_size,
                            sha256=digest_file(path), **public_reference(store, path))
