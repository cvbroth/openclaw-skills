"""Bounded type identification and streaming I/O; classification is not parse support."""
import hashlib
import codecs
import json
import os
import time
import zipfile
import struct
import uuid
import stat
from datetime import datetime, timezone
from pathlib import Path

from .contracts import Fault

CATEGORIES = ("pdf", "word", "markdown", "text", "images", "audio", "tables", "datasets", "structured", "other")
EXTENSIONS = {
    ".pdf": ("pdf", "pdf"), ".docx": ("word", "docx"), ".doc": ("word", "doc"),
    ".md": ("markdown", "markdown"), ".txt": ("text", "text"),
    **{e: ("images", e[1:]) for e in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif")},
    **{e: ("audio", e[1:]) for e in (".mp3", ".m4a", ".wav", ".flac", ".ogg")},
    **{e: ("tables", e[1:]) for e in (".xlsx", ".xls", ".csv", ".tsv", ".ods")},
    **{e: ("datasets", e[1:]) for e in (".jsonl", ".parquet", ".arrow", ".feather")},
    **{e: ("structured", e[1:]) for e in (".json", ".yaml", ".yml", ".xml")},
    **{e: ("video", e[1:]) for e in (".mp4", ".mov", ".mkv", ".webm")},
    **{e: ("archives", e[1:]) for e in (".zip", ".tar", ".gz", ".7z")},
}


def timestamp(value=None):
    return datetime.fromtimestamp(time.time() if value is None else value, timezone.utc).isoformat()


def atomic_json(path, value):
    target = Path(path)
    if target.is_symlink():
        raise Fault("UNSAFE_JSON_TARGET")
    previous = target.stat() if target.exists() else None
    mode = stat.S_IMODE(previous.st_mode) if previous else 0o600
    temporary = target.with_name(target.name + ".tmp-"+uuid.uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        if os.name == "posix" and previous:
            os.chown(temporary, previous.st_uid, previous.st_gid)
        os.replace(temporary, target)
        sync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


def digest_file(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def copy_stream(source, destination, maximum, expected_size=None, expected_sha=None):
    digest, count = hashlib.sha256(), 0
    with Path(destination).open("xb") as output:
        while chunk := source.read(1024 * 1024):
            count = advance_bytes(count, len(chunk), maximum)
            digest.update(chunk)
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    sha = digest.hexdigest()
    if count == 0 or (expected_size is not None and count != expected_size) or (expected_sha and sha != expected_sha):
        raise Fault("ATTACHMENT_CHANGED")
    return count, sha


def advance_bytes(current, additional, maximum):
    """Shared 64-bit ingress counter; also tested at 4 GiB without claiming a full transfer."""
    total = current+additional
    if total > maximum or total > 2**63-1:
        raise Fault("RECEIVE_SIZE_LIMIT")
    return total


def sync_directory(path):
    if os.name == "posix":
        fd = os.open(path, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def identify(path, filename):
    with Path(path).open("rb") as source:
        header = source.read(65536)
    declared = Path(filename).suffix.lower()
    extension, confidence = declared, "signature"
    if header.lstrip().startswith(b"%PDF-"):
        extension = ".pdf"
    elif header.startswith(b"\x89PNG\r\n\x1a\n"):
        extension = ".png"
    elif header.startswith(b"\xff\xd8\xff"):
        extension = ".jpg"
    elif header[:4] in (b"II*\x00", b"MM\x00*"):
        extension = ".tiff"
    elif header.startswith(b"BM"):
        extension = ".bmp"
    elif header.startswith(b"GIF8"):
        extension = ".gif"
    elif header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        extension = ".webp"
    elif header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        extension = ".wav"
    elif header.startswith(b"fLaC"):
        extension = ".flac"
    elif header.startswith(b"OggS"):
        extension = ".ogg"
    elif header.startswith(b"ID3") or (len(header) > 2 and header[0] == 255 and header[1] & 224 == 224):
        extension = ".mp3"
    elif header[4:8] == b"ftyp" and header[8:12] in (b"M4A ", b"M4B "):
        extension = ".m4a"
    elif header[4:8] == b"ftyp":
        extension = ".mov" if header[8:12] == b"qt  " else ".mp4"
    elif header.startswith(b"\x1aE\xdf\xa3"):
        extension = ".webm" if declared == ".webm" else ".mkv"
    elif header.startswith(b"\x1f\x8b"):
        extension = ".gz"
    elif header.startswith(b"7z\xbc\xaf\x27\x1c"):
        extension = ".7z"
    elif header[257:262] == b"ustar":
        extension = ".tar"
    elif header.startswith(b"PAR1"):
        extension = ".parquet"
    elif header.startswith(b"ARROW1"):
        extension = ".arrow"
    elif header.startswith(b"FEA1"):
        extension = ".feather"
    elif header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        extension = declared if declared in (".doc", ".xls") else ""
        confidence = "ole-container-declared-subtype"
    elif header.startswith(b"PK\x03\x04"):
        # Inspect only bounded central directory metadata; never decompress arbitrary payloads here.
        try:
            with Path(path).open("rb") as handle:
                handle.seek(max(0, Path(path).stat().st_size-65557))
                tail = handle.read(65557)
            end = tail.rfind(b"PK\x05\x06")
            if end < 0 or len(tail)-end < 22:
                raise Fault("INVALID_CONTAINER")
            _, _, _, _, entries, central_size, _, _ = struct.unpack("<4s4H2IH", tail[end:end+22])
            if entries >= 10000 or central_size > 4*1024**2:
                raise Fault("CONTAINER_METADATA_LIMIT")
            with zipfile.ZipFile(path) as archive:
                if len(archive.filelist) > 10000:
                    raise Fault("EXPANDED_SIZE_LIMIT")
                names = set(archive.namelist())
                extension = ".docx" if "word/document.xml" in names else ".xlsx" if "xl/workbook.xml" in names else ".zip"
                if extension == ".zip" and "mimetype" in names and archive.getinfo("mimetype").file_size < 100:
                    if archive.read("mimetype") == b"application/vnd.oasis.opendocument.spreadsheet":
                        extension = ".ods"
        except (zipfile.BadZipFile, Fault):
            extension, confidence = "", "unknown-container"
    else:
        try:
            text = codecs.getincrementaldecoder("utf-8-sig")().decode(header, final=False)
            if "\0" in text:
                raise UnicodeError()
            confidence = "bounded-text-heuristic"
            if declared in (".md", ".txt", ".csv", ".tsv", ".jsonl", ".yaml", ".yml"):
                extension = declared
            elif text.lstrip().startswith(("{", "[")):
                extension = ".json"
            elif text.lstrip().startswith("<?xml"):
                extension = ".xml"
            else:
                extension = ".txt"
        except UnicodeError:
            extension, confidence = "", "unknown-binary"
    category, actual = EXTENSIONS.get(extension, ("other", "unknown"))
    if confidence == "ole-container-declared-subtype":
        actual = "ole-compound-unverified-subtype"
    aliases = ({".jpg", ".jpeg"}, {".tif", ".tiff"}, {".yaml", ".yml"})
    mismatch = declared != extension and not any({declared, extension} <= group for group in aliases)
    kind = {"pdf": "pdf", "word": "docx" if extension == ".docx" else "unsupported",
            "markdown": "text", "text": "text", "images": "image", "audio": "audio"}.get(category, "unsupported")
    if extension == ".gif":
        kind = "unsupported"
    return {"category": category, "actual_type": actual, "extension": extension or declared,
            "type_confidence": confidence, "extension_mismatch": mismatch, "kind": kind,
            "warnings": ["Extension differs from bounded type identification."] if mismatch else []}
