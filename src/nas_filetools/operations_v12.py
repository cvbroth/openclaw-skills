"""Additive shared-workspace deployment. Plan first; only --apply changes a runtime."""
import copy
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path, PurePosixPath

from .catalog import atomic_json, digest_file, timestamp
from .contracts import AGENT_USERS, Fault, Limits, strict
from .operations import command, gateway, own_tree, REPOSITORY, TOOLS
from .shared_workspace import mapped_store

LAYOUT = "shared-v1.2"
VERSION = "1.2.1"


def configuration(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    strict(raw, ("workspace_layout", "data_root", "agents", "bindings", "limits", "gateway_container",
                 "gateway_config", "compose_service", "workspaces", "management_python"),
           ("workspace_layout", "data_root", "agents", "bindings"))
    if raw["workspace_layout"] != LAYOUT or not Path(raw["data_root"]).is_absolute():
        raise Fault("INVALID_SHARED_INSTALL_CONFIG")
    # Reuse the established trusted identity/binding validation, not a second user system.
    reduced = {k: v for k, v in raw.items() if k not in ("workspace_layout", "workspaces", "management_python")}
    temporary = dict(reduced)
    limits = Limits(**{**temporary.get("limits", {}), "enabled_agents": temporary["agents"]})
    seen = set()
    for binding in raw["bindings"]:
        strict(binding, ("agent_id", "sender_id", "channel_id", "account_id", "user_id"),
               ("agent_id", "sender_id", "channel_id", "account_id"))
        key = tuple(binding[k] for k in ("agent_id", "channel_id", "account_id", "sender_id"))
        if binding["agent_id"] not in limits.enabled_agents or key in seen or any(not isinstance(k, str) or not k for k in key):
            raise Fault("INVALID_BINDINGS")
        if binding.get("user_id", AGENT_USERS.get(binding["agent_id"], binding["agent_id"])) != AGENT_USERS.get(binding["agent_id"], binding["agent_id"]):
            raise Fault("INVALID_BINDINGS")
        seen.add(key)
    return raw, limits


def host_path(path, mounts, require_writable=True):
    path = PurePosixPath(path)
    if not path.is_absolute() or ".." in path.parts:
        raise Fault("INVALID_MAPPED_PATH")
    candidates = [m for m in mounts if m["Type"] == "bind" and path.is_relative_to(PurePosixPath(m["Destination"]))]
    if not candidates:
        raise Fault("PERSISTENT_WORKSPACE_BIND_REQUIRED")
    mount = max(candidates, key=lambda m: len(PurePosixPath(m["Destination"]).parts))
    if require_writable and not mount["RW"]:
        raise Fault("WORKSPACE_BIND_READONLY")
    return str(PurePosixPath(mount["Source"])/PurePosixPath(path).relative_to(PurePosixPath(mount["Destination"])))


def profiles(raw, target=None, document=None):
    mapped = copy.deepcopy(raw.get("workspaces", {}))
    agents = (document or {}).get("agents", {})
    entries = [{**entry, "id": key} for key, entry in agents.get("entries", {}).items()] if agents.get("entries") else agents.get("list", [])
    discovered = None
    for agent in raw["agents"]:
        profile = mapped.setdefault(agent, {})
        if not profile.get("workspace"):
            entry = next((a for a in entries if a.get("id") == agent), {})
            configured = entry.get("workspace") or ((document or {}).get("agents", {}).get("defaults", {}).get("workspace") if agent == "main" else None)
            if not configured and target:
                if discovered is None:
                    discovered = json.loads(command(["docker", "exec", target["container"], "openclaw", "agents", "list", "--json"], 60))
                    if not isinstance(discovered, list):
                        raise Fault("INVALID_AGENT_WORKSPACE_DISCOVERY")
                configured = next((a.get("workspace") for a in discovered if a.get("id") == agent), None)
            if not configured:
                raise Fault("AGENT_WORKSPACE_DISCOVERY_REQUIRED", "Set this Agent's explicit workspace; do not infer a fake service workspace.")
            profile["workspace"] = configured
        path_type = PurePosixPath if target else Path
        if not path_type(profile["workspace"]).is_absolute():
            raise Fault("ABSOLUTE_WORKSPACE_MAPPING_REQUIRED")
        if target:
            profile["host_workspace"] = host_path(profile["workspace"], target["mounts"])
        elif not profile.get("host_workspace"):
            profile["host_workspace"] = profile["workspace"]
        profile["service_root"] = f"/workspaces/{agent}/filetools" if target else str(Path(profile["host_workspace"])/"filetools")
        roots = profile.setdefault("source_roots", {})
        processing = {}
        for root_id, source in roots.items():
            strict(source, ("path", "host_path", "kind"), ("path", "kind"))
            if source["kind"] not in ("nas", "media") or not path_type(source["path"]).is_absolute() or root_id == "workspace":
                raise Fault("INVALID_SOURCE_ROOT")
            if not __import__("re").fullmatch(r"[a-z][a-z0-9_-]{0,63}", root_id):
                raise Fault("INVALID_SOURCE_ROOT")
            if source["kind"] == "nas" and (str(path_type(source["path"])) == path_type(source["path"]).anchor or
                    any(part in (".openclaw", ".ssh") for part in path_type(source["path"]).parts) or
                    path_type(profile["workspace"]).is_relative_to(path_type(source["path"]))):
                raise Fault("BROAD_REFERENCE_MOUNT_DENIED")
            if target and not source.get("host_path"):
                source["host_path"] = host_path(source["path"], target["mounts"], require_writable=False)
            if source["kind"] == "nas":
                processing[root_id] = {"path": f"/references/{agent}/{root_id}" if target else source["path"], "kind": "nas"}
        profile["processing_roots"] = processing
    if set(mapped) != set(raw["agents"]):
        raise Fault("ENABLED_AGENT_MAPPING_MISMATCH")
    for key in ("workspace", "host_workspace"):
        paths = [Path(p[key]).resolve() for p in mapped.values()]
        if len(set(paths)) != len(paths) or any(a != b and a.is_relative_to(b) for a in paths for b in paths):
            raise Fault("AGENT_WORKSPACE_OVERLAP")
    return mapped


def plugin_configuration(document, raw, mapped, plugin_path):
    updated = copy.deepcopy(document)
    plugins = updated.setdefault("plugins", {})
    allowed = plugins.get("allow")
    if allowed and "nas-filetools" not in allowed:
        allowed.append("nas-filetools")
    paths = plugins.setdefault("load", {}).setdefault("paths", [])
    if plugin_path not in paths:
        paths.append(plugin_path)
    plugin_profiles = {a: {"workspace": p["workspace"], "source_roots": {
        k: {"path": r["path"], "kind": r["kind"]} for k, r in p["source_roots"].items()}} for a, p in mapped.items()}
    plugins.setdefault("entries", {})["nas-filetools"] = {"enabled": True, "config": {
        "bindings": raw["bindings"], "workspaces": plugin_profiles, "management": {
            "python": raw.get("management_python", "/usr/bin/python3"),
            "entry": "/opt/nas-filetools-management/scripts/filetools_manage.py",
            "config": "/etc/nas-filetools-management.json"}}}
    tools = [*TOOLS, "filetools_register"]
    roster = updated.get("agents", {})
    agents = [{**entry, "id": key} for key, entry in roster.get("entries", {}).items()] if roster.get("entries") else roster.get("list", [])
    for agent in raw["agents"]:
        entry = next((a for a in agents if a.get("id") == agent), None)
        if roster.get("entries") and entry:
            entry = roster["entries"][agent]
        block = entry.setdefault("tools", {}) if entry else updated.setdefault("tools", {})
        also = block.setdefault("alsoAllow", [])
        also.extend(t for t in tools if t not in also)
    return updated


def compose_text(target, mapped, release, model_root, limits):
    def q(value):
        return json.dumps(str(value))
    worker_mounts = [str(release/"control")+":/var/lib/nas-filetools",
                     str(model_root)+":/var/cache/nas-filetools:ro", str(release/"socket")+":/run/nas-filetools",
                     str(release/"worker.json")+":/etc/nas-filetools/config.json:ro"]
    for agent, profile in mapped.items():
        worker_mounts.append(str(PurePosixPath(profile["host_workspace"])/"filetools")+":"+profile["service_root"])
        for root_id, root in profile["source_roots"].items():
            if root["kind"] == "nas":
                worker_mounts.append(root["host_path"]+":"+profile["processing_roots"][root_id]["path"]+":ro")
    gateway_mounts = [str(release/"socket")+":/run/nas-filetools",
        str(release/"manager")+":/opt/nas-filetools-management:ro",
        str(release/"gateway.json")+":/etc/nas-filetools-management.json:ro"]
    return (f"services:\n  {target['service']}:\n    volumes:\n"+"".join("      - "+q(m)+"\n" for m in gateway_mounts)+
        f"  nas-filetools:\n    image: nas-filetools:{VERSION}\n    user: \"{target['uid']}:{target['gid']}\"\n"
        f"    restart: unless-stopped\n    init: true\n    network_mode: none\n    read_only: true\n    cap_drop: [ALL]\n"
        f"    security_opt: [no-new-privileges:true]\n    cpus: {limits.engine_threads}\n    mem_limit: {limits.worker_memory_mb}m\n"
        "    pids_limit: 96\n    tmpfs: ['/tmp:size=256m,mode=1777']\n    volumes:\n"+
        "".join("      - "+q(m)+"\n" for m in worker_mounts))


def install(config, apply=False, local_only=False):
    raw, limits = configuration(config)
    root = Path(raw["data_root"])
    if root.exists() and (root.is_symlink() or any(p.name not in {"installation", "models", "migration", "workspace-map.json", "service.lock"} for p in root.iterdir())):
        raise Fault("DEDICATED_CONTROL_ROOT_REQUIRED")
    parent = root
    while not parent.exists():
        parent = parent.parent
    if shutil.disk_usage(parent).free < limits.disk_reserve_bytes+limits.max_receive_bytes:
        raise Fault("DISK_RESERVE")
    target = None if local_only else gateway(raw)
    document = {} if local_only else json.loads(Path(target["config"]).read_text(encoding="utf-8"))
    mapped = profiles(raw, target, document)
    result = {"status": "INSTALL_PLAN", "version": VERSION, "workspaces": mapped,
        "gateway": target, "production_changed": False, "existing_image_preserved": True,
        "requires": ["Gateway must already have Python >=3.11 stdlib/SQLite; no runtime pip/sudo",
                     "Linux Landlock ABI >=3 + seccomp; offline ASR model",
                     "Compose additive override; only new filetools directories change owner"]}
    if not apply:
        return result
    if local_only:
        for agent, profile in mapped.items():
            mapped_store({**profile, "workspace": profile["host_workspace"]}, agent, limits, "gateway")
        root.mkdir(parents=True, exist_ok=True)
        atomic_json(root/"workspace-map.json", {"limits": limits.dict(), "workspaces": mapped})
        return {**result, "status": "LOCAL_WORKSPACE_READY", "runtime_installed": False}
    if sys.platform != "linux" or not target["service"]:
        raise Fault("LINUX_COMPOSE_INSTALL_REQUIRED")
    if limits.script_isolation != "landlock":
        raise Fault("PRODUCTION_SCRIPT_ISOLATION_REQUIRED")
    if any(not any(b["agent_id"] == a for b in raw["bindings"]) for a in raw["agents"]):
        raise Fault("TRUSTED_BINDING_REQUIRED_FOR_ENABLED_AGENT")
    command(["docker", "exec", target["container"], raw.get("management_python", "/usr/bin/python3"), "-I", "-c",
             "import sys,sqlite3;assert sys.version_info >= (3,11)"], 30)
    before_plugins = plugin_inventory(target)
    release = root/"installation"/VERSION
    if (release/"rollback.json").exists():
        raise Fault("INSTALLATION_ALREADY_RECORDED", "Use diagnose or a new data_root; retain the previous rollback record.")
    release.mkdir(parents=True, exist_ok=True)
    for name in ("socket", "control", "manager"):
        folder = release/name
        folder.mkdir(exist_ok=True)
        os.chown(folder, target["uid"], target["gid"])
        os.chmod(folder, 0o750)
    # Initialize only the dedicated subtree, never chown the Agent workspace recursively.
    for agent, profile in mapped.items():
        subtree = Path(profile["host_workspace"])/"filetools"
        if subtree.exists() and (subtree.is_symlink() or subtree.stat().st_uid != target["uid"] or subtree.stat().st_gid != target["gid"]):
            raise Fault("EXISTING_FILETOOLS_OWNERSHIP_REQUIRES_REVIEW")
        created = not subtree.exists()
        local_profile = {**profile, "workspace": profile["host_workspace"]}
        mapped_store(local_profile, agent, limits, "gateway")
        if created:
            own_tree(subtree, target["uid"], target["gid"])
    shutil.copytree(REPOSITORY/"src", release/"manager"/"src", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    (release/"manager"/"scripts").mkdir(exist_ok=True)
    shutil.copyfile(REPOSITORY/"scripts"/"filetools_manage.py", release/"manager"/"scripts"/"filetools_manage.py")
    own_tree(release/"manager", target["uid"], target["gid"])
    plugin = release/"plugin"
    shutil.copytree(REPOSITORY/"integrations"/"openclaw-filetools", plugin,
        ignore=shutil.ignore_patterns("node_modules", "tests"))
    package = json.loads((plugin/"package.json").read_text())
    package.pop("devDependencies", None)
    atomic_json(plugin/"package.json", package)
    command(["docker", "run", "--rm", "-v", str(plugin)+":/plugin", "-w", "/plugin", "node:24.16.0-bookworm-slim",
             "npm", "install", "--omit=dev", "--ignore-scripts", "--legacy-peer-deps"], 600)
    mount = target["config_mount"]
    plugin_host = Path(mount["Source"])/"extensions"/"nas-filetools"
    plugin_gateway = str(Path(mount["Destination"])/"extensions"/"nas-filetools")
    if plugin_host.is_symlink():
        raise Fault("UNSAFE_PLUGIN_INSTALL_PATH")
    plugin_backup = release/"previous-plugin"
    if plugin_host.exists():
        if json.loads((plugin_host/"openclaw.plugin.json").read_text())["id"] != "nas-filetools":
            raise Fault("PLUGIN_PATH_CONFLICT")
        shutil.copytree(plugin_host, plugin_backup)
    updated = plugin_configuration(document, raw, mapped, plugin_gateway)
    # Remove only older load paths positively identified as this exact plugin; preserve all others.
    for loaded in list(updated["plugins"]["load"]["paths"]):
        if loaded == plugin_gateway:
            continue
        try:
            manifest = Path(host_path(loaded, target["mounts"]))/"openclaw.plugin.json"
            if manifest.is_file() and json.loads(manifest.read_text()).get("id") == "nas-filetools":
                updated["plugins"]["load"]["paths"].remove(loaded)
        except Fault:
            pass
    backup = release/"previous-openclaw.json"
    config_stat = Path(target["config"]).stat()
    shutil.copyfile(target["config"], backup)
    os.chmod(backup, 0o600)
    command(["docker", "build", "-f", str(REPOSITORY/"deploy"/"Dockerfile"), "-t", "nas-filetools:"+VERSION, str(REPOSITORY)], 1800)
    models = root/"models"
    models.mkdir(exist_ok=True)
    revision = "536b0662742c02347bc0e980a01041f333bce120"
    snapshot = models/"models--Systran--faster-whisper-small"/"snapshots"/revision
    if limits.whisper_model == "small":
        if not (snapshot/"model.bin").is_file():
            os.chown(models, target["uid"], target["gid"])
            command(["docker", "run", "--rm", "--user", f"{target['uid']}:{target['gid']}", "-v", str(models)+":/var/cache/nas-filetools",
                "--entrypoint", "/opt/nas-filetools/.venv/bin/python", "nas-filetools:"+VERSION, "/opt/nas-filetools/prepare_models.py",
                "--model", "small", "--cache", "/var/cache/nas-filetools", "--revision", revision], 1800)
        from dataclasses import replace
        limits = replace(limits, whisper_model="/var/cache/nas-filetools/models--Systran--faster-whisper-small/snapshots/"+revision)
    shared = {"limits": limits.dict(), "workspaces": mapped}
    atomic_json(release/"gateway.json", shared)
    atomic_json(release/"worker.json", shared)
    runtime_config_permissions(release, target["uid"], target["gid"])
    override = release/"compose.filetools.yaml"
    override.write_text(compose_text(target, mapped, release, models, limits), encoding="utf-8")
    compose = ["docker", "compose"]
    if target["project"]:
        compose.extend(["-p", target["project"]])
    for file in target["compose"]:
        compose.extend(["-f", file])
    record = {"backup": str(backup), "config": target["config"], "installed_sha256": hashlib.sha256(json.dumps(updated, ensure_ascii=False).encode()).hexdigest(),
        "base_compose": target["compose"], "service": target["service"], "new_data_preserved": [str(root), *[str(Path(p["host_workspace"])/"filetools") for p in mapped.values()]],
        "project": target["project"], "override": str(override), "plugin_path": str(plugin_host), "uid": target["uid"], "gid": target["gid"],
        "plugin_backup": str(plugin_backup) if plugin_backup.exists() else None, "plugins_before": before_plugins}
    effective = json.loads(command([*compose, "-f", str(override), "config", "--format", "json"], 60))
    validate_effective_compose(effective, target, mapped)
    atomic_json(release/"rollback.json", record)
    try:
        shutil.copytree(plugin, plugin_host, dirs_exist_ok=True)
        own_tree(plugin_host, target["uid"], target["gid"])
        atomic_json(target["config"], updated)
        os.chown(target["config"], config_stat.st_uid, config_stat.st_gid)
        os.chmod(target["config"], config_stat.st_mode & 0o777)
        command([*compose, "-f", str(override), "up", "-d", "nas-filetools", target["service"]], 600)
        command(["docker", "exec", target["container"], "openclaw", "plugins", "validate", "--entry", plugin_gateway+"/src/index.mjs"], 120)
    except Exception:
        from .operations import rollback
        rollback(release/"rollback.json", apply=True)
        raise
    checks = diagnose(config)
    return {**result, "status": "INSTALLED_WITH_ISSUES" if checks["issues"] else "INSTALLED", "self_check": checks,
            "production_changed": True, "rollback_record": str(release/"rollback.json")}


def validate_effective_compose(effective, target, mapped):
    services = effective["services"]
    if target.get("image") and services[target["service"]].get("image") != target["image"]:
        raise Fault("EXISTING_GATEWAY_IMAGE_CHANGED_IN_COMPOSE")
    expected = {"/var/lib/nas-filetools", "/var/cache/nas-filetools", "/run/nas-filetools", "/etc/nas-filetools/config.json"}
    for profile in mapped.values():
        expected.add(profile["service_root"])
        expected.update(r["path"] for r in profile["processing_roots"].values())
    volumes = services["nas-filetools"].get("volumes", [])
    if any(v.get("target") not in expected or v.get("type") != "bind" for v in volumes) or {v["target"] for v in volumes} != expected:
        raise Fault("UNEXPECTED_EFFECTIVE_WORKER_MOUNT", "Review inherited Compose worker mounts; never mount the full state or authentication tree.")


def runtime_config_permissions(release, uid, gid):
    for name in ("gateway.json", "worker.json"):
        os.chmod(release/name, 0o640)
        os.chown(release/name, uid, gid)


def plugin_inventory(target):
    raw = json.loads(command(["docker", "exec", target["container"], "openclaw", "plugins", "list", "--json"], 120))
    return [{k: row.get(k) for k in ("id", "status", "enabled", "toolNames")} for row in (raw.get("plugins", []) if isinstance(raw, dict) else raw)]


def diagnostic_marker(marker, token, uid, gid):
    """Change only our new marker, independent of the host operator's umask."""
    with marker.open("x", encoding="utf-8") as output:
        output.write(token)
    os.chown(marker, uid, gid)
    os.chmod(marker, 0o660)


def diagnose(config, local_only=False):
    raw, limits = configuration(config)
    issues, checks = [], {}
    try:
        target = None if local_only else gateway(raw)
        document = {} if local_only else json.loads(Path(target["config"]).read_text())
        mapped = profiles(raw, target, document)
        checks["agents"] = {}
        for agent, profile in mapped.items():
            identity = {"user_id": AGENT_USERS.get(agent, agent), "agent_id": agent, "session_hash": "0"*64}
            local = {**profile, "workspace": profile["host_workspace"]}
            store = mapped_store(local, agent, limits, "gateway")
            checks["agents"][agent] = {"capacity": store.capacity(identity), "gateway_workspace": profile["workspace"], "worker_root": profile["service_root"]}
            if target:
                # Probe ONLY the dedicated subtree, then verify the exact bytes in each container.
                token = os.urandom(16).hex()
                marker = store.root/(".diagnostic-"+token)
                try:
                    diagnostic_marker(marker, token, target["uid"], target["gid"])
                    read = "from pathlib import Path;import sys;assert Path(sys.argv[1]).read_text()==sys.argv[2]"
                    command(["docker", "exec", "--user", f"{target['uid']}:{target['gid']}", target["container"], raw.get("management_python", "/usr/bin/python3"), "-I", "-c", read,
                             profile["workspace"]+"/filetools/"+marker.name, token])
                    worker_name = command(["docker", "ps", "--filter", "label=com.docker.compose.project="+target["project"],
                        "--filter", "label=com.docker.compose.service=nas-filetools", "--format", "{{.ID}}"] ).strip()
                    if "\n" in worker_name:
                        raise Fault("AMBIGUOUS_WORKER_CONTAINER")
                    if not worker_name:
                        raise Fault("WORKER_CONTAINER_NOT_FOUND")
                    worker_uid = int(command(["docker", "exec", worker_name, "id", "-u"]).strip())
                    worker_gid = int(command(["docker", "exec", worker_name, "id", "-g"]).strip())
                    if (worker_uid, worker_gid) != (target["uid"], target["gid"]):
                        raise Fault("WORKER_IDENTITY_MISMATCH")
                    write = "from pathlib import Path;import sys;Path(sys.argv[1]).write_text(sys.argv[2])"
                    command(["docker", "exec", "--user", f"{target['uid']}:{target['gid']}", target["container"], raw.get("management_python", "/usr/bin/python3"), "-I", "-c", write,
                             profile["workspace"]+"/filetools/"+marker.name, token+"gateway"])
                    command(["docker", "exec", worker_name, "/opt/nas-filetools/.venv/bin/python", "-I", "-c", read,
                             profile["service_root"]+"/"+marker.name, token+"gateway"])
                    command(["docker", "exec", worker_name, "/opt/nas-filetools/.venv/bin/python", "-I", "-c", write, profile["service_root"]+"/"+marker.name, token+"worker"])
                    command(["docker", "exec", "--user", f"{target['uid']}:{target['gid']}", target["container"], raw.get("management_python", "/usr/bin/python3"), "-I", "-c", read,
                             profile["workspace"]+"/filetools/"+marker.name, token+"worker"])
                    checks["agents"][agent]["two_container_visibility"] = True
                finally:
                    marker.unlink(missing_ok=True)
        if local_only:
            checks["runtime"] = "NOT_CHECKED_LOCAL_ONLY"
        else:
            checks["plugins"] = plugin_inventory(target)
            current = {r["id"]: r for r in checks["plugins"]}
            record_path = Path(raw["data_root"])/"installation"/VERSION/"rollback.json"
            previous = json.loads(record_path.read_text()).get("plugins_before", []) if record_path.exists() else []
            for record in previous:
                if record["id"] != "nas-filetools" and record["status"] == "loaded" and current.get(record["id"], {}).get("status") != "loaded":
                    issues.append("EXISTING_PLUGIN_NO_LONGER_LOADED:"+record["id"])
            if current.get("nas-filetools", {}).get("status") != "loaded":
                issues.append("PLUGIN_NOT_REPORTED_LOADED")
            from .cli import UnixConnection
            connection = UnixConnection(str(Path(raw["data_root"])/"installation"/VERSION/"socket"/"service.sock"))
            connection.timeout = 90
            try:
                for agent in raw["agents"]:
                    identity = {"user_id": AGENT_USERS.get(agent, agent), "agent_id": agent, "session_hash": "0"*64}
                    connection.request("POST", "/v1/tool", json.dumps({"identity": identity, "operation": "diagnostics", "params": {}}))
                    report = json.loads(connection.getresponse().read(limits.max_response_bytes))
                    checks["agents"][agent]["worker_runtime"] = report
                    issues.extend(report.get("issues", []))
            finally:
                connection.close()
            checks["qq_delivery"] = "PENDING_REAL_RECIPIENT_DOWNLOAD_AND_MESSAGE_RECEIPT"
    except (Fault, OSError, ValueError) as error:
        issues.append(error.code if isinstance(error, Fault) else type(error).__name__)
    return {"status": "DIAGNOSED", "checks": checks, "issues": issues, "runtime_verified": not local_only and not issues,
            "production_acceptance": "PENDING", "time": timestamp()}


def migrate(config, old_root, agent_map, apply=False):
    """Copy V1.1 business snapshots/saved bundles, preserve provenance/IDs; old cache remains historical."""
    raw, limits = configuration(config)
    deployed_map = Path(raw["data_root"])/"installation"/VERSION/"gateway.json"
    mapped = json.loads(deployed_map.read_text())["workspaces"] if deployed_map.is_file() else profiles(raw)
    old = Path(str(old_root).removeprefix("\\\\?\\")).resolve()
    mapping = json.loads(Path(agent_map).read_text(encoding="utf-8"))
    with sqlite3.connect((old/'jobs.sqlite3').as_uri()+"?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        files = [dict(r) for r in db.execute("SELECT * FROM files WHERE state='LIVE'")]
        saved = [dict(r) for r in db.execute("SELECT * FROM saved")]
        attachments = [dict(r) for r in db.execute("SELECT * FROM attachments")]
    for prior, new in mapping.items():
        if prior != new or new not in mapped:
            raise Fault("MIGRATION_CANNOT_MERGE_OR_RENAME_AGENT_IDENTITY")
        destination = Path(mapped[new]["host_workspace"])/"filetools"
        if destination.resolve().is_relative_to(old) or old.is_relative_to(destination.resolve()):
            raise Fault("SEPARATE_MIGRATION_ROOT_REQUIRED")
    unknown = sorted({r["agent"] for r in [*files, *saved]}-set(mapping))
    result = {"status": "MIGRATION_PLAN", "mapped_agents": sorted(mapping), "paused_agents": unknown,
              "old_root_untouched": True, "old_cache": "retained; select snapshot to reprocess", "saved_bundles_independent": True}
    if not apply:
        return result
    from .worker import ServiceLock
    lock = ServiceLock(old)
    try:
        # Refresh the plan under the service lock: an old worker may have finished
        # a job between the read-only preview and acquiring this lock.
        with sqlite3.connect((old/'jobs.sqlite3').as_uri()+"?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            files = [dict(r) for r in db.execute("SELECT * FROM files WHERE state='LIVE'")]
            saved = [dict(r) for r in db.execute("SELECT * FROM saved")]
            attachments = [dict(r) for r in db.execute("SELECT * FROM attachments")]
        unknown = sorted({r["agent"] for r in [*files, *saved]}-set(mapping))
        result["paused_agents"] = unknown
        backup_root = Path(raw["data_root"])/"migration"/str(time.time_ns())
        backup_root.mkdir(parents=True)
        backup = backup_root/"v11-registry.sqlite"
        with sqlite3.connect(old/"jobs.sqlite3") as source, sqlite3.connect(backup) as target:
            source.backup(target)
        for agent in mapping:
            profile = {**mapped[agent], "workspace": mapped[agent]["host_workspace"]}
            store = mapped_store(profile, agent, limits, "gateway")
            backup_files = []
            with store.lock, store.db() as db:
                for record in [r for r in files if r["agent"] == agent]:
                    path = old/record["path"]
                    if path.is_symlink() or not path.resolve().is_relative_to(old) or not path.is_file() or digest_file(path) != record["sha"]:
                        raise Fault("MIGRATION_SOURCE_CHANGED")
                    from .workspace import category_v12
                    category = category_v12(record["category"])
                    destination = store.root/"snapshots"/category/path.name
                    if not destination.exists():
                        from .management import snapshot_copy
                        snapshot_copy(path, destination, limits.max_receive_bytes, record["size"], record["sha"])
                    if digest_file(destination) != record["sha"]:
                        raise Fault("MIGRATION_DESTINATION_CONFLICT")
                    backup_files.append({"source": record["path"], "destination": str(destination.relative_to(store.root)), "sha256": record["sha"], "file_id": record["id"]})
                    changed = {**record, "category": category, "path": str(destination.relative_to(store.root)), "mode": "snapshot"}
                    prior = db.execute("SELECT sha,path FROM files WHERE id=?", (record["id"],)).fetchone()
                    if prior and (prior["sha"] != record["sha"] or prior["path"] != changed["path"]):
                        raise Fault("MIGRATION_DESTINATION_CONFLICT")
                    db.execute("INSERT OR IGNORE INTO files VALUES(?,?,?,?,?,?,?,?,?,?)", tuple(changed[k] for k in
                        ("id", "agent", "sha", "size", "category", "path", "info", "created", "state", "mode")))
                    for attachment in [a for a in attachments if a["file_id"] == record["id"]]:
                        db.execute("INSERT OR IGNORE INTO attachments VALUES(?,?,?,?,?,?,?,?,?,?,?)", tuple(attachment[k] for k in
                            ("id", "owner", "filename", "sha", "size", "info", "created", "file_id", "agent", "source", "active")))
                for record in [r for r in saved if r["agent"] == agent]:
                    source = old/record["path"]
                    if source.is_symlink() or not source.is_dir() or not source.resolve().is_relative_to(old):
                        raise Fault("MIGRATION_SAVED_SOURCE_INVALID")
                    category = __import__("nas_filetools.workspace", fromlist=["category_v12"]).category_v12(json.loads(record["info"])["category"])
                    destination = store.root/"saved"/category/record["id"]
                    hashes = {p.relative_to(source).as_posix(): digest_file(p) for p in source.rglob("*") if p.is_file()}
                    if any(p.is_symlink() for p in source.rglob("*")):
                        raise Fault("MIGRATION_SAVED_SYMLINK")
                    if not destination.exists():
                        temporary = destination.with_name(".migration-"+record["id"])
                        shutil.copytree(source, temporary)
                        if any(digest_file(temporary/name) != digest for name, digest in hashes.items()):
                            raise Fault("MIGRATION_SOURCE_CHANGED")
                        os.replace(temporary, destination)
                    if any(not (destination/name).is_file() or digest_file(destination/name) != digest for name, digest in hashes.items()):
                        raise Fault("MIGRATION_DESTINATION_CONFLICT")
                    backup_files.append({"saved_id": record["id"], "source": record["path"], "destination": str(destination.relative_to(store.root)), "sha256_by_relative_path": hashes})
                    changed = {**record, "path": str(destination.relative_to(store.root))}
                    db.execute("INSERT OR IGNORE INTO saved VALUES(?,?,?,?,?,?,?)", tuple(changed[k] for k in ("id", "agent", "file_id", "job_id", "path", "created", "info")))
            atomic_json(backup_root/(agent+"-business-files.json"), backup_files)
        atomic_json(backup_root/"migration.json", {**result, "old_root": str(old), "registry_backup": str(backup)})
        return {**result, "status": "PARTIAL_MIGRATION" if unknown else "MIGRATED", "metadata_backup": str(backup)}
    finally:
        lock.close()
