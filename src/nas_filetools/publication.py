"""Trusted verified publication outside the execution directory, on the same filesystem."""
import json
import os
import shutil
import uuid
from pathlib import Path

from .catalog import digest_file, sync_directory
from .contracts import Fault


def publish(private, task, artifacts):
    temporary = Path(task)/(".publishing-"+uuid.uuid4().hex)
    temporary.mkdir(mode=0o700)
    updated = json.loads(json.dumps(artifacts))
    try:
        for artifact in updated:
            if artifact["kind"] == "sources":
                continue
            source = Path(private)/artifact["file"]
            if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(Path(private).resolve()):
                raise Fault("UNSAFE_ARTIFACT")
            before = digest_file(source)
            target = temporary/artifact["file"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if artifact["kind"] in ("content", "transcript", "minutes"):
                text = source.read_text(encoding="utf-8")
                for image in artifacts:
                    if image["kind"] == "image":
                        text = text.replace("artifact:"+image["artifact_id"],
                            Path(os.path.relpath(image["file"], Path(artifact["file"]).parent)).as_posix())
                target.write_text(text, encoding="utf-8")
            else:
                shutil.copyfile(source, target)
            if (artifact["kind"] not in ("content", "transcript", "minutes") and digest_file(target) != before) or digest_file(source) != before:
                raise Fault("OUTPUT_CHANGED_DURING_PUBLICATION")
            with target.open("r+b") as file:
                os.fsync(file.fileno())
            os.chmod(target, 0o440)
            artifact.update(file="published/"+artifact["file"], sha256=digest_file(target), bytes=target.stat().st_size)
        destination = Path(task)/"published"
        if destination.exists():
            # Resume replaces a former result only after the new bundle has fully verified.
            retained = Path(task)/(".superseded-"+uuid.uuid4().hex)
            os.replace(destination, retained)
        os.replace(temporary, destination)
        sync_directory(destination.parent)
        return updated
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
