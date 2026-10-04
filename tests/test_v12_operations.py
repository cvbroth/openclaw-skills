"""Local install/migration and generated Docker/config plans; no live Docker assertions."""
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from nas_filetools.catalog import digest_file
from nas_filetools.contracts import Fault, Limits
from nas_filetools.management import register_source
from nas_filetools.operations import install, diagnose
from nas_filetools.operations_v12 import compose_text, host_path, migrate, plugin_configuration, profiles, runtime_config_permissions, validate_effective_compose
from nas_filetools.shared_workspace import mapped_store
from nas_filetools.store import Store
from test_v11 import finish


def config(tmp_path):
    return {"workspace_layout": "shared-v1.2", "data_root": str(tmp_path/"control"), "agents": ["chen"], "bindings": [],
            "limits": {"script_isolation": "development"}, "workspaces": {"chen": {"workspace": str(tmp_path/"workspace-chen")}}}


@pytest.mark.parametrize("allowed", [None, [], ["qqbot", "knowledge-broker"]])
def test_allowlist_preserves_effective_existing_plugins_in_plan(tmp_path, allowed):
    raw = config(tmp_path)
    document = {"plugins": {"entries": {"qqbot": {"enabled": True}, "knowledge-broker": {"enabled": True}}}}
    if allowed is not None:
        document["plugins"]["allow"] = allowed.copy()
    updated = plugin_configuration(document, raw, profiles(raw), "/extensions/nas-filetools")
    if allowed is None:
        assert "allow" not in updated["plugins"]
    else:
        assert updated["plugins"]["allow"] == (allowed+["nas-filetools"] if allowed else [])
    def effective(cfg, name):
        allow = cfg["plugins"].get("allow")
        return (not allow or name in allow) and cfg["plugins"]["entries"][name]["enabled"]
    assert all(effective(updated, name) == effective(document, name) for name in ("qqbot", "knowledge-broker"))
    assert document["plugins"].get("allow") == allowed


def test_two_container_mount_plan_paths_uid_and_no_full_state(tmp_path):
    raw = config(tmp_path)
    raw["workspaces"]["chen"] = {"workspace": "/home/node/.openclaw/workspace-chen"}
    target = {"uid": 1234, "gid": 1235, "service": "openclaw-gateway", "mounts": [{"Type": "bind", "RW": True,
        "Source": "/root/.openclaw", "Destination": "/home/node/.openclaw"}]}
    mapping = profiles(raw, target)
    assert mapping["chen"]["host_workspace"] == "/root/.openclaw/workspace-chen"
    assert host_path("/home/node/.openclaw/workspace-chen/filetools", target["mounts"]) == "/root/.openclaw/workspace-chen/filetools"
    text = compose_text(target, mapping, tmp_path/"release", tmp_path/"models", Limits())
    worker = text.split("  nas-filetools:")[1]
    assert '/root/.openclaw/workspace-chen/filetools:/workspaces/chen/filetools' in worker
    assert '/root/.openclaw:/home/node/.openclaw' not in worker and 'user: "1234:1235"' in worker
    assert "network_mode: none" in worker and "mem_limit: 4096m" in worker


def test_entries_roster_and_runtime_workspace_discovery(tmp_path, monkeypatch):
    raw = config(tmp_path)
    raw.pop("workspaces")
    document = {"agents": {"entries": {"chen": {"workspace": str(tmp_path/"chen")}}}}
    mapping = profiles(raw, document=document)
    updated = plugin_configuration(document, raw, mapping, "/extensions/nas-filetools")
    assert "filetools_register" in updated["agents"]["entries"]["chen"]["tools"]["alsoAllow"]
    assert "tools" not in document["agents"]["entries"]["chen"]
    calls = []
    def run(args, timeout):
        calls.append(args)
        return json.dumps([{"id": "chen", "workspace": "/home/node/.openclaw/workspace-chen"}])
    monkeypatch.setattr("nas_filetools.operations_v12.command", run)
    target = {"container": "fixture-only", "mounts": [{"Type": "bind", "RW": True,
        "Source": "/root/.openclaw", "Destination": "/home/node/.openclaw"}]}
    assert profiles(raw, target)["chen"]["host_workspace"] == "/root/.openclaw/workspace-chen"
    assert calls == [["docker", "exec", "fixture-only", "openclaw", "agents", "list", "--json"]]


@pytest.mark.skipif(sys.platform != "linux", reason="Actual Linux config UID/GID and mode")
def test_both_installed_runtime_configs_are_readable_by_container_owner(tmp_path):
    from nas_filetools.catalog import atomic_json
    for name in ("gateway.json", "worker.json"):
        atomic_json(tmp_path/name, {"version": "1.2.0"})
    runtime_config_permissions(tmp_path, os.getuid(), os.getgid())
    for name in ("gateway.json", "worker.json"):
        metadata = (tmp_path/name).stat()
        assert metadata.st_uid == os.getuid() and metadata.st_gid == os.getgid()
        assert metadata.st_mode & 0o777 == 0o640
        assert json.loads((tmp_path/name).read_text())["version"] == "1.2.0"


def test_effective_compose_rejects_inherited_broad_mount_and_changed_image(tmp_path):
    raw = config(tmp_path)
    mapping = profiles(raw)
    roots = ["/var/lib/nas-filetools", "/var/cache/nas-filetools", "/run/nas-filetools", "/etc/nas-filetools/config.json", mapping["chen"]["service_root"]]
    target = {"service": "gateway", "image": "existing-custom-image"}
    effective = {"services": {"gateway": {"image": target["image"]}, "nas-filetools": {"volumes": [{"type": "bind", "target": p} for p in roots]}}}
    validate_effective_compose(effective, target, mapping)
    effective["services"]["nas-filetools"]["volumes"].append({"type": "bind", "target": "/home/node/.openclaw"})
    with pytest.raises(Fault, match="UNEXPECTED_EFFECTIVE_WORKER_MOUNT"):
        validate_effective_compose(effective, target, mapping)
    effective["services"]["gateway"]["image"] = "replacement"
    with pytest.raises(Fault, match="EXISTING_GATEWAY_IMAGE_CHANGED"):
        validate_effective_compose(effective, target, mapping)


def test_local_shared_install_is_idempotent_and_mapping_errors(tmp_path):
    raw = config(tmp_path)
    path = tmp_path/"install.json"
    path.write_text(json.dumps(raw))
    assert install(path, local_only=True)["status"] == "INSTALL_PLAN"
    assert not Path(raw["workspaces"]["chen"]["workspace"]).exists()
    install(path, apply=True, local_only=True)
    marker = Path(raw["workspaces"]["chen"]["workspace"])/"private.txt"
    marker.write_text("keep")
    install(path, apply=True, local_only=True)
    assert marker.read_text() == "keep"
    report = diagnose(path, local_only=True)
    assert not report["runtime_verified"] and report["checks"]["runtime"] == "NOT_CHECKED_LOCAL_ONLY"
    raw["agents"].append("main")
    raw["workspaces"]["main"] = raw["workspaces"]["chen"]
    with pytest.raises(Fault, match="AGENT_WORKSPACE_OVERLAP"):
        profiles(raw)


def test_v11_migration_hashes_saved_independence_unknown_pause_and_repeat(tmp_path, identity):
    raw = config(tmp_path)
    configuration = tmp_path/"install.json"
    configuration.write_text(json.dumps(raw))
    old = Store(tmp_path/"v11", replace(Limits(), script_isolation="development"))
    source = tmp_path/"old.md"
    source.write_text("# Retained evidence")
    attachment = old.register(identity, "1"*32, source.name, source)
    job = finish(old, identity, old.submit(identity, attachment["attachment_id"], {"mode": "full"}))
    saved = old.save_result(identity, job["job_id"])
    other = {"user_id": "liang", "agent_id": "liang", "session_hash": "b"*64}
    old.register(other, "2"*32, source.name, source)
    old_hashes = {p.relative_to(old.root).as_posix(): digest_file(p) for p in old.root.rglob("*") if p.is_file() and not p.name.startswith("jobs.sqlite3") and p.name != "service.lock"}
    agent_map = tmp_path/"map.json"
    agent_map.write_text(json.dumps({"chen": "chen"}))
    result = migrate(configuration, old.root, agent_map, apply=True)
    assert result["status"] == "PARTIAL_MIGRATION" and result["paused_agents"] == ["liang"]
    new = mapped_store(profiles(raw)["chen"], "chen", Limits(), "gateway")
    assert new.inspect(identity, attachment["attachment_id"])["sha256"] == attachment["sha256"]
    read = new.saved_read(identity, saved["saved_id"], 0)
    assert "Retained" in read["text"] and Path(read["gateway_path"]).is_file()
    new.files(identity, "delete_original", file_id=attachment["file_id"])
    assert "Retained" in new.saved_read(identity, saved["saved_id"], 0)["text"]
    assert all(digest_file(old.root/name) == sha for name, sha in old_hashes.items())
    # No implicit merge/rename of main and chen.
    agent_map.write_text(json.dumps({"main": "chen"}))
    with pytest.raises(Fault, match="MIGRATION_CANNOT_MERGE"):
        migrate(configuration, old.root, agent_map)


def test_registration_rejects_change_during_snapshot_and_symlink(tmp_path, identity, monkeypatch):
    raw = config(tmp_path)
    store = mapped_store(profiles(raw)["chen"], "chen", Limits(), "gateway")
    path = Path(raw["workspaces"]["chen"]["workspace"])/"sample.txt"
    path.write_text("version A")
    import nas_filetools.management as module
    copy = module.snapshot_copy
    def unstable(source, target, *args):
        copied = copy(source, target, *args)
        source.write_text("version B")
        return copied
    monkeypatch.setattr(module, "snapshot_copy", unstable)
    with pytest.raises(Fault, match="ATTACHMENT_CHANGED|SOURCE_CHANGED"):
        register_source(store, identity, {"source_path": path.name})
    assert store.inspect(identity)["attachments"] == []
    monkeypatch.setattr(module, "snapshot_copy", copy)
    link = path.with_name("link.txt")
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("Creating real Windows symlinks needs OS privilege; Linux CI covers this")
    with pytest.raises(Fault, match="SOURCE_SYMLINK_DENIED"):
        register_source(store, identity, {"source_path": link.name})
