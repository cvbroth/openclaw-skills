"""SQLite metadata and guarded per-task artifacts; originals live outside cleanup targets."""

import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .contracts import Fault, integer, options, owner, strict, valid_id

TERMINAL = ("SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED", "TIMED_OUT", "INTERRUPTED")


def write_json(path, value):
    temp = Path(str(path) + ".tmp")
    with temp.open("w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)


class Store:
    def __init__(self, root, limits):
        self.root = Path(root).resolve()
        if os.name == "nt" and not str(self.root).startswith("\\\\?\\"):
            self.root = Path("\\\\?\\" + str(self.root))
        self.limits = limits
        self.lock = threading.RLock()
        for name in ("originals", "tasks", "incoming"):
            if (self.root / name).is_symlink():
                raise Fault("UNSAFE_STATE_DIRECTORY")
            (self.root / name).mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS attachments(
                  id TEXT NOT NULL, owner TEXT NOT NULL, filename TEXT NOT NULL, sha TEXT NOT NULL,
                  size INTEGER NOT NULL, info TEXT NOT NULL, created REAL NOT NULL,
                  PRIMARY KEY(owner,id));
                CREATE TABLE IF NOT EXISTS jobs(
                  id TEXT PRIMARY KEY, owner TEXT NOT NULL, attachment TEXT NOT NULL, fingerprint TEXT NOT NULL,
                  config TEXT NOT NULL, status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
                  created REAL NOT NULL, updated REAL NOT NULL, expires REAL NOT NULL, cancel INTEGER DEFAULT 0);
                CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner, fingerprint);
            """)

    @contextmanager
    def db(self):
        with self.lock:
            connection = sqlite3.connect(self.root / "jobs.sqlite3", timeout=15)
            connection.row_factory = sqlite3.Row
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    def original(self, scope, identifier, filename):
        return self.root / "originals" / scope / (valid_id(identifier) + Path(filename).suffix.lower())

    def task(self, identifier):
        return self.root / "tasks" / valid_id(identifier)

    def register(self, identity, identifier, filename, incoming, info):
        scope = owner(identity)
        valid_id(identifier)
        if (not isinstance(filename, str) or not 1 <= len(filename) <= 200 or
                Path(filename).name != filename or any(c in filename for c in "\\/\r\n\0")):
            raise Fault("INVALID_FILENAME")
        incoming = Path(incoming)
        size = incoming.stat().st_size
        if not 0 < size <= self.limits.max_bytes:
            raise Fault("SIZE_LIMIT")
        with incoming.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        with self.db() as db:
            previous = db.execute("SELECT * FROM attachments WHERE owner=? AND id=?", (scope, identifier)).fetchone()
            if previous:
                if previous["sha"] != digest or previous["filename"] != filename:
                    raise Fault("ATTACHMENT_CHANGED")
                if previous["created"] + self.limits.ttl_seconds <= time.time():
                    raise Fault("EXPIRED")
                return self.inspect(identity, identifier)
            used = db.execute("SELECT COALESCE(SUM(size),0) FROM attachments WHERE owner=?", (scope,)).fetchone()[0]
            count = db.execute("SELECT COUNT(*) FROM attachments WHERE owner=? AND created>?",
                               (scope, time.time() - self.limits.ttl_seconds)).fetchone()[0]
            if used + size > self.limits.max_original_bytes_per_scope or count >= 8:
                raise Fault("ATTACHMENT_QUOTA")
            target = self.original(scope, identifier, filename)
            target.parent.mkdir(exist_ok=True, mode=0o700)
            if target.exists():
                raise Fault("ORIGINAL_CONFLICT")
            # Copy with exclusive create; this immutable snapshot does not rename/delete the inbound original.
            created_snapshot = False
            try:
                with target.open("xb") as output:
                    created_snapshot = True
                    with incoming.open("rb") as source:
                        shutil.copyfileobj(source, output, 1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
            except Exception:
                if created_snapshot:
                    target.unlink(missing_ok=True)
                raise
            os.chmod(target, 0o600)
            db.execute("INSERT INTO attachments VALUES(?,?,?,?,?,?,?)",
                       (identifier, scope, filename, digest, size, json.dumps(info), time.time()))
        return self.inspect(identity, identifier)

    def attachment(self, identity, identifier):
        scope = owner(identity)
        valid_id(identifier)
        with self.db() as db:
            row = db.execute("SELECT * FROM attachments WHERE owner=? AND id=?", (scope, identifier)).fetchone()
        if not row or row["created"] + self.limits.ttl_seconds <= time.time():
            raise Fault("NOT_FOUND")
        return dict(row)

    def inspect(self, identity, identifier=None):
        if identifier is None:
            with self.db() as db:
                rows = db.execute("SELECT id,filename,size FROM attachments WHERE owner=? AND created>? ORDER BY created",
                                  (owner(identity), time.time() - self.limits.ttl_seconds)).fetchall()
            return {"status": "AVAILABLE", "attachments": [
                {"attachment_id": r["id"], "filename": r["filename"], "bytes": r["size"]} for r in rows]}
        row = self.attachment(identity, identifier)
        return {"status": "INSPECTED", "attachment_id": identifier, "filename": row["filename"],
                "bytes": row["size"], "sha256": row["sha"], "content_trust": "untrusted", **json.loads(row["info"])}

    def submit(self, identity, identifier, raw):
        scope = owner(identity)
        attachment = self.attachment(identity, identifier)
        config = options(raw, json.loads(attachment["info"]))
        from .engines import version
        engines = {name: version(name) for name in
                   ("PyMuPDF", "python-docx", "rapidocr-onnxruntime", "faster-whisper")}
        fingerprint = hashlib.sha256(json.dumps([identifier, attachment["sha"], config,
                                                self.limits.dict(), engines, "1.0.0"], sort_keys=True).encode()).hexdigest()
        with self.db() as db:
            row = db.execute("SELECT id FROM jobs WHERE owner=? AND fingerprint=? AND expires>? AND status IN"
                             " ('QUEUED','RUNNING','SUCCEEDED','PARTIAL') ORDER BY created DESC LIMIT 1",
                             (scope, fingerprint, time.time())).fetchone()
            if row:
                return {**self.status(identity, row["id"]), "reused": True}
            count = db.execute("SELECT COUNT(*) FROM jobs WHERE owner=? AND expires>?", (scope, time.time())).fetchone()[0]
            if count >= self.limits.max_jobs_per_scope:
                raise Fault("JOB_QUOTA")
            identifier_job = uuid.uuid4().hex
            now = time.time()
            out = self.task(identifier_job)
            out.mkdir(mode=0o700)
            # Every task has an explicit empty evidence document and provenance, even
            # before an engine starts. Tool reads still require a published terminal result.
            (out / "content.md").write_text("", encoding="utf-8")
            write_json(out / "sources.json", {
                "schema_version": "1.0", "job_id": identifier_job, "attachment_id": identifier,
                "original": {"filename": attachment["filename"], "sha256": attachment["sha"],
                             "bytes": attachment["size"],
                             "message_id": json.loads(attachment["info"]).get("source_message_id")},
                "status": "QUEUED", "created_at": now, "expires_at": now + self.limits.ttl_seconds,
                "config": config, "engines": engines,
                "limits": {k: v for k, v in self.limits.dict().items() if k not in ("model_cache", "whisper_model")},
                "model": {"reference": Path(self.limits.whisper_model).name, "offline": self.limits.offline},
                "coverage": {"kind": json.loads(attachment["info"])["kind"], "mode": config["mode"],
                             "processed": [], "full_document": False},
                "segments": [], "failures": [], "warnings": ["No evidence published yet; query the job state."],
                "artifacts": [], "content_trust": "untrusted"})
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,0)",
                       (identifier_job, scope, identifier, fingerprint, json.dumps(config), "QUEUED",
                        0, now, now, now + self.limits.ttl_seconds))
        return {**self.status(identity, identifier_job), "reused": False}

    def job(self, identity, identifier):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=? AND owner=? AND (expires>? OR status IN ('QUEUED','RUNNING'))",
                             (valid_id(identifier), owner(identity), time.time())).fetchone()
        if not row:
            raise Fault("NOT_FOUND")
        return dict(row)

    def manifest(self, row):
        if row["status"] not in ("SUCCEEDED", "PARTIAL", "FAILED"):
            raise Fault("NOT_READY")
        file = self.task(row["id"]) / "sources.json"
        if not file.is_file() or file.stat().st_size > 64 * 1024 * 1024:
            raise Fault("ARTIFACT_UNAVAILABLE")
        return json.loads(file.read_text(encoding="utf-8"))

    def status(self, identity, identifier):
        row = self.job(identity, identifier)
        result = {"status": row["status"], "job_id": row["id"], "attachment_id": row["attachment"],
                  "progress": round(row["progress"], 3), "expires_at": row["expires"],
                  "cancel_requested": bool(row["cancel"])}
        if row["status"] in ("SUCCEEDED", "PARTIAL", "FAILED"):
            manifest = self.manifest(row)
            result.update(self.public_manifest(manifest))
        return result

    @staticmethod
    def public_manifest(manifest):
        coverage = dict(manifest["coverage"])
        processed = coverage.pop("processed", [])
        coverage.update(processed_count=len(processed), processed_sample=processed[:20])
        return {"coverage": coverage, "failures": manifest["failures"][:20],
                "failure_count": len(manifest["failures"]), "warnings": manifest["warnings"][:20],
                "warning_count": len(manifest["warnings"]), "artifacts": manifest["artifacts"][:64],
                "artifact_count": len(manifest["artifacts"]),
                "metadata_truncated": len(processed) > 20 or len(manifest["failures"]) > 20 or
                len(manifest["warnings"]) > 20 or len(manifest["artifacts"]) > 64}

    def cancel(self, identity, identifier):
        self.job(identity, identifier)
        with self.db() as db:
            db.execute("UPDATE jobs SET cancel=1, status=CASE WHEN status='QUEUED' THEN 'CANCELLED' ELSE status END"
                       " WHERE id=? AND status IN ('QUEUED','RUNNING')", (identifier,))
        return self.status(identity, identifier)

    def read(self, identity, identifier, raw, find=False):
        allowed = ("artifact_id", "pages", "time_range", "paragraphs", "offset", "max_chars", "keyword")
        strict(raw, allowed)
        if not find and "keyword" in raw:
            raise Fault("INVALID_PARAMETERS")
        row = self.job(identity, identifier)
        manifest = self.manifest(row)
        if not manifest["artifacts"]:
            raise Fault("NO_CONTENT")
        artifact = raw.get("artifact_id", manifest["artifacts"][0]["artifact_id"])
        valid_id(artifact)
        selected = next((a for a in manifest["artifacts"] if a["artifact_id"] == artifact), None)
        if not selected:
            raise Fault("UNREADABLE_ARTIFACT")
        maximum = integer(raw.get("max_chars", self.limits.max_read_chars), 1, self.limits.max_read_chars)
        offset = integer(raw.get("offset", 0), 0, self.limits.max_output_chars)
        if selected["kind"] not in ("content", "transcript"):
            if selected["kind"] not in ("sources", "minutes") or find or set(raw) & {"pages", "time_range", "paragraphs"}:
                raise Fault("UNREADABLE_ARTIFACT")
            file = self.task(identifier) / selected["file"]
            text = file.read_text(encoding="utf-8")
            chunk = text[offset:offset + maximum]
            return {"status": "READ", "job_id": identifier, "artifact_id": artifact,
                    "artifact_kind": selected["kind"], "text": chunk, "content_trust": "untrusted",
                    "source_segments": selected.get("source_segments", []),
                    "next_offset": offset + len(chunk) if offset + len(chunk) < len(text) else None,
                    "truncated": offset + len(chunk) < len(text)}
        filters = set(raw) & {"pages", "time_range", "paragraphs"}
        if len(filters) > 1:
            raise Fault("INVALID_RANGE")
        for field in filters:
            values = raw[field]
            if (not isinstance(values, list) or len(values) != 2 or
                    any(type(v) not in (int, float) or not 0 <= v <= 2_000_000 for v in values) or
                    values[0] > values[1]):
                raise Fault("INVALID_RANGE")
            expected = {"pdf": "pages", "image": "pages", "audio": "time_range",
                        "docx": "paragraphs", "text": "paragraphs"}[manifest["coverage"]["kind"]]
            if field != expected or (field != "time_range" and any(type(v) is not int or v < 1 for v in values)):
                raise Fault("INVALID_RANGE")
        keyword = raw.get("keyword")
        if find and (not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 200):
            raise Fault("INVALID_PARAMETERS")
        entries = []
        for segment in manifest["segments"]:
            source = segment["source"]
            if "pages" in raw and not raw["pages"][0] <= source.get("page", -1) <= raw["pages"][1]:
                continue
            if "paragraphs" in raw and not raw["paragraphs"][0] <= source.get("paragraph", -1) <= raw["paragraphs"][1]:
                continue
            if "time_range" in raw and not (source.get("end", -1) > raw["time_range"][0] and
                                            source.get("start", 2_000_001) < raw["time_range"][1]):
                continue
            entries.append(segment)
        # Pagination spans the selected text stream; evidence slices carry exact original locations.
        hits, position, consumed, remaining = [], 0, 0, maximum
        for segment in entries:
            text = segment["text"]
            if find:
                match = text.casefold().find(keyword.casefold())
                if match < 0:
                    continue
                # casefold changes Unicode lengths; context is deliberately approximate and labelled.
                text = text[max(0, match - 150):match + len(keyword) + 150]
            end = position + len(text)
            if end > offset and remaining > 0:
                start = max(0, offset - position)
                chunk = text[start:start + remaining]
                hits.append({"source": segment["source"], "segment": segment["segment"], "text": chunk,
                             "engine": segment["engine"], "incomplete": segment.get("incomplete", False)})
                consumed += len(chunk)
                remaining -= len(chunk)
            position = end
        return {"status": "MATCHES" if find and hits else "NO_MATCH" if find else "READ",
                "job_id": identifier, "artifact_id": artifact, "evidence": hits,
                "next_offset": offset + consumed if position > offset + consumed else None,
                "truncated": position > offset + consumed, "selected_chars": position,
                **self.public_manifest(manifest), "content_trust": "untrusted",
                "caution": "No keyword match is not proof of absence; only extracted selected evidence was searched."}

    def save_minutes(self, identity, identifier, text, source_segments):
        row = self.job(identity, identifier)
        manifest = self.manifest(row)
        if (row["status"] not in ("SUCCEEDED", "PARTIAL") or not isinstance(text, str) or
                not 1 <= len(text) <= self.limits.max_read_chars or not isinstance(source_segments, list) or
                not source_segments or len(source_segments) > 100 or
                any(type(i) is not int or i < 1 or i > len(manifest["segments"]) for i in source_segments)):
            raise Fault("INVALID_MINUTES")
        if sum(a["kind"] == "minutes" for a in manifest["artifacts"]) >= 32:
            raise Fault("ARTIFACT_LIMIT")
        digest = hashlib.sha256(json.dumps([text, source_segments]).encode()).hexdigest()
        previous = next((a for a in manifest["artifacts"] if a.get("derived_sha256") == digest), None)
        if previous:
            return {"status": "SAVED", "job_id": identifier, "artifact_id": previous["artifact_id"], "reused": True}
        artifact = uuid.uuid4().hex
        filename = f"minutes-{artifact}.md"
        (self.task(identifier) / filename).write_text(text, encoding="utf-8")
        manifest["artifacts"].append({"artifact_id": artifact, "file": filename, "kind": "minutes",
            "derived_sha256": digest, "source_segments": source_segments, "content_trust": "untrusted",
            "author": "agent-derived-unverified"})
        write_json(self.task(identifier) / "sources.json", manifest)
        return {"status": "SAVED", "job_id": identifier, "artifact_id": artifact, "reused": False}

    def cleanup(self, now=None):
        now = time.time() if now is None else now
        removed = []
        # Readers, scheduler and cleanup share the lock. Active/queued jobs are never removed.
        with self.db() as db:
            if (self.root / "tasks").is_symlink():
                raise Fault("UNSAFE_CLEANUP_TARGET")
            rows = db.execute("SELECT id FROM jobs WHERE expires<=? AND status NOT IN ('RUNNING','QUEUED')",
                              (now,)).fetchall()
            for row in rows:
                target = self.task(row["id"])
                if target.is_symlink() or target.resolve().parent != (self.root / "tasks").resolve():
                    raise Fault("UNSAFE_CLEANUP_TARGET")
                if target.exists():
                    shutil.rmtree(target)
                db.execute("DELETE FROM jobs WHERE id=?", (row["id"],))
                removed.append(row["id"])
        return {"status": "CLEANED", "removed_jobs": removed, "originals_deleted": 0}
