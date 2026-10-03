"""SQLite metadata and guarded per-task artifacts; originals live outside cleanup targets."""

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .contracts import Fault, integer, strict, valid_id

TERMINAL = ("SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED", "TIMED_OUT", "INTERRUPTED")


def write_json(path, value):
    temp = Path(str(path) + ".tmp")
    with temp.open("w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)


class EvidenceStore:
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

    def manifest(self, row):
        if row["status"] not in ("SUCCEEDED", "PARTIAL", "FAILED"):
            raise Fault("NOT_READY")
        file = self.task(row["id"]) / "sources.json"
        if not file.is_file() or file.stat().st_size > self.limits.max_manifest_bytes:
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
            if selected["kind"] not in ("sources", "minutes", "script", "log") or find or set(raw) & {"pages", "time_range", "paragraphs"}:
                raise Fault("UNREADABLE_ARTIFACT")
            file = self.task(identifier) / selected["file"]
            text = file.read_text(encoding="utf-8", errors="replace" if selected["kind"] == "log" else "strict")
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



from .workspace import WorkspaceStore  # noqa: E402


class Store(WorkspaceStore, EvidenceStore):
    """V1 readers reused behind V1.1 persistent Agent snapshots and session references."""
