"""Persistent one-Agent files, explicit session selection and independent saved versions."""
import hashlib
import json
import os
import shutil
import threading
import time
import sys
import uuid
from pathlib import Path

from .catalog import CATEGORIES, atomic_json, copy_stream, digest_file, identify, timestamp, sync_directory
from .contracts import Fault, options, owner, valid_id, integer


class WorkspaceStore:
    def __init__(self, root, limits):
        given = Path(root)
        if given.is_symlink():
            raise Fault("UNSAFE_STATE_DIRECTORY")
        self.root = given.resolve()
        if sys.platform == "linux" and limits.script_isolation == "landlock" and any(
                self.root.is_relative_to(Path(p).resolve()) for p in ("/usr", "/lib", "/lib64", sys.prefix, sys.base_prefix)):
            raise Fault("DATA_ROOT_OVERLAPS_READABLE_SYSTEM_LIBRARIES")
        if os.name == "nt" and not str(self.root).startswith("\\\\?\\"):
            self.root = Path("\\\\?\\" + str(self.root))
        self.limits, self.lock = limits, threading.RLock()
        for name in ("agents", "incoming"):
            self.directory(self.root / name)
        with self.db() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "attachments" in tables and "files" not in tables:
                raise Fault("V1_MIGRATION_REQUIRED")
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS files(
                  id TEXT PRIMARY KEY, agent TEXT NOT NULL, sha TEXT NOT NULL, size INTEGER NOT NULL,
                  category TEXT NOT NULL, path TEXT NOT NULL, info TEXT NOT NULL, created TEXT NOT NULL,
                  state TEXT NOT NULL DEFAULT 'LIVE');
                CREATE UNIQUE INDEX IF NOT EXISTS files_dedup ON files(agent,sha) WHERE state='LIVE';
                CREATE TABLE IF NOT EXISTS attachments(
                  id TEXT NOT NULL, owner TEXT NOT NULL, filename TEXT NOT NULL, sha TEXT NOT NULL,
                  size INTEGER NOT NULL, info TEXT NOT NULL, created REAL NOT NULL,
                  file_id TEXT NOT NULL, agent TEXT NOT NULL, source TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                  PRIMARY KEY(owner,id));
                CREATE TABLE IF NOT EXISTS jobs(
                  id TEXT PRIMARY KEY, owner TEXT NOT NULL, attachment TEXT NOT NULL, fingerprint TEXT NOT NULL,
                  config TEXT NOT NULL, status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
                  created REAL NOT NULL, updated REAL NOT NULL, expires REAL NOT NULL, cancel INTEGER DEFAULT 0,
                  agent TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'extract', payload TEXT NOT NULL DEFAULT '{}',
                  prompted INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner,fingerprint);
                CREATE TABLE IF NOT EXISTS saved(
                  id TEXT PRIMARY KEY, agent TEXT NOT NULL, file_id TEXT NOT NULL, job_id TEXT NOT NULL,
                  path TEXT NOT NULL, created TEXT NOT NULL, info TEXT NOT NULL);
            """)
        for agent in limits.enabled_agents:
            self.initialize(agent)
        with self.db() as db:
            pending_deletes = [dict(row) for row in db.execute("SELECT * FROM files WHERE state='DELETING'")]
        for row in pending_deletes:
            # The committed DELETING marker records an already authorized exact deletion.
            self.finish_delete(row)
        with self.db() as db:
            # Never advertise missing snapshots after a crash/operator filesystem change.
            for row in db.execute("SELECT id,path FROM files WHERE state='LIVE'").fetchall():
                if not (self.root/row["path"]).is_file() or (self.root/row["path"]).is_symlink():
                    db.execute("UPDATE files SET state='MISSING' WHERE id=?", (row["id"],))
                    db.execute("UPDATE attachments SET active=0 WHERE file_id=?", (row["id"],))

    @staticmethod
    def directory(path):
        if path.is_symlink():
            raise Fault("UNSAFE_STATE_DIRECTORY")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)

    def agent(self, identity):
        owner(identity)
        agent = identity["agent_id"]
        if agent not in self.limits.enabled_agents:
            raise Fault("FORBIDDEN")
        return agent

    def initialize(self, agent):
        if agent not in self.limits.enabled_agents:
            raise Fault("FORBIDDEN")
        home = self.root / "agents" / agent
        self.directory(home)
        for area in ("inbox", "cache", "snapshots", "saved"):
            self.directory(home / area)
        for area in ("snapshots", "saved"):
            for category in CATEGORIES:
                self.directory(home / area / category)
        return home

    def task(self, identifier):
        with self.db() as db:
            row = db.execute("SELECT agent FROM jobs WHERE id=?", (valid_id(identifier),)).fetchone()
        if not row:
            raise Fault("NOT_FOUND")
        return self.root / "agents" / row[0] / "cache" / identifier

    def original(self, scope, identifier, filename):
        with self.db() as db:
            row = db.execute("SELECT f.path FROM files f JOIN attachments a ON a.file_id=f.id "
                             "WHERE a.owner=? AND a.id=? AND f.state='LIVE'", (scope, identifier)).fetchone()
        if not row:
            raise Fault("NOT_FOUND")
        return self.root / row[0]

    def capacity(self, identity):
        agent = self.agent(identity)
        with self.db() as db:
            snapshots = db.execute("SELECT COALESCE(SUM(size),0) FROM files WHERE agent=? AND state='LIVE'",
                                   (agent,)).fetchone()[0]
        home = self.initialize(agent)
        sizes = {}
        physical_snapshots = sum(p.stat().st_size for p in (home/"snapshots").rglob("*") if p.is_file() and not p.is_symlink())
        for area in ("saved", "cache"):
            sizes[area] = sum(p.stat().st_size for p in (home / area).rglob("*") if p.is_file() and not p.is_symlink())
        disk = shutil.disk_usage(self.root)
        quotas = {"snapshots": self.limits.snapshot_quota_bytes, "saved": self.limits.saved_quota_bytes,
                  "cache": self.limits.cache_quota_bytes}
        usage = {"snapshots": physical_snapshots, **sizes}
        return {"status": "CAPACITY", "usage_bytes": usage, "quota_bytes": quotas, "disk_free_bytes": disk.free,
                "registered_snapshot_bytes": snapshots, "snapshot_orphan_bytes": max(0, physical_snapshots-snapshots),
                "warnings": [k for k in usage if usage[k]*100 >= quotas[k]*self.limits.quota_warning_percent],
                "disk_reserve_bytes": self.limits.disk_reserve_bytes}

    def room(self, identity, area, additional):
        capacity = self.capacity(identity)
        if capacity["usage_bytes"][area] + additional > capacity["quota_bytes"][area]:
            raise Fault("DISK_QUOTA")
        if capacity["disk_free_bytes"] - additional < self.limits.disk_reserve_bytes:
            raise Fault("DISK_RESERVE")

    def register(self, identity, identifier, filename, incoming, info=None):
        # Cross-request copies are serialized; SQLite unique index remains the final dedup guard.
        with self.lock:
            return self._register(identity, identifier, filename, incoming, info)

    def _register(self, identity, identifier, filename, incoming, info=None):
        agent, scope = self.agent(identity), owner(identity)
        valid_id(identifier)
        if (not isinstance(filename, str) or not 1 <= len(filename) <= 200 or Path(filename).name != filename or
                any(c in filename for c in "\\/\r\n\0")):
            raise Fault("INVALID_FILENAME")
        incoming = Path(incoming)
        if incoming.is_symlink() or not incoming.is_file():
            raise Fault("UNSAFE_ATTACHMENT")
        before = incoming.stat()
        if not 0 < before.st_size <= self.limits.max_receive_bytes:
            raise Fault("RECEIVE_SIZE_LIMIT")
        detected = identify(incoming, filename)
        sha = digest_file(incoming)
        with self.db() as db:
            previous = db.execute("SELECT * FROM attachments WHERE owner=? AND id=?", (scope, identifier)).fetchone()
            if previous:
                if previous["sha"] != sha or previous["filename"] != filename or not previous["active"]:
                    raise Fault("ATTACHMENT_CHANGED")
                return {**self.inspect(identity, identifier, lightweight=True), "reused": True}
            count = db.execute("SELECT COUNT(*) FROM attachments WHERE owner=? AND active=1", (scope,)).fetchone()[0]
            if count >= self.limits.max_references_per_session:
                raise Fault("SESSION_REFERENCE_LIMIT")
            record = db.execute("SELECT * FROM files WHERE agent=? AND sha=? AND state='LIVE'", (agent, sha)).fetchone()
            reused = record is not None
            if record is None:
                self.room(identity, "snapshots", before.st_size)
                file_id = uuid.uuid4().hex
                target = self.initialize(agent) / "snapshots" / detected["category"] / (file_id+detected["extension"])
                temporary = target.with_name(target.name+".receiving-"+uuid.uuid4().hex)
                try:
                    with incoming.open("rb") as source:
                        copy_stream(source, temporary, self.limits.max_receive_bytes, before.st_size, sha)
                    after = incoming.stat()
                    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                        raise Fault("ATTACHMENT_CHANGED")
                    os.replace(temporary, target)
                    os.chmod(target, 0o600)
                    sync_directory(target.parent)
                    details = {**(info or {}), **detected}
                    details.setdefault("units", 0)
                    details.setdefault("preview", [])
                    details["deferred_inspection"] = (info or {}).get("deferred_inspection", "units" not in (info or {}))
                    db.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?,?,'LIVE')", (file_id, agent, sha, before.st_size,
                        detected["category"], str(target.relative_to(self.root)), json.dumps(details), timestamp()))
                finally:
                    temporary.unlink(missing_ok=True)
                record = db.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
            else:
                if not (self.root / record["path"]).is_file():
                    raise Fault("SNAPSHOT_MISSING")
                if digest_file(self.root/record["path"]) != record["sha"]:
                    raise Fault("SNAPSHOT_CHANGED")
            source = {"message_id": (info or {}).get("source_message_id"), "filename": filename,
                      "received_at": timestamp(), "origin": (info or {}).get("origin", "attachment")}
            db.execute("INSERT INTO attachments VALUES(?,?,?,?,?,?,?,?,?,?,1)", (identifier, scope, filename, sha,
                record["size"], record["info"], time.time(), record["id"], agent, json.dumps(source)))
        result = self.inspect(identity, identifier, lightweight=True)
        return {**result, "reused": reused, "receipt": {"status": "RECEIVED", "filename": filename,
                                                      "bytes": before.st_size, "file_id": record["id"]}}

    def attachment(self, identity, identifier):
        self.agent(identity)
        with self.db() as db:
            row = db.execute("SELECT a.*,f.state FROM attachments a JOIN files f ON f.id=a.file_id "
                             "WHERE a.owner=? AND a.id=? AND a.active=1", (owner(identity), valid_id(identifier))).fetchone()
        if not row or row["state"] != "LIVE":
            raise Fault("NOT_FOUND")
        return dict(row)

    def inspect(self, identity, identifier=None, lightweight=False):
        self.agent(identity)
        if identifier is None:
            with self.db() as db:
                rows = db.execute("SELECT a.id,a.file_id,a.filename,a.size FROM attachments a JOIN files f ON f.id=a.file_id "
                                  "WHERE a.owner=? AND a.active=1 AND f.state='LIVE' ORDER BY a.created", (owner(identity),)).fetchall()
            return {"status": "AVAILABLE", "attachments": [{"attachment_id": r["id"], "file_id": r["file_id"],
                     "filename": r["filename"], "bytes": r["size"]} for r in rows]}
        row = self.attachment(identity, identifier)
        info = json.loads(row["info"])
        if info.get("deferred_inspection") and not lightweight and info["kind"] != "unsupported":
            from .worker import bounded_probe
            try:
                parsed = bounded_probe(self.original(row["owner"], identifier, row["filename"]), self.limits,
                                       self.root / "incoming")
                info.update(parsed)
                info["deferred_inspection"] = False
            except Fault as error:
                info.update(parse_error=error.code, deferred_inspection=False)
            with self.db() as db:
                db.execute("UPDATE attachments SET info=? WHERE file_id=?", (json.dumps(info), row["file_id"]))
                db.execute("UPDATE files SET info=? WHERE id=?", (json.dumps(info), row["file_id"]))
        return {"status": "INSPECTED", "attachment_id": identifier, "file_id": row["file_id"],
                "filename": row["filename"], "bytes": row["size"], "sha256": row["sha"],
                "source": json.loads(row["source"]), "content_trust": "untrusted", **info}

    def submit(self, identity, identifier, raw):
        self.agent(identity)
        inspected = self.inspect(identity, identifier)
        config = options(raw, inspected)
        if inspected["bytes"] > self.limits.max_process_bytes:
            raise Fault("PROCESS_SIZE_LIMIT")
        return self.create_job(identity, identifier, config, "extract", {}, inspected)

    def create_job(self, identity, identifier, config, kind, payload, inspected=None):
        scope, agent = owner(identity), self.agent(identity)
        attachment = self.attachment(identity, identifier)
        from .engines import version
        engines = {k: version(k) for k in ("PyMuPDF", "python-docx", "rapidocr-onnxruntime", "faster-whisper", "openpyxl")}
        fingerprint = hashlib.sha256(json.dumps([attachment["sha"], config, kind, payload, self.limits.dict(),
                                                engines, "1.1.0"], sort_keys=True).encode()).hexdigest()
        with self.db() as db:
            cached = db.execute("SELECT id FROM jobs WHERE owner=? AND fingerprint=? AND expires>? AND status IN "
                                "('QUEUED','RUNNING','SUCCEEDED','PARTIAL') ORDER BY created DESC LIMIT 1",
                                (scope, fingerprint, time.time())).fetchone()
            if cached:
                self.touch(cached[0])
                return {**self.status(identity, cached[0]), "reused": True}
            count = db.execute("SELECT COUNT(*) FROM jobs WHERE owner=? AND (expires>? OR status IN ('QUEUED','RUNNING'))",
                               (scope, time.time())).fetchone()[0]
            if count >= self.limits.max_jobs_per_scope:
                raise Fault("JOB_QUOTA")
            self.room(identity, "cache", self.limits.max_asset_bytes)
            job_id, now = uuid.uuid4().hex, time.time()
            db.execute("INSERT INTO jobs(id,owner,attachment,fingerprint,config,status,created,updated,expires,agent,kind,payload) "
                       "VALUES(?,?,?,?,?,'QUEUED',?,?,?,?,?,?)", (job_id, scope, identifier, fingerprint, json.dumps(config),
                       now, now, now+self.limits.ttl_seconds, agent, kind, json.dumps(payload)))
            out = self.initialize(agent)/"cache"/job_id
            self.directory(out)
            (out / "content.md").write_text("", encoding="utf-8")
            atomic_json(out / "sources.json", {"schema_version": "1.1", "job_id": job_id, "attachment_id": identifier,
                "file_id": attachment["file_id"], "original": {"filename": attachment["filename"], "sha256": attachment["sha"],
                "bytes": attachment["size"], "message_id": json.loads(attachment["source"])["message_id"]},
                "status": "QUEUED", "created_at": timestamp(now), "config": config, "engines": engines,
                "coverage": {"kind": (inspected or {}).get("kind", "script"), "processed": [], "full_document": False},
                "segments": [], "artifacts": [], "failures": [], "warnings": [], "content_trust": "untrusted"})
        return {**self.status(identity, job_id), "reused": False}

    def job(self, identity, identifier):
        self.agent(identity)
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=? AND owner=?", (valid_id(identifier), owner(identity))).fetchone()
        if not row:
            raise Fault("NOT_FOUND", "Cache expired or unknown; select the persistent snapshot and extract again.")
        return dict(row)

    def touch(self, identifier):
        now = time.time()
        with self.db() as db:
            db.execute("UPDATE jobs SET expires=? WHERE id=?", (now+self.limits.ttl_seconds, identifier))

    def status(self, identity, identifier):
        result = super().status(identity, identifier)
        row = self.job(identity, identifier)
        result.update(expires_at=timestamp(row["expires"]), created_at=timestamp(row["created"]), kind=row["kind"])
        checkpoint = self.task(identifier)/"checkpoint.json"
        if checkpoint.exists() and checkpoint.stat().st_size <= self.limits.max_manifest_bytes:
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            result["processed_time_ranges"] = [[c["start"], c["end"]] for c in saved.get("chunks", []) if c["status"]=="DONE"]
        return result

    def read(self, identity, identifier, raw, find=False):
        with self.lock:
            row = self.job(identity, identifier)
            if row["expires"] <= time.time() and row["status"] not in ("QUEUED", "RUNNING"):
                raise Fault("CACHE_EXPIRED", "Select persistent snapshot and extract again.")
            result = super().read(identity, identifier, raw, find)
            if result.get("evidence") or result.get("text"):
                self.touch(identifier)
            return result

    def save_minutes(self, identity, identifier, text, source_segments):
        with self.lock:
            result = super().save_minutes(identity, identifier, text, source_segments)
            self.touch(identifier)
            return result

    def files(self, identity, action, **params):
        agent, scope = self.agent(identity), owner(identity)
        if action == "offer_save":
            job = self.job(identity, params.get("job_id"))
            if job["status"] not in ("SUCCEEDED", "PARTIAL"):
                raise Fault("NOT_READY")
            with self.db() as db:
                changed = db.execute("UPDATE jobs SET prompted=1 WHERE id=? AND prompted=0", (job["id"],)).rowcount
            return {"status": "SAVE_OFFER", "ask_once": bool(changed), "job_id": job["id"]}
        if action == "capacity":
            return self.capacity(identity)
        if action == "list":
            offset = integer(params.get("offset", 0), 0, 10000000)
            area = params.get("area", "snapshots")
            if area == "inbox":
                return self.inbox_list(identity)
            if area not in ("snapshots", "saved"):
                raise Fault("INVALID_PARAMETERS")
            with self.db() as db:
                if area == "saved":
                    rows = db.execute("SELECT id,created,info FROM saved WHERE agent=? ORDER BY created DESC LIMIT 101 OFFSET ?", (agent, offset)).fetchall()
                    items = [{"saved_id": r["id"], "created_at": r["created"], **json.loads(r["info"])} for r in rows]
                else:
                    rows = db.execute("SELECT id,sha,size,category,created FROM files WHERE agent=? AND state='LIVE' "
                                      "ORDER BY created DESC LIMIT 101 OFFSET ?", (agent, offset)).fetchall()
                    items = []
                    for r in rows:
                        names = db.execute("SELECT filename,source,active FROM attachments WHERE file_id=? LIMIT 20", (r["id"],)).fetchall()
                        items.append({"file_id": r["id"], "sha256": r["sha"], "bytes": r["size"], "category": r["category"],
                            "first_received_at": r["created"], "uploads": [{"filename": a["filename"], **json.loads(a["source"]),
                                                                         "active": bool(a["active"])} for a in names]})
            return {"status": "FILES", "area": area, "items": items[:100], "truncated": len(items)>100,
                    "next_offset": offset+100 if len(items)>100 else None}
        if action == "select":
            file_id = valid_id(params.get("file_id"))
            with self.db() as db:
                row = db.execute("SELECT * FROM files WHERE id=? AND agent=? AND state='LIVE'", (file_id, agent)).fetchone()
                if not row:
                    raise Fault("NOT_FOUND")
                existing = db.execute("SELECT id FROM attachments WHERE owner=? AND file_id=? AND active=1", (scope, file_id)).fetchone()
                if existing:
                    return self.inspect(identity, existing[0], lightweight=True)
                original = db.execute("SELECT filename FROM attachments WHERE file_id=? ORDER BY created LIMIT 1", (file_id,)).fetchone()
                return self.register(identity, uuid.uuid4().hex, original[0], self.root / row["path"], json.loads(row["info"]))
        if action == "save":
            return self.save_result(identity, params.get("job_id"), params.get("artifact_id"))
        if action == "saved_read":
            return self.saved_read(identity, params.get("saved_id"), params.get("offset", 0), params.get("artifact_id"))
        if action == "delete_cache":
            job = self.job(identity, params.get("job_id"))
            if job["status"] in ("QUEUED", "RUNNING"):
                raise Fault("FILE_BUSY")
            return self.remove_cache(job)
        if action in ("delete_original", "remove_reference"):
            return self.delete_file(identity, action, params)
        if action == "inbox_register":
            return self.inbox_register(identity, params.get("inbox_id"))
        if action == "resume":
            job = self.job(identity, params.get("job_id"))
            if job["status"] not in ("INTERRUPTED", "CANCELLED", "TIMED_OUT", "PARTIAL", "FAILED"):
                raise Fault("NOT_RESUMABLE")
            if job["kind"] != "extract":
                raise Fault("NOT_RESUMABLE")
            original = self.original(scope, job["attachment"], "")
            if digest_file(original) != self.attachment(identity, job["attachment"])["sha"]:
                raise Fault("ATTACHMENT_CHANGED")
            with self.db() as db:
                db.execute("UPDATE jobs SET status='QUEUED',cancel=0,expires=?,updated=? WHERE id=?",
                           (time.time()+self.limits.ttl_seconds, time.time(), job["id"]))
            return self.status(identity, job["id"])
        raise Fault("UNKNOWN_ACTION")

    def save_result(self, identity, identifier, artifact_id=None):
        with self.lock:
            job = self.job(identity, identifier)
            if job["status"] not in ("SUCCEEDED", "PARTIAL"):
                raise Fault("NOT_READY")
            manifest = self.manifest(job)
            selected = [a for a in manifest["artifacts"] if not artifact_id or a["artifact_id"] == valid_id(artifact_id)]
            if not selected:
                raise Fault("UNREADABLE_ARTIFACT")
            saved_id = uuid.uuid4().hex
            source = self.task(identifier)
            category = identify(source/selected[0]["file"], selected[0]["file"])["category"]
            destination = self.initialize(job["agent"]) / "saved" / category / saved_id
            temporary = destination.with_name(".saving-"+saved_id)
            # All source records/images are necessary dependencies; preserve bundle, even for one selected item.
            source = self.task(identifier)
            inputs = [source/a["file"] for a in manifest["artifacts"] if a["kind"] != "sources"]
            inputs.append(source/"sources.json")
            size = sum(p.stat().st_size for p in inputs)
            self.room(identity, "saved", size)
            self.directory(temporary)
            try:
                saved_manifest = json.loads(json.dumps(manifest))
                for file in inputs:
                    if file.is_symlink() or file.resolve().is_relative_to(source.resolve()) is False:
                        raise Fault("UNSAFE_ARTIFACT")
                    target = temporary/file.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(file, target)
                # Saved Markdown uses actual relative links, independent of cache lifetime.
                for artifact in saved_manifest["artifacts"]:
                    if artifact["kind"] in ("content", "transcript", "minutes"):
                        file = temporary/artifact["file"]
                        text = file.read_text(encoding="utf-8")
                        for image in saved_manifest["artifacts"]:
                            if image["kind"] == "image":
                                text = text.replace("artifact:"+image["artifact_id"], image["file"])
                        file.write_text(text, encoding="utf-8")
                atomic_json(temporary/"saved.json", {"saved_id": saved_id, "saved_at": timestamp(), "source": saved_manifest,
                            "selected_artifacts": [a["artifact_id"] for a in selected], "original_state": "LIVE"})
                os.replace(temporary, destination)
                with self.db() as db:
                    attachment = self.attachment(identity, job["attachment"])
                    db.execute("INSERT INTO saved VALUES(?,?,?,?,?,?,?)", (saved_id, job["agent"], attachment["file_id"],
                        identifier, str(destination.relative_to(self.root)), timestamp(), json.dumps({"category": category,
                        "selected_artifacts": [a["artifact_id"] for a in selected], "original_state": "LIVE"})))
            except Exception:
                # Preserve original cache on any error. An unregistered published bundle is retained for diagnosis.
                if temporary.exists():
                    shutil.rmtree(temporary)
                raise
            self.touch(identifier)
            with self.db() as db:
                db.execute("UPDATE jobs SET prompted=1 WHERE id=?", (identifier,))
            return {"status": "SAVED", "saved_id": saved_id, "version": saved_id, "bytes": size}

    def saved_read(self, identity, saved_id, offset, artifact_id=None):
        agent = self.agent(identity)
        with self.db() as db:
            row = db.execute("SELECT * FROM saved WHERE id=? AND agent=?", (valid_id(saved_id), agent)).fetchone()
        if not row:
            raise Fault("NOT_FOUND")
        folder = self.root/row["path"]
        info = json.loads((folder/"saved.json").read_text(encoding="utf-8"))
        chosen = valid_id(artifact_id) if artifact_id else info["selected_artifacts"][0]
        artifact = next((a for a in info["source"]["artifacts"] if a["artifact_id"] == chosen), None)
        if not artifact:
            raise Fault("UNREADABLE_ARTIFACT")
        result = {"status": "SAVED_FILE", "saved_id": saved_id, "artifact": artifact, "original_state": info["original_state"]}
        if artifact["kind"] in ("content", "transcript", "minutes", "sources"):
            text = (folder/artifact["file"]).read_text(encoding="utf-8")
            start = integer(offset, 0, self.limits.max_manifest_bytes)
            result.update(text=text[start:start+self.limits.max_read_chars],
                          next_offset=start+self.limits.max_read_chars if start+self.limits.max_read_chars<len(text) else None)
        return result

    def delete_file(self, identity, action, params):
        agent, scope = self.agent(identity), owner(identity)
        with self.db() as db:
            if action == "remove_reference":
                attachment = self.attachment(identity, params.get("attachment_id"))
                busy = db.execute("SELECT 1 FROM jobs WHERE owner=? AND attachment=? AND status IN ('RUNNING','QUEUED')",
                                  (scope, attachment["id"])).fetchone()
                if busy:
                    raise Fault("FILE_BUSY")
                db.execute("UPDATE attachments SET active=0 WHERE owner=? AND id=?", (scope, attachment["id"]))
                return {"status": "REFERENCE_REMOVED", "snapshot_deleted": False}
            file_id = valid_id(params.get("file_id"))
            row = db.execute("SELECT * FROM files WHERE id=? AND agent=? AND state='LIVE'", (file_id, agent)).fetchone()
            if not row:
                raise Fault("NOT_FOUND")
            busy = db.execute("SELECT 1 FROM jobs j JOIN attachments a ON a.owner=j.owner AND a.id=j.attachment "
                              "WHERE a.file_id=? AND j.status IN ('RUNNING','QUEUED')", (file_id,)).fetchone()
            if busy:
                raise Fault("FILE_BUSY")
            # Explicit deletion of a unique file means all its references; no dangling live rows.
            path = self.root/row["path"]
            if path.is_symlink() or not path.resolve().is_relative_to((self.root/"agents"/agent/"snapshots").resolve()):
                raise Fault("UNSAFE_DELETE")
            db.execute("UPDATE files SET state='DELETING' WHERE id=?", (file_id,))
        self.finish_delete(dict(row))
        return {"status": "DELETED", "file_id": file_id, "saved_results_preserved": True, "all_references_removed": True}

    def finish_delete(self, row):
        file_id = row["id"]
        path = self.root/row["path"]
        expected = self.root/"agents"/row["agent"]/"snapshots"
        if path.is_symlink() or not path.resolve().is_relative_to(expected.resolve()):
            raise Fault("UNSAFE_DELETE")
        path.unlink(missing_ok=True)
        sync_directory(path.parent)
        with self.db() as db:
            db.execute("UPDATE files SET state='DELETED' WHERE id=?", (file_id,))
            db.execute("UPDATE attachments SET active=0 WHERE file_id=?", (file_id,))
            for saved in db.execute("SELECT * FROM saved WHERE file_id=?", (file_id,)).fetchall():
                info = json.loads(saved["info"])
                info["original_state"] = "DELETED"
                db.execute("UPDATE saved SET info=? WHERE id=?", (json.dumps(info), saved["id"]))
                file = self.root/saved["path"]/"saved.json"
                source = json.loads(file.read_text(encoding="utf-8"))
                source["original_state"] = "DELETED"
                atomic_json(file, source)

    def remove_cache(self, row):
        target = self.task(row["id"])
        expected = self.root/"agents"/row["agent"]/"cache"
        if target.is_symlink() or expected.is_symlink() or target.resolve().parent != expected.resolve():
            raise Fault("UNSAFE_CLEANUP_TARGET")
        if target.exists():
            shutil.rmtree(target)
        with self.db() as db:
            db.execute("DELETE FROM jobs WHERE id=?", (row["id"],))
        return {"status": "CACHE_DELETED", "job_id": row["id"], "snapshot_preserved": True}

    def cleanup(self, now=None):
        now = time.time() if now is None else now
        removed = []
        with self.lock:
            with self.db() as db:
                rows = db.execute("SELECT * FROM jobs WHERE expires<=? AND status NOT IN ('QUEUED','RUNNING')", (now,)).fetchall()
            for row in rows:
                self.remove_cache(dict(row))
                removed.append(row["id"])
        return {"status": "CLEANED", "removed_jobs": removed, "originals_deleted": 0}

    def inbox_list(self, identity):
        inbox = self.initialize(self.agent(identity))/"inbox"
        items = []
        for file in sorted(inbox.iterdir()):
            if not file.is_file() or file.is_symlink() or file.name.endswith((".ready", ".part", ".tmp")):
                continue
            items.append({"inbox_id": hashlib.sha256(file.name.encode()).hexdigest()[:32], "filename": file.name,
                          "bytes": file.stat().st_size, "ready": file.with_name(file.name+".ready").is_file()})
            if len(items) == 100:
                break
        return {"status": "INBOX", "items": items}

    def inbox_register(self, identity, identifier):
        valid_id(identifier)
        inbox = self.initialize(self.agent(identity))/"inbox"
        name = next((i["filename"] for i in self.inbox_list(identity)["items"] if i["inbox_id"] == identifier), None)
        if not name:
            raise Fault("NOT_FOUND")
        file = inbox/name
        marker = file.with_name(name+".ready")
        if not marker.is_file() or marker.is_symlink() or marker.stat().st_size > 1024:
            raise Fault("INBOX_INCOMPLETE")
        size = file.stat().st_size
        if not 0 < size <= self.limits.max_receive_bytes:
            raise Fault("RECEIVE_SIZE_LIMIT")
        try:
            ready = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise Fault("INBOX_INCOMPLETE") from None
        if (not isinstance(ready, dict) or set(ready) != {"bytes", "sha256"} or type(ready["bytes"]) is not int or
                ready["bytes"] != size or ready["sha256"] != digest_file(file)):
            raise Fault("INBOX_INCOMPLETE")
        return self.register(identity, uuid.uuid4().hex, name, file, {"origin": "nas-inbox"})
