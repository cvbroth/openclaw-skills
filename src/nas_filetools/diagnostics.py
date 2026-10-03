"""Operator runtime checks in the worker's environment, never expose credentials."""
import json
import multiprocessing
import os
import sys
import uuid
from pathlib import Path

from .catalog import atomic_json
from .contracts import Fault, Limits
from .worker import isolate_child, resource_limits, terminate


def check_child(folder, settings, parent):
    isolate_child(parent)
    resource_limits(settings)
    result = {"platform": sys.platform, "python": sys.version.split()[0], "checks": {}, "issues": []}
    from .engines import Processor, version
    limits = Limits(**settings)
    result["dependencies"] = {p: version(p) for p in ("PyMuPDF", "python-docx", "openpyxl", "rapidocr-onnxruntime", "faster-whisper")}
    for name in ("ocr", "asr_model_load", "temporary_python"):
        try:
            if name == "ocr":
                import numpy as np
                from PIL import Image, ImageDraw, ImageFont
                image = Image.new("RGB", (720, 140), "white")
                ImageDraw.Draw(image).text((20, 35), "FILETOOLS TEST 123", font=ImageFont.load_default(size=40), fill="black")
                text, _ = Processor(limits).ocr(np.array(image))
                if "123" not in text:
                    raise Fault("OCR_SELF_CHECK_FAILED")
                result["checks"][name] = "PRINTED_SYNTHETIC_SAMPLE_PASSED"
            elif name == "asr_model_load":
                from faster_whisper import WhisperModel
                model = WhisperModel(limits.whisper_model, device="cpu", compute_type="int8", cpu_threads=limits.engine_threads,
                    num_workers=1, download_root=limits.model_cache, local_files_only=limits.offline)
                del model
                result["checks"][name] = "OFFLINE_MODEL_LOAD_PASSED_NOT_SPEECH_ACCURACY"
            else:
                import subprocess
                script = Path(folder)/"operation.py"
                script.write_text("from pathlib import Path\nimport socket\ntry:\n socket.socket()\nexcept PermissionError:\n pass\nelse:\n raise AssertionError('network available')\nPath('result.txt').write_text('ok')\n")
                launcher = Path(__file__).with_name("script_launcher.py")
                child = subprocess.run([sys.executable, "-I", str(launcher), str(folder), limits.script_isolation,
                    str(limits.worker_memory_mb*1024**2), "15", "1048576"], capture_output=True, timeout=20)
                if child.returncode or not (Path(folder)/"result.txt").exists():
                    raise Fault("SCRIPT_ISOLATION_SELF_CHECK_FAILED")
                result["checks"][name] = "ISOLATED_WRITE_AND_NETWORK_DENIAL_PASSED"
        except Exception as error:
            result["checks"][name] = "FAILED"
            result["issues"].append(error.code if isinstance(error, Fault) else name.upper()+"_UNAVAILABLE")
    atomic_json(Path(folder)/"diagnostics.json", result)


def runtime_check(store):
    with store.db() as db:
        if db.execute("SELECT 1 FROM jobs WHERE status IN ('RUNNING','QUEUED')").fetchone():
            return {"status": "DIAGNOSTICS_DEFERRED", "code": "SERVICE_NOT_IDLE"}
    folder = store.root/"incoming"/("diagnostic-"+uuid.uuid4().hex)
    folder.mkdir(mode=0o700)
    process = multiprocessing.get_context("spawn").Process(target=check_child,
        args=(str(folder), store.limits.dict(), os.getpid()), daemon=True)
    try:
        process.start()
        process.join(60)
        output = folder/"diagnostics.json"
        if process.is_alive() or not output.exists():
            raise Fault("DIAGNOSTICS_FAILED_OR_TIMEOUT")
        return {"status": "RUNTIME_DIAGNOSTICS", **json.loads(output.read_text(encoding="utf-8"))}
    finally:
        terminate(process)
        import shutil
        shutil.rmtree(folder)
