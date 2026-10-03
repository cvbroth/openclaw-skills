"""Filesystem-real rollback/preflight regressions with simulated Docker responses.

These tests do not establish Linux installation, ownership, container or Gateway health.
"""
import hashlib
import json

import pytest

from nas_filetools import operations
from nas_filetools.contracts import Fault


def test_gateway_preflight_uses_existing_custom_compose_and_rejects_single_file_mount(tmp_path, monkeypatch):
    state = tmp_path/"gateway"
    state.mkdir()
    config = state/"openclaw.json"
    config.write_text(json.dumps({"agents": {"list": [{"id": "chen"}]}, "models": {"keep": True}}))
    compose = tmp_path/"custom.yaml"
    compose.write_text("services: {}")
    mount = {"Source": str(state), "Destination": "/state", "Type": "bind", "RW": True}
    def docker(args, *_args):
        if args[1] == "ps":
            return "openclaw-custom-gateway-1\nimmich-server\n"
        if args[1] == "inspect":
            return json.dumps([{"Config": {"Labels": {"com.docker.compose.project.config_files": str(compose),
                       "com.docker.compose.project": "custom", "com.docker.compose.service": "gateway"}}, "Mounts": [mount]}])
        return "2026.9.4 (3a9d69d)" if "--version" in args else "1000"
    monkeypatch.setattr(operations, "command", docker)
    result = operations.gateway({"agents": ["chen"]})
    assert result["compose"] == [str(compose)] and result["project"] == "custom"
    assert result["service"] == "gateway" and json.loads(config.read_text())["models"]["keep"]
    mount.update(Source=str(config), Destination="/state/openclaw.json")
    with pytest.raises(Fault, match="PERSISTENT_GATEWAY_CONFIG_MOUNT_REQUIRED"):
        operations.gateway({"agents": ["chen"], "gateway_config": str(config)})


def test_rollback_restores_files_preserves_data_and_rejects_later_config_edits(tmp_path, monkeypatch):
    original = {"models": {"keep": True}, "plugins": {"entries": {"knowledge": {"enabled": True}}}}
    current = {**original, "filetools_added": True}
    config = tmp_path/"openclaw.json"
    config.write_text(json.dumps(current))
    backup = tmp_path/"backup.json"
    backup.write_text(json.dumps(original))
    data = tmp_path/"data"
    data.mkdir()
    (data/"preserve.txt").write_text("new saved output")
    plugin = tmp_path/"extensions"/"nas-filetools"
    plugin.mkdir(parents=True)
    (plugin/"openclaw.plugin.json").write_text(json.dumps({"id": "nas-filetools"}))
    (plugin/"version").write_text("1.1")
    plugin_backup = tmp_path/"old-plugin"
    plugin_backup.mkdir()
    (plugin_backup/"version").write_text("1.0")
    record = tmp_path/"rollback.json"
    record.write_text(json.dumps({"config": str(config), "backup": str(backup), "new_data_preserved": str(data),
        "installed_sha256": hashlib.sha256(json.dumps(current, ensure_ascii=False).encode()).hexdigest(),
        "base_compose": ["custom.yaml"], "service": "gateway", "project": "custom", "override": "added.yaml",
        "plugin_path": str(plugin), "plugin_backup": str(plugin_backup), "uid": 1000, "gid": 1000}))
    calls = []
    def docker(args, *_args):
        calls.append(args)
        return json.dumps({"services": {"gateway": {}, "nas-filetools": {}, "immich": {}}})
    monkeypatch.setattr(operations, "command", docker)
    monkeypatch.setattr(operations, "own_tree", lambda *_args: None)
    assert operations.rollback(record)["status"] == "ROLLBACK_PLAN" and not calls
    config.write_text(json.dumps({**current, "later_operator_change": True}))
    with pytest.raises(Fault, match="ROLLBACK_CONFIG_CHANGED"):
        operations.rollback(record, apply=True)
    assert not calls and (plugin/"version").read_text() == "1.1"
    config.write_text(json.dumps(current))
    result = operations.rollback(record, apply=True)
    assert result["status"] == "ROLLED_BACK" and json.loads(config.read_text()) == original
    assert (plugin/"version").read_text() == "1.0" and (data/"preserve.txt").read_text() == "new saved output"
    assert calls[-1][-2:] == ["gateway", "nas-filetools"] and "immich" not in calls[-1]
