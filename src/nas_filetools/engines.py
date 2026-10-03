"""Engine adapters. Extracted text is evidence, never an instruction or layout guarantee."""

import hashlib
import importlib.metadata
import json
import subprocess
import zipfile
from pathlib import Path

from .contracts import FORMATS, Fault


def version(package):
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def check_docx(path, limits):
    with zipfile.ZipFile(path) as archive:
        items = archive.infolist()
        if len(items) > 10000 or sum(i.file_size for i in items) > limits.max_docx_expanded_bytes:
            raise Fault("EXPANDED_SIZE_LIMIT")
        if len({i.filename for i in items}) != len(items):
            raise Fault("INVALID_DOCX")
        for item in items:
            if item.flag_bits & 1 or ".." in Path(item.filename).parts or item.filename.startswith("/"):
                raise Fault("INVALID_DOCX")
        if "word/document.xml" not in archive.namelist():
            raise Fault("INVALID_DOCX")


def text_blocks(path, limits):
    value = Path(path).read_text(encoding="utf-8-sig", errors="strict")
    if "\0" in value:
        raise Fault("INVALID_TEXT")
    if len(value) > limits.max_output_chars:
        raise Fault("OUTPUT_LIMIT")
    # Paragraph identifiers are stable across inspect/extract/read.
    return [p for p in value.replace("\r\n", "\n").split("\n\n") if p.strip()]


def probe(path, limits):
    path = Path(path)
    kind = FORMATS.get(path.suffix.lower())
    if kind is None:
        raise Fault("UNSUPPORTED_TYPE")
    info = {"kind": kind, "units": 0, "warnings": [], "preview": [], "preview_coverage": []}
    if kind == "pdf":
        import fitz
        with fitz.open(path) as doc:
            if not doc.is_pdf or doc.needs_pass:
                raise Fault("INVALID_OR_ENCRYPTED_PDF")
            info["units"] = len(doc)
            if len(doc) > limits.max_pages:
                raise Fault("PAGE_LIMIT")
            for i in range(min(limits.preview_pages, len(doc))):
                page = doc[i]
                raw = page.get_text(sort=True).strip()
                info["preview"].append({"page": i + 1, "text": raw[:1000],
                                        "requires_ocr": len(raw) < 30 or bool(page.get_images())})
                info["preview_coverage"].append(i + 1)
            info["warnings"].append("Preview is bounded; text presence does not prove complete extraction.")
    elif kind == "docx":
        check_docx(path, limits)
        from docx import Document
        doc = Document(path)
        from docx.oxml.ns import qn
        blocks = [e for e in doc.element.body if e.tag in (qn("w:p"), qn("w:tbl"))]
        info["units"] = len(blocks)
        for number, element in enumerate(blocks[:limits.preview_pages], 1):
            value = " ".join(n.text or "" for n in element.iter(qn("w:t")))
            info["preview"].append({"paragraph": number, "text": value[:1000],
                                    "kind": "table" if element.tag == qn("w:tbl") else "paragraph"})
            info["preview_coverage"].append(number)
        info["warnings"].append("Body blocks only; headers, footers, text boxes and layout are not reconstructed.")
    elif kind == "text":
        blocks = text_blocks(path, limits)
        info["units"] = len(blocks)
        info["preview"] = [p[:1000] for p in blocks[:3]]
        info["preview_coverage"] = list(range(1, min(3, len(blocks)) + 1))
    elif kind == "image":
        from PIL import Image
        with Image.open(path) as image:
            if image.width * image.height > limits.max_image_pixels:
                raise Fault("PIXEL_LIMIT")
            info.update(units=getattr(image, "n_frames", 1), width=image.width, height=image.height)
            if info["units"] > limits.max_pages:
                raise Fault("PAGE_LIMIT")
        info["warnings"].append("Printed text OCR only; no scene understanding, handwriting or formula guarantee.")
    else:
        try:
            result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "json", str(path)], capture_output=True, timeout=10, check=True)
            duration = float(json.loads(result.stdout)["format"]["duration"])
        except FileNotFoundError:
            raise Fault("FFPROBE_UNAVAILABLE") from None
        except (subprocess.SubprocessError, ValueError, KeyError):
            raise Fault("INVALID_AUDIO") from None
        if not 0 < duration <= limits.max_audio_seconds:
            raise Fault("DURATION_LIMIT")
        info.update(duration=duration, units=1)
        info["warnings"].append("Transcript is not a verified record; no speaker identification.")
    info["requires_explicit_scope"] = (info["units"] > limits.large_pages or
                                       info.get("duration", 0) > limits.large_audio_seconds)
    return info


def selection(info, config, limits):
    if info["kind"] == "audio":
        return config.get("time_range", [0, min(info["duration"], 60)
                                         if config["mode"] == "preview" else info["duration"]])
    return config.get("pages", config.get("paragraphs", [1, min(info["units"], limits.preview_pages)
                                                          if config["mode"] == "preview" else info["units"]]))


class Processor:
    def __init__(self, limits, ocr=None, transcriber=None):
        self.limits = limits
        self._ocr = ocr
        self._transcriber = transcriber

    def ocr(self, image):
        if self._ocr is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError:
                raise Fault("OCR_UNAVAILABLE") from None
            # Models are bundled in the pinned wheel. Threads are bounded for a NAS.
            self._ocr = RapidOCR(intra_op_num_threads=self.limits.engine_threads, inter_op_num_threads=1)
        result, _ = self._ocr(image)
        if not result:
            return "", []
        return "\n".join(line[1] for line in result), [
            {"box": [[float(v) for v in p] for p in line[0]], "confidence": float(line[2])}
            for line in result]

    def process(self, path, info, config, out, progress=lambda *_: None):
        out = Path(out)
        (out / "assets").mkdir(exist_ok=True)
        segments, failures, warnings, assets = [], [], list(info["warnings"]), []
        wanted = selection(info, config, self.limits)
        kind = info["kind"]
        total_chars, asset_bytes = 0, 0

        def asset(data, extension, source):
            nonlocal asset_bytes
            if asset_bytes + len(data) > self.limits.max_asset_bytes:
                raise Fault("ASSET_LIMIT")
            identifier = hashlib.sha256(data).hexdigest()[:32]
            filename = f"assets/{identifier}.{extension}"
            (out / filename).write_bytes(data)
            asset_bytes += len(data)
            assets.append({"artifact_id": identifier, "file": filename, "source": source,
                           "bytes": len(data), "kind": "image"})
            return f"![preserved image](artifact:{identifier})"

        def add(text, source, engine, extra=None):
            nonlocal total_chars
            if not text.strip():
                raise Fault("NO_CONTENT")
            if total_chars + len(text) > self.limits.max_output_chars or len(segments) >= self.limits.max_segments:
                raise Fault("OUTPUT_LIMIT")
            total_chars += len(text)
            segments.append({"segment": len(segments) + 1, "text": text, "source": source,
                             "engine": engine, **(extra or {})})

        def failed(source, error):
            failures.append({"source": source, "code": error.code if isinstance(error, Fault)
                             else "ENGINE_ERROR", "error_type": type(error).__name__})

        if kind == "pdf":
            import fitz
            with fitz.open(path) as doc:
                for number in range(wanted[0], wanted[1] + 1):
                    source = {"page": number}
                    raw = ""
                    try:
                        page = doc[number - 1]
                        raw = page.get_text(sort=True).strip()
                        use_ocr = config["ocr"] == "always" or len(raw) < 30 or bool(page.get_images())
                        if use_ocr:
                            import numpy as np
                            width, height = page.rect.width * 200 / 72, page.rect.height * 200 / 72
                            if width * height > self.limits.max_image_pixels:
                                raise Fault("PIXEL_LIMIT")
                            pix = page.get_pixmap(dpi=200, colorspace=fitz.csRGB, alpha=False)
                            pixels = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                            text, boxes = self.ocr(pixels)
                            add(text, source, "rapidocr", {"ocr_boxes": boxes})
                            try:
                                asset(pix.tobytes("png"), "png", source)
                            except Fault:
                                warnings.append(f"Page {number} preview image omitted: asset limit.")
                        else:
                            add(raw, source, "pymupdf")
                    except Exception as error:
                        failed(source, error)
                        # Recover known digital text, but never count the failed page as fully processed.
                        if raw and not any(s["source"] == source for s in segments):
                            try:
                                add(raw, source, "pymupdf-fallback", {"incomplete": True})
                            except Fault:
                                pass
                    progress(number - wanted[0] + 1, wanted[1] - wanted[0] + 1)
            warnings.append("PDF reading order is geometric/engine order; columns, formulas and complex tables need review.")
        elif kind == "docx":
            from docx import Document
            from docx.oxml.ns import qn
            from docx.table import Table
            doc = Document(path)
            warnings.append("Embedded images are preserved, not OCRed; image-only content requires a separate OCR task.")
            blocks = [e for e in doc.element.body if e.tag in (qn("w:p"), qn("w:tbl"))]
            for number in range(wanted[0], wanted[1] + 1):
                source = {"paragraph": number}
                try:
                    element = blocks[number - 1]
                    lines = []
                    # XML traversal keeps body/table placement and inline picture order.
                    def paragraph_text(element):
                        parts = []
                        for node in element.iter():
                            if node.tag == qn("w:t"):
                                parts.append(node.text or "")
                            elif node.tag in (qn("w:br"), qn("w:tab")):
                                parts.append("\n" if node.tag == qn("w:br") else "\t")
                            elif node.tag == qn("a:blip"):
                                relation = node.get(qn("r:embed"))
                                if relation:
                                    part = doc.part.related_parts[relation]
                                    extension = part.partname.ext.lower()
                                    if extension not in ("png", "jpg", "jpeg", "gif", "bmp", "tiff", "svg", "emf", "wmf"):
                                        raise Fault("UNSUPPORTED_EMBEDDED_IMAGE")
                                    parts.append(asset(part.blob, extension, source))
                                else:
                                    warnings.append(f"Block {number}: external image was not fetched.")
                        return "".join(parts)
                    if element.tag == qn("w:p"):
                        lines.append(paragraph_text(element))
                    else:
                        table = Table(element, doc)
                        for row in table.rows:
                            lines.append("| " + " | ".join(paragraph_text(c._tc).replace("|", "\\|")
                                                           .replace("\n", "<br>") for c in row.cells) + " |")
                        warnings.append(f"Block {number}: table cells retained; merged/nested geometry may be approximate.")
                    text = "\n".join(lines)
                    if text.strip() and any(n.tag == qn("w:t") and (n.text or "").strip() for n in element.iter()):
                        add(text, source, "python-docx")
                    elif "artifact:" in text:
                        add(text, source, "python-docx", {"incomplete": True, "image_only": True})
                        raise Fault("IMAGE_TEXT_NOT_EXTRACTED")
                    # Empty body paragraphs are legitimate empty units, not recognition failures.
                except Exception as error:
                    failed(source, error)
                progress(number - wanted[0] + 1, wanted[1] - wanted[0] + 1)
        elif kind == "text":
            blocks = text_blocks(path, self.limits)
            for number in range(wanted[0], wanted[1] + 1):
                try:
                    add(blocks[number - 1], {"paragraph": number}, "utf-8")
                except Fault as error:
                    failed({"paragraph": number}, error)
                progress(number - wanted[0] + 1, wanted[1] - wanted[0] + 1)
        elif kind == "image":
            import numpy as np
            from PIL import Image
            with Image.open(path) as image:
                for number in range(wanted[0], wanted[1] + 1):
                    source = {"page": number}
                    try:
                        image.seek(number - 1)
                        if image.width * image.height > self.limits.max_image_pixels:
                            raise Fault("PIXEL_LIMIT")
                        text, boxes = self.ocr(np.array(image.convert("RGB")))
                        add(text, source, "rapidocr", {"ocr_boxes": boxes})
                    except Exception as error:
                        failed(source, error)
                    progress(number - wanted[0] + 1, wanted[1] - wanted[0] + 1)
        else:
            try:
                if self._transcriber is None:
                    try:
                        from faster_whisper import WhisperModel
                    except ImportError:
                        raise Fault("ASR_UNAVAILABLE") from None
                    try:
                        self._transcriber = WhisperModel(self.limits.whisper_model, device="cpu", compute_type="int8",
                                                         cpu_threads=self.limits.engine_threads, num_workers=1,
                                                         download_root=self.limits.model_cache,
                                                         local_files_only=self.limits.offline)
                    except Exception:
                        raise Fault("MODEL_UNAVAILABLE") from None
                # Decode only the selected audio interval; the process supervisor bounds decoding/model work.
                import av
                import numpy as np
                result = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(wanted[0]), "-t",
                                         str(wanted[1] - wanted[0]), "-threads", str(self.limits.engine_threads),
                                         "-i", str(path), "-threads", str(self.limits.engine_threads), "-ac", "1", "-ar",
                                         "16000", "-f", "wav", str(out / "selected.wav")],
                                        capture_output=True, timeout=self.limits.timeout_seconds, check=True)
                del result
                audio = []
                with av.open(str(out / "selected.wav")) as container:
                    for frame in container.decode(audio=0):
                        audio.append(frame.to_ndarray().flatten())
                samples = np.concatenate(audio).astype(np.float32) / 32768.0
                values, _ = self._transcriber.transcribe(samples, language=config.get("language"),
                                                        beam_size=5, vad_filter=True)
                for s in values:
                    source = {"start": round(wanted[0] + s.start, 3), "end": round(wanted[0] + s.end, 3)}
                    add(s.text.strip(), source, "faster-whisper")
                    progress(min(s.end, wanted[1] - wanted[0]), wanted[1] - wanted[0])
                (out / "selected.wav").unlink(missing_ok=True)
            except Exception as error:
                failed({"start": wanted[0], "end": wanted[1]}, error)
        if not segments and not failures:
            failures.append({"source": {}, "code": "NO_CONTENT"})
        status = "FAILED" if not segments or all(s.get("image_only") for s in segments) else "PARTIAL" if failures else "SUCCEEDED"
        return {"status": status, "segments": segments, "failures": failures, "warnings": warnings,
                "assets": assets, "coverage": {"kind": kind, "requested": wanted,
                 "mode": config["mode"], "total_units": info["units"],
                 "total_duration": info.get("duration"), "processed": [s["source"] for s in segments],
                 "full_document": config["mode"] == "full" and not failures},
                "engines": {name: version(name) for name in
                            ("PyMuPDF", "python-docx", "rapidocr-onnxruntime", "faster-whisper")},
                "config": config}
