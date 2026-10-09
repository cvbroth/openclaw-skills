"""Portable project packages exclude renderer state, locks and running temp files."""

from pathlib import PurePosixPath


def exportable(path):
    p = PurePosixPath(str(path))
    if any(x in {"lo-profile", "tmp", "temp", "__pycache__"} or x.startswith(".") for x in p.parts):
        return False
    return not (p.name.endswith((".lock", ".tmp", ".next", ".pyc")) or p.name.startswith("~$"))


def windows_safe(path):
    p = PurePosixPath(str(path))
    forbidden = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *[f"COM{i}" for i in range(1, 10)],
        *[f"LPT{i}" for i in range(1, 10)],
    }
    return (
        not p.is_absolute()
        and ".." not in p.parts
        and all(
            not any(c in x for c in '<>:"\\|?*')
            and not x.endswith((" ", "."))
            and x.split(".")[0].upper() not in forbidden
            for x in p.parts
        )
    )


def portable_manifest(project):
    """Download aliases only in the ZIP; original registered paths/IDs are unchanged."""
    import copy
    from pathlib import PurePosixPath

    portable = copy.deepcopy(project)
    aliases, seen = [], set()
    for artifact in portable["artifacts"]:
        if not artifact.get("path") or artifact["format"] not in {"markdown", "docx", "pdf", "image"}:
            continue
        name = artifact["download_name"]
        if name.casefold() in seen:
            p = PurePosixPath(name)
            name = p.stem + "-" + artifact["artifact_id"][:8] + p.suffix
        seen.add(name.casefold())
        target = "downloads/" + name
        if not windows_safe(target):
            raise ValueError("download alias not Windows portable")
        artifact["download_path"] = target
        aliases.append((artifact["path"], target))
    return portable, aliases
