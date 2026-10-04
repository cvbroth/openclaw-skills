"""Incremental V1.2.1 core checks; Samba/root Docker are opt-in actual tests."""
import os
import sys
import json

import pytest

from nas_filetools.contracts import Fault
from nas_filetools.management import register_source
from nas_filetools.operations_v12 import host_path, profiles
from test_v12 import mapped, source  # noqa: F401,F811 -- shared fixture
from test_v12_operations import config


@pytest.mark.skipif(sys.platform != "linux", reason="Actual Unix marker modes/owner, command failure injection")
@pytest.mark.parametrize("mask", [0o022, 0o077])
def test_diagnose_failure_always_removes_own_marker(tmp_path, monkeypatch, mask):
    import nas_filetools.operations_v12 as module
    raw = config(tmp_path)
    raw["workspaces"]["chen"]["workspace"] = "/gateway/chen"
    cfg = tmp_path/"install.json"
    cfg.write_text(json.dumps(raw))
    document = tmp_path/"openclaw.json"
    document.write_text("{}")
    workspace = tmp_path/"chen"
    target = {"uid": os.getuid(), "gid": os.getgid(), "container": "test-gateway", "config": str(document),
              "project": "fixture", "mounts": [{"Type": "bind", "RW": True, "Destination": "/gateway/chen", "Source": str(workspace)}]}
    monkeypatch.setattr(module, "gateway", lambda _: target)
    def fail(args, timeout=60):
        marker = next((workspace/"filetools").glob(".diagnostic-*"))
        assert marker.stat().st_mode & 0o777 == 0o660
        assert marker.stat().st_uid == os.getuid()
        assert args[2:4] == ["--user", f"{os.getuid()}:{os.getgid()}"]
        raise Fault("TEST_CONTAINER_UNAVAILABLE")
    monkeypatch.setattr(module, "command", fail)
    previous = os.umask(mask)
    try:
        assert module.diagnose(cfg)["issues"] == ["TEST_CONTAINER_UNAVAILABLE"]
    finally:
        os.umask(previous)
    assert not list((workspace/"filetools").glob(".diagnostic-*"))


def test_readonly_source_longest_mount_and_writable_workspace(tmp_path):
    mounts = [{"Type": "bind", "RW": True, "Source": "/root/.openclaw", "Destination": "/home/node/.openclaw"},
              {"Type": "bind", "RW": False, "Source": "/srv/storage/users/chen/Incoming", "Destination": "/nas/chen"},
              {"Type": "bind", "RW": True, "Source": "/nested-main", "Destination": "/home/node/.openclaw/workspace"}]
    assert host_path("/nas/chen/file.pdf", mounts, False) == "/srv/storage/users/chen/Incoming/file.pdf"
    assert host_path("/home/node/.openclaw/workspace/filetools", mounts) == "/nested-main/filetools"
    with pytest.raises(Fault, match="WORKSPACE_BIND_READONLY"):
        host_path("/nas/chen", mounts)
    for path in ("/nas/chen/../outside", "relative"):
        with pytest.raises(Fault, match="INVALID_MAPPED_PATH"):
            host_path(path, mounts, False)
    raw = config(tmp_path)
    raw["workspaces"]["chen"] = {"workspace": "/home/node/.openclaw/workspace-chen", "source_roots": {
        "incoming": {"path": "/nas/chen", "kind": "nas"}}}
    result = profiles(raw, {"mounts": mounts})
    assert result["chen"]["source_roots"]["incoming"]["host_path"] == "/srv/storage/users/chen/Incoming"


def test_catalog_more_than_32_dedup_select_and_system_exclusion(mapped, identity):  # noqa: F811
    store, file, _ = source(mapped, identity)
    ids = []
    for number in range(45):
        path = file.with_name(f"business-{number}.txt")
        path.write_text(f"Business record {number}")
        result = register_source(store, identity, {"source_path": path.name, "select": False})
        assert not result["selected"] and "attachment_id" not in result
        repeat = register_source(store, identity, {"source_path": path.name, "select": False})
        assert repeat["file_id"] == result["file_id"] and repeat["reused"]
        ids.append(result["file_id"])
    assert len(set(ids)) == 45
    page = store.files(identity, "list", area="snapshots")
    assert set(ids).issubset({item["file_id"] for item in page["items"]}) and not page["truncated"]
    assert any(event["source_relative_path"] == "business-0.txt" for item in page["items"] for event in item["uploads"])
    assert len(store.inspect(identity)["attachments"]) == 1
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM files WHERE mode='snapshot'").fetchone()[0] == 46
    assert store.files(identity, "select", file_id=ids[-1])["file_id"] == ids[-1]
    for name in ("SOUL.md", ".env", "node_modules/config.txt", "skills/SKILL.md", "memory/history.txt"):
        path = file.parent/name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text("system content")
        with pytest.raises(Fault, match="SYSTEM_FILE_EXCLUDED"):
            register_source(store, identity, {"source_path": name, "select": False})
    for number in range(30):
        store.files(identity, "select", file_id=ids[number])
    with pytest.raises(Fault, match="SESSION_REFERENCE_LIMIT"):
        store.files(identity, "select", file_id=ids[30])
    # Catalog remains usable when the processing selection is full.
    extra = file.with_name("extra.txt")
    extra.write_text("Additional catalog file")
    register_source(store, identity, {"source_path": extra.name, "select": False})


def test_catalog_list_byte_budget_continuation_does_not_drop_ids(mapped, identity):  # noqa: F811
    from dataclasses import replace
    store, file, _ = source(mapped, identity)
    for number in range(8):
        path = file.with_name(f"record-{number}.txt")
        path.write_text(f"Different contents {number}")
        register_source(store, identity, {"source_path": path.name, "select": False})
    store.limits = replace(store.limits, max_response_bytes=2048)
    items, offset = [], 0
    for _ in range(20):
        result = store.files(identity, "list", area="snapshots", offset=offset)
        items.extend(result["items"])
        if not result["truncated"]:
            break
        assert result["next_offset"] > offset
        offset = result["next_offset"]
    assert len(items) == len({item["file_id"] for item in items}) == 9


def test_uploading_rejected_even_if_stable_and_complete_move_accepted(mapped, identity):  # noqa: F811
    store, file, _ = source(mapped, identity)
    uploading = file.parent/"Uploading"/"large.txt"
    uploading.parent.mkdir()
    uploading.write_text("Stable bytes alone do not prove completion")
    with pytest.raises(Fault, match="SOURCE_INCOMPLETE"):
        register_source(store, identity, {"source_path": "Uploading/large.txt"})
    incoming = file.parent/"Incoming"
    incoming.mkdir()
    uploading.rename(incoming/uploading.name)
    assert register_source(store, identity, {"source_path": "Incoming/large.txt"})["status"] == "REGISTERED"


@pytest.mark.skipif(sys.platform != "linux", reason="Actual Linux xattr ACL test")
def test_saved_atomic_json_and_0440_mask_repair(tmp_path):
    from nas_filetools.catalog import atomic_json
    from nas_filetools.saved_permissions import readers, set_read_acl, publish_saved_permissions, acl_bytes, ACCESS
    import struct
    saved = tmp_path/"saved"
    saved.mkdir()
    reader = 24001 if os.getuid() != 24001 else 24002
    set_read_acl(saved, [reader])
    assert readers(saved) == [reader]
    version = saved/"documents"/"new-version"
    version.mkdir(parents=True)
    file = version/"content.md"
    file.write_text("Actual ACL test")
    os.chmod(file, 0o440)
    atomic_json(version/"saved.json", {"first": True})
    publish_saved_permissions(saved, version)
    atomic_json(version/"saved.json", {"second": True})
    publish_saved_permissions(saved, version)
    for path in (file, version/"saved.json"):
        entries = list(struct.iter_unpack("<HHI", acl_bytes(path, ACCESS)[4:]))
        assert (2, 4, reader) in entries and (16, 4, 0xffffffff) in entries
        assert path.stat().st_uid == os.getuid()
