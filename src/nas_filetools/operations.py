"""Operator-only installation planning, diagnostics, migration and reversible configuration."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from .catalog import atomic_json, digest_file, timestamp
from .contracts import AGENT_USERS, Fault, Limits, owner, strict
from .engines import version
from .store import Store

WORKER_UID = 10001
TOOLS = ["filetools_"+n for n in ("inspect", "extract", "status", "cancel", "read", "find", "save_minutes", "files", "python")]
REPOSITORY = Path(__file__).resolve().parents[2]


def settings(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    strict(raw, ("data_root", "agents", "bindings", "limits", "gateway_container", "gateway_config", "compose_service"),
           ("data_root", "agents", "bindings"))
    if not Path(raw["data_root"]).is_absolute():
        raise Fault("ABSOLUTE_DATA_ROOT_REQUIRED")
    limits = Limits(**{**raw.get("limits", {}), "enabled_agents": raw["agents"]})
    seen = set()
    for binding in raw["bindings"]:
        strict(binding, ("agent_id", "sender_id", "channel_id", "account_id", "user_id"),
               ("agent_id", "sender_id", "channel_id", "account_id"))
        key = tuple(binding.get(k) for k in ("channel_id", "account_id", "sender_id"))
        if binding["agent_id"] not in limits.enabled_agents or key in seen or any(not isinstance(v, str) or not v for v in key):
            raise Fault("INVALID_BINDINGS")
        if binding.get("user_id", AGENT_USERS.get(binding["agent_id"], binding["agent_id"])) != AGENT_USERS.get(binding["agent_id"], binding["agent_id"]):
            raise Fault("INVALID_BINDINGS")
        seen.add(key)
    return raw, limits


def command(args, timeout=60):
    result = subprocess.run(args, capture_output=True, timeout=timeout, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        # Docker/CLI output can contain credentials. Return only the operation and exit code.
        raise Fault("OPERATOR_COMMAND_FAILED", f"{args[0]} exit {result.returncode}")
    return result.stdout


def own_tree(directory, uid, gid):
    if Path(directory).is_symlink():
        raise Fault("UNSAFE_OWNERSHIP_TARGET")
    for parent, _directories, files in os.walk(directory):
        os.chown(parent, uid, gid)
        for name in files:
            file = Path(parent)/name
            if not file.is_symlink():
                os.chown(file, uid, gid)


def gateway(raw):
    names = command(["docker", "ps", "--format", "{{.Names}}"] ).splitlines()
    container = raw.get("gateway_container")
    if not container:
        candidates = [n for n in names if "openclaw" in n and "gateway" in n]
        if len(candidates) != 1:
            raise Fault("SELECT_GATEWAY_CONTAINER")
        container = candidates[0]
    info = json.loads(command(["docker", "inspect", container]))[0]
    actual = command(["docker", "exec", container, "openclaw", "--version"]).strip()
    if "2026.9.4" not in actual:
        raise Fault("OPENCLAW_VERSION_MISMATCH")
    uid = int(command(["docker", "exec", container, "id", "-u"]).strip())
    gid = int(command(["docker", "exec", container, "id", "-g"]).strip())
    labels = info.get("Config", {}).get("Labels", {}) or {}
    mounts = [{k: m[k] for k in ("Source", "Destination", "Type", "RW")} for m in info["Mounts"]]
    compose = labels.get("com.docker.compose.project.config_files", "").split(",")
    if not compose or any(not Path(p).is_file() for p in compose):
        raise Fault("COMPOSE_SOURCE_REQUIRED")
    config = raw.get("gateway_config")
    if not config:
        candidates = [str(Path(m["Source"])/"openclaw.json") for m in mounts if m["Type"] == "bind" and m["RW"]
                      and Path(m["Source"], "openclaw.json").is_file()]
        if len(candidates) != 1:
            raise Fault("SELECT_GATEWAY_CONFIG")
        config = candidates[0]
    target = next((m for m in mounts if m["Type"] == "bind" and m["RW"] and
                   Path(config).resolve().is_relative_to(Path(m["Source"]).resolve())), None)
    if not target or not Path(target["Source"]).is_dir():
        raise Fault("PERSISTENT_GATEWAY_CONFIG_MOUNT_REQUIRED")
    # JSON5 is deliberately rejected rather than rewriting comments incorrectly.
    document = json.loads(Path(config).read_text(encoding="utf-8"))
    roster = document.get("agents", {})
    entries = [{**entry, "id": key} for key, entry in roster.get("entries", {}).items()] if roster.get("entries") else roster.get("list", [])
    for agent in raw["agents"]:
        found = next((a for a in entries if a.get("id") == agent), None)
        if not found and agent != "main":
            raise Fault("AGENT_NOT_CONFIGURED")
        denied = set((found or {}).get("tools", {}).get("deny", [])) | set(document.get("tools", {}).get("deny", []))
        required = [*TOOLS, *(["filetools_register"] if raw.get("workspace_layout") == "shared-v1.2" else [])]
        if any(t in denied for t in required) or "nas-filetools" in denied or "group:plugins" in denied or "*" in denied:
            raise Fault("FILETOOLS_DENIED_BY_EXISTING_POLICY")
    return {"container": container, "version": actual, "uid": uid, "gid": gid, "mounts": mounts,
            "image": info.get("Config", {}).get("Image"),
            "config": config, "config_mount": target, "compose": compose,
            "project": labels.get("com.docker.compose.project", ""),
            "service": raw.get("compose_service", labels.get("com.docker.compose.service", ""))}


def install(config, apply=False, local_only=False):
    if json.loads(Path(config).read_text(encoding="utf-8")).get("workspace_layout") == "shared-v1.2":
        from .operations_v12 import install as install_shared
        return install_shared(config, apply, local_only)
    raw, limits = settings(config)
    root = Path(raw["data_root"])
    if root.exists() and any(p.name not in {"agents", "incoming", "installation", "models", "jobs.sqlite3", "jobs.sqlite3-wal",
            "jobs.sqlite3-shm", "service.lock", "filetools.json"} and not p.name.startswith("v1-metadata-") for p in root.iterdir()):
        raise Fault("DEDICATED_DATA_ROOT_REQUIRED")
    checks = {"python": sys.version.split()[0], "free_bytes": shutil.disk_usage(root if root.exists() else root.parent).free,
              "dependencies": {p: version(p) for p in ("PyMuPDF", "python-docx", "openpyxl", "rapidocr-onnxruntime", "faster-whisper")}}
    if checks["free_bytes"] < limits.disk_reserve_bytes+limits.max_receive_bytes:
        raise Fault("DISK_RESERVE")
    target = None if local_only else gateway(raw)
    result = {"status": "INSTALL_PLAN", "version": "1.1.0", "data_root": str(root), "agents": raw["agents"],
              "checks": checks, "gateway": target, "worker_uid": WORKER_UID, "requires": ["Docker/Compose operator rights", "Gateway recreate for socket bind mount",
              "Build network for pinned dependencies; pre-download ASR model, then runtime network disabled",
              "Landlock ABI >=3 and libseccomp for scripts; no runtime pip or sudo"], "production_changed": False}
    if not apply:
        return result
    if local_only:
        Store(root, limits)
        atomic_json(root/"filetools.json", limits.dict())
        result.update(status="LOCAL_WORKSPACE_READY", runtime_installed=False)
        return result
    if any(not any(b["agent_id"] == agent for b in raw["bindings"]) for agent in raw["agents"]):
        raise Fault("TRUSTED_BINDING_REQUIRED_FOR_ENABLED_AGENT")
    if sys.platform != "linux" or not target["service"]:
        raise Fault("LINUX_COMPOSE_INSTALL_REQUIRED")
    if os.geteuid() != 0 and (os.geteuid() != WORKER_UID or os.geteuid() != target["uid"]):
        raise Fault("DATA_OWNERSHIP_REQUIRES_OPERATOR_RIGHTS")
    Store(root, limits)
    release = root/"installation"/"1.1.0"
    release.mkdir(parents=True, exist_ok=True)
    plugin = release/"plugin"
    source = REPOSITORY/"integrations"/"openclaw-filetools"
    shutil.copytree(source, plugin, dirs_exist_ok=True, ignore=shutil.ignore_patterns("node_modules", "tests"))
    plugin_manifest = plugin/"package.json"
    # No dev Gateway dependency in the production plugin install.
    package = json.loads(plugin_manifest.read_text())
    package.pop("devDependencies", None)
    atomic_json(plugin_manifest, package)
    command(["docker", "run", "--rm", "-v", f"{plugin}:/plugin", "-w", "/plugin", "node:24.16.0-bookworm-slim",
             "npm", "install", "--omit=dev", "--ignore-scripts", "--legacy-peer-deps"], 600)
    socket_dir = release/"socket"
    socket_dir.mkdir(exist_ok=True)
    model_dir = root/"models"
    model_dir.mkdir(exist_ok=True)
    mount = target["config_mount"]
    gateway_plugin = str(Path(mount["Destination"])/"extensions"/"nas-filetools")
    gateway_plugin_host = Path(mount["Source"])/"extensions"/"nas-filetools"
    if gateway_plugin_host.is_symlink():
        raise Fault("UNSAFE_PLUGIN_INSTALL_PATH")
    plugin_backup = release/("gateway-plugin-"+str(time.time_ns()))
    if gateway_plugin_host.exists():
        if json.loads((gateway_plugin_host/"openclaw.plugin.json").read_text())["id"] != "nas-filetools":
            raise Fault("PLUGIN_PATH_CONFLICT")
        shutil.copytree(gateway_plugin_host, plugin_backup)
    config_path = Path(target["config"])
    previous = config_path.read_bytes()
    backup = release/("gateway-"+str(time.time_ns())+".json")
    backup.write_bytes(previous)
    os.chmod(backup, 0o600)
    updated = json.loads(previous)
    plugins = updated.setdefault("plugins", {})
    allowed = plugins.get("allow", [])
    if allowed and "nas-filetools" not in allowed:
        allowed.append("nas-filetools")
    paths = plugins.setdefault("load", {}).setdefault("paths", [])
    # Remove only explicitly configured older copies of this exact plugin.
    for loaded in list(paths):
        for existing_mount in target["mounts"]:
            base = Path(existing_mount["Destination"])
            if Path(loaded).is_relative_to(base):
                candidate = Path(existing_mount["Source"])/Path(loaded).relative_to(base)
                manifest = candidate/"openclaw.plugin.json"
                if manifest.is_file() and json.loads(manifest.read_text()).get("id") == "nas-filetools" and loaded != gateway_plugin:
                    paths.remove(loaded)
                    break
    if gateway_plugin not in paths:
        paths.append(gateway_plugin)
    plugins.setdefault("entries", {})["nas-filetools"] = {"enabled": True, "config": {"bindings": raw["bindings"]}}
    for agent in updated.get("agents", {}).get("list", []):
        if agent.get("id") in raw["agents"]:
            allowed_tools = agent.setdefault("tools", {}).setdefault("alsoAllow", [])
            for tool in TOOLS:
                if tool not in allowed_tools:
                    allowed_tools.append(tool)
    if "main" in raw["agents"] and not any(a.get("id") == "main" for a in updated.get("agents", {}).get("list", [])):
        allowed_tools = updated.setdefault("tools", {}).setdefault("alsoAllow", [])
        for tool in TOOLS:
            if tool not in allowed_tools:
                allowed_tools.append(tool)
    image = "nas-filetools:1.1.0"
    command(["docker", "build", "-f", str(REPOSITORY/"deploy"/"Dockerfile"), "-t", image, str(REPOSITORY)], 1800)
    if limits.whisper_model == "small":
        from dataclasses import replace
        revision = "536b0662742c02347bc0e980a01041f333bce120"
        local_snapshot = model_dir/"models--Systran--faster-whisper-small"/"snapshots"/revision
        if not (local_snapshot/"model.bin").is_file():
            os.chown(model_dir, WORKER_UID, target["gid"])
            command(["docker", "run", "--rm", "--user", f"{WORKER_UID}:{target['gid']}",
                "-v", str(model_dir)+":/var/cache/nas-filetools", "--entrypoint", "/opt/nas-filetools/.venv/bin/python",
                image, "/opt/nas-filetools/prepare_models.py", "--model", "small", "--cache", "/var/cache/nas-filetools",
                "--revision", revision], 1800)
        limits = replace(limits, whisper_model="/var/cache/nas-filetools/models--Systran--faster-whisper-small/snapshots/"+revision)
    atomic_json(release/"filetools.json", limits.dict())
    def quoted(value):
        return json.dumps(str(value))
    override = release/"compose.filetools.yaml"
    override.write_text(f'''services:
  {target['service']}:
    volumes:
      - {quoted(str(socket_dir)+':/run/nas-filetools')}
  nas-filetools:
    image: {image}
    user: "{WORKER_UID}:{target['gid']}"
    restart: unless-stopped
    network_mode: none
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    cpus: {limits.engine_threads}
    mem_limit: {limits.worker_memory_mb}m
    pids_limit: 96
    volumes:
      - {quoted(str(root)+':/var/lib/nas-filetools')}
      - {quoted(str(model_dir)+':/var/cache/nas-filetools:ro')}
      - {quoted(str(socket_dir)+':/run/nas-filetools')}
      - {quoted(str(release/'filetools.json')+':/etc/nas-filetools/config.json:ro')}
    tmpfs: ['/tmp:size=256m,mode=1777']
''', encoding="utf-8")
    own_tree(root, WORKER_UID, target["gid"])
    os.chmod(socket_dir, 0o750)
    compose = ["docker", "compose"]
    if target["project"]:
        compose.extend(["-p", target["project"]])
    for file in target["compose"]:
        compose.extend(["-f", file])
    compose.extend(["-f", str(override)])
    atomic_json(release/"rollback.json", {"backup": str(backup), "config": str(config_path),
        "installed_sha256": __import__("hashlib").sha256(json.dumps(updated, ensure_ascii=False).encode()).hexdigest(),
        "base_compose": target["compose"], "service": target["service"], "new_data_preserved": str(root),
        "project": target["project"], "override": str(override), "plugin_path": str(gateway_plugin_host),
        "uid": target["uid"], "gid": target["gid"],
        "plugin_backup": str(plugin_backup) if plugin_backup.exists() else None,
        "old_runtime": "Existing Gateway image/Compose unchanged; remove additive override on rollback."})
    try:
        shutil.copytree(plugin, gateway_plugin_host, dirs_exist_ok=True)
        own_tree(gateway_plugin_host, target["uid"], target["gid"])
        atomic_json(config_path, updated)
        command([*compose, "up", "-d", "nas-filetools", target["service"]], 600)
        command(["docker", "exec", target["container"], "openclaw", "plugins", "validate", "--entry", gateway_plugin+"/src/index.mjs"], 120)
    except Exception:
        try:
            rollback(release/"rollback.json", apply=True)
        except Exception:
            config_path.write_bytes(previous)
            if plugin_backup.exists():
                shutil.copytree(plugin_backup, gateway_plugin_host, dirs_exist_ok=True)
                own_tree(gateway_plugin_host, target["uid"], target["gid"])
            raise Fault("INSTALL_FAILED_RECOVERY_REQUIRED") from None
        raise
    self_check = diagnose(config)
    result.update(status="INSTALLED_WITH_ISSUES" if self_check["issues"] else "INSTALLED", self_check=self_check, production_changed=True, rollback_record=str(release/"rollback.json"),
                  next="Run nas-filetools diagnose; ASR availability requires prepared offline model.")
    return result


def rollback(record_path, apply=False):
    record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    result = {"status": "ROLLBACK_PLAN", "restore_config": record["config"], "data_preserved": record["new_data_preserved"],
              "restart": "Stop new worker, recreate original Gateway; restore original worker if present in base Compose."}
    if not apply:
        return result
    config = Path(record["config"])
    current = json.loads(config.read_text(encoding="utf-8"))
    digest = __import__("hashlib").sha256(json.dumps(current, ensure_ascii=False).encode()).hexdigest()
    if digest != record["installed_sha256"]:
        raise Fault("ROLLBACK_CONFIG_CHANGED", "Merge the saved backup manually to preserve later operator changes.")
    compose = ["docker", "compose"]
    if record.get("project"):
        compose.extend(["-p", record["project"]])
    for file in record["base_compose"]:
        compose.extend(["-f", file])
    command([*compose, "-f", record["override"], "stop", "nas-filetools"], 120)
    plugin = Path(record["plugin_path"])
    if plugin.is_symlink() or json.loads((plugin/"openclaw.plugin.json").read_text()).get("id") != "nas-filetools":
        raise Fault("UNSAFE_PLUGIN_ROLLBACK_PATH")
    retained = Path(record_path).parent/("retained-filetools-plugin-"+str(time.time_ns()))
    shutil.move(str(plugin), retained)
    if record["plugin_backup"]:
        shutil.copytree(record["plugin_backup"], plugin)
        own_tree(plugin, record["uid"], record["gid"])
    config.write_bytes(Path(record["backup"]).read_bytes())
    base = json.loads(command([*compose, "config", "--format", "json"]))
    services = [record["service"]]
    if "nas-filetools" in base["services"]:
        services.append("nas-filetools")
    command([*compose, "up", "-d", "--force-recreate", *services], 600)
    result.update(status="ROLLED_BACK", new_plugin_retained=str(retained))
    return result


def diagnose(config, local_only=False):
    if json.loads(Path(config).read_text(encoding="utf-8")).get("workspace_layout") == "shared-v1.2":
        from .operations_v12 import diagnose as diagnose_shared
        return diagnose_shared(config, local_only)
    raw, limits = settings(config)
    issues, checks = [], {}
    try:
        store = Store(raw["data_root"], limits)
        identity = {"agent_id": raw["agents"][0], "user_id": AGENT_USERS.get(raw["agents"][0], raw["agents"][0]), "session_hash": "0"*64}
        checks["workspace"] = store.capacity(identity)
        checks["bindings_count"] = len(raw["bindings"])
        checks["dependencies"] = {p: version(p) for p in ("PyMuPDF", "python-docx", "openpyxl", "rapidocr-onnxruntime", "faster-whisper")}
        checks["ffmpeg"] = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        checks["script_isolation"] = limits.script_isolation
        if limits.script_isolation == "development":
            issues.append("DEVELOPMENT_SCRIPT_MODE_NOT_PRODUCTION_ISOLATION")
        if not local_only:
            checks["gateway"] = gateway(raw)
            from .cli import UnixConnection
            endpoint = Path(raw["data_root"])/"installation"/"1.1.0"/"socket"/"service.sock"
            client = UnixConnection(str(endpoint))
            try:
                client.request("POST", "/v1/tool", json.dumps({"identity": identity, "operation": "health", "params": {}}))
                checks["service"] = json.loads(client.getresponse().read(limits.max_response_bytes))
                if checks["service"]["status"] != "HEALTHY":
                    issues.append("SCHEDULER_UNHEALTHY")
                client.timeout = 90
                client.close()
                client.request("POST", "/v1/tool", json.dumps({"identity": identity, "operation": "diagnostics", "params": {}}))
                checks["worker_runtime"] = json.loads(client.getresponse().read(limits.max_response_bytes))
                issues.extend(checks["worker_runtime"].get("issues", []))
                if checks["worker_runtime"]["status"] != "RUNTIME_DIAGNOSTICS":
                    issues.append("RUNTIME_CHECK_DEFERRED")
                target = checks["gateway"]
                plugins = json.loads(command(["docker", "exec", target["container"], "openclaw", "plugins", "list", "--json"]))
                entries = plugins.get("plugins", []) if isinstance(plugins, dict) else plugins
                selected = next((p for p in entries if p.get("id") == "nas-filetools"), None)
                checks["plugin"] = {k: selected.get(k) for k in ("id", "status", "enabled", "toolNames")} if selected else {"status": "MISSING"}
                if not selected or selected.get("status") != "loaded":
                    issues.append("PLUGIN_NOT_REPORTED_LOADED")
                checks["gateway_tools"] = "SDK contracts present; live Agent call/QQ E2E still requires acceptance."
                checks["socket_mount"] = any(m["Destination"] == "/run/nas-filetools" for m in target["mounts"])
                if not checks["socket_mount"]:
                    issues.append("GATEWAY_SOCKET_MOUNT_MISSING")
            finally:
                client.close()
        else:
            checks["runtime"] = "NOT_CHECKED_LOCAL_ONLY"
    except (Fault, OSError, ValueError) as error:
        issues.append(error.code if isinstance(error, Fault) else type(error).__name__)
    return {"status": "DIAGNOSED", "checks": checks, "issues": issues,
            "runtime_verified": not local_only and not issues, "time": timestamp()}


def migrate(old_root, new_root, limits, identity_map, apply=False):
    old = Path(old_root).resolve()
    new = Path(new_root).resolve()
    if old == new or new.is_relative_to(old) or old.is_relative_to(new):
        raise Fault("SEPARATE_MIGRATION_ROOT_REQUIRED")
    mapping = json.loads(Path(identity_map).read_text(encoding="utf-8"))
    with sqlite3.connect(f"file:{(old/'jobs.sqlite3').as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        attachments = [dict(r) for r in db.execute("SELECT * FROM attachments")]
    for row in attachments:
        identity = mapping.get(row["owner"])
        if not identity or owner(identity) != row["owner"] or identity["agent_id"] not in limits.enabled_agents:
            raise Fault("TRUSTED_V1_SCOPE_MAP_REQUIRED")
        original = old/"originals"/row["owner"]/(row["id"]+Path(row["filename"]).suffix.lower())
        if not original.is_file() or original.is_symlink() or digest_file(original) != row["sha"]:
            raise Fault("V1_ORIGINAL_MISSING_OR_CHANGED")
    result = {"status": "MIGRATION_PLAN", "attachments": len(attachments), "old_root_untouched": True,
              "jobs": "Retain old jobs in old root; new extraction regenerates with V1.1 provenance/configuration."}
    if not apply:
        return result
    from .worker import ServiceLock
    lock = ServiceLock(old)
    try:
        new.mkdir(parents=True, exist_ok=True)
        backup = new/("v1-metadata-"+str(time.time_ns())+".sqlite3")
        with sqlite3.connect(old/"jobs.sqlite3") as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
        store = Store(new, limits)
        for row in attachments:
            original = old/"originals"/row["owner"]/(row["id"]+Path(row["filename"]).suffix.lower())
            registered = store.register(mapping[row["owner"]], row["id"], row["filename"], original,
                                        {**json.loads(row["info"]), "origin": "v1-migration"})
            with store.db() as db:
                db.execute("UPDATE files SET created=MIN(created,?) WHERE id=?", (timestamp(row["created"]), registered["file_id"]))
                reference = db.execute("SELECT source FROM attachments WHERE owner=? AND id=?", (row["owner"], row["id"])).fetchone()
                source_info = json.loads(reference[0])
                source_info["received_at"] = timestamp(row["created"])
                db.execute("UPDATE attachments SET created=?,source=? WHERE owner=? AND id=?",
                           (row["created"], json.dumps(source_info), row["owner"], row["id"]))
        result.update(status="MIGRATED", metadata_backup=str(backup))
    finally:
        lock.close()
    return result
