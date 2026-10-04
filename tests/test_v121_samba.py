"""REAL local smbd/smbclient/ACL/bind tests in an explicitly enabled root container.

Systemctl calls are recorded instead of booting systemd: enable/reboot integration
remains production acceptance. Passwords are ephemeral and never printed.
"""
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import pytest

from nas_filetools.contracts import Fault
from nas_filetools.samba_results import ACL_MODE, OWNER_MODE, results, binding_matches, permission_record

pytestmark = pytest.mark.skipif(sys.platform != "linux" or os.getenv("FILETOOLS_SAMBA_TEST") != "1",
                               reason="Opt-in isolated root Docker Samba/ACL/bind integration")


@pytest.mark.parametrize("mode", [ACL_MODE, OWNER_MODE])
def test_actual_accounts_new_old_saved_bind_idempotence_rollback(tmp_path, monkeypatch, mode):
    import pwd
    assert (pwd.getpwnam("chen").pw_uid, pwd.getpwnam("chen").pw_gid) == (1000, 1000)
    import nas_filetools.samba_results as module
    original_command, systemd_calls = module.command, []
    fail_unmount = {"remaining": 0}
    def run(args, timeout=60):
        if args[0] == "systemctl":
            systemd_calls.append(args)
            return ""  # Explicit simulation of systemd service-manager calls only.
        if args[0] == "umount" and fail_unmount["remaining"]:
            fail_unmount["remaining"] -= 1
            raise Fault("TEST_BUSY_MOUNT")
        return original_command(args, timeout)
    monkeypatch.setattr(module, "command", run)
    os.chmod(tmp_path, 0o755)
    # pytest's parent is private by default; this disposable fixture has no secrets.
    os.chmod(tmp_path.parent, 0o755)
    os.chmod(tmp_path.parent.parent, 0o755)
    units = tmp_path/"units"
    units.mkdir()
    originals, original_permissions, writers = {}, {}, {}
    shares = []
    for agent, user, name in (("chen", "chen", "Chen-Results"), ("liang", "liang", "Liang-Results"), ("ziling", "azl", "AZL-Results")):
        saved = tmp_path/agent/"filetools"/"saved"
        saved.mkdir(parents=True)
        writer = pwd.getpwnam(user if mode == OWNER_MODE else "filetools")
        writers[agent] = writer.pw_name
        os.chown(saved.parent, writer.pw_uid, writer.pw_gid)
        os.chown(saved.parent.parent, writer.pw_uid, writer.pw_gid)
        old = saved/"old.md"
        old.write_text("Saved evidence "+agent)
        for path in (saved, old):
            os.chown(path, writer.pw_uid, writer.pw_gid)
            os.chmod(path, 0o700 if path.is_dir() else (0o600 if mode == OWNER_MODE else 0o440))
        if mode == OWNER_MODE:
            # Preexisting, redundant named-owner + custom group ACLs are not ours.
            # The owner entry must not become a reader policy in the publisher.
            original_command(["setfacl", "-m", f"u:{writer.pw_uid}:r-x,g:24003:r--", str(saved)])
            original_command(["setfacl", "-m", f"d:u:{writer.pw_uid}:r-x,d:g:24003:r--", str(saved)])
            original_command(["setfacl", "-m", "g:24003:r--", str(old)])
        original_permissions[agent] = [permission_record(p) for p in (saved, old)]
        if mode == OWNER_MODE:
            from nas_filetools.saved_permissions import set_read_acl, readers
            set_read_acl(saved, [writer.pw_uid])
            assert readers(saved) == []
            assert permission_record(saved) == original_permissions[agent][0]
        originals[agent] = old.read_bytes()
        shares.append({"agent": agent, "samba_user": user, "name": name, "saved": str(saved)})
    legacy = tmp_path/"legacy-personal"
    legacy.mkdir()
    conf = tmp_path/"smb.conf"
    conf.write_text(f"[global]\nworkgroup = WORKGROUP\nserver role = standalone server\n"
                    "interfaces = 127.0.0.1\nbind interfaces only = yes\nmap to guest = Never\n"
                    "write list = chen\nadmin users = chen\nforce user = filetools\nforce group = filetools\n"
                    f"[Legacy]\npath = {legacy}\nread only = yes\nvalid users = chen\n")
    previous = conf.read_bytes()
    cfg = tmp_path/"results.json"
    cfg.write_text(json.dumps({"state_dir": str(tmp_path/"admin"), "results_root": str(tmp_path/"results"),
                               "smb_conf": str(conf), "unit_dir": str(units), "shares": shares}))
    planned = results(cfg)
    assert planned["status"] == "RESULTS_PLAN"
    assert all(s["permission_mode"] == mode for s in planned["shares"])
    assert not (tmp_path/"admin").exists() and conf.read_bytes() == previous
    applied = results(cfg, "apply", True)
    assert applied["status"] == "RESULTS_APPLIED"
    assert results(cfg, "apply", True)["status"] == "RESULTS_ALREADY_APPLIED"
    assert all(binding_matches(s) for s in planned["shares"])
    diagnosis = results(cfg, "diagnose")
    assert diagnosis["issues"] == []
    record_path = tmp_path/"admin"/"results-rollback.json"
    record = json.loads(record_path.read_text())
    assert all(s["permission_mode"] == mode for s in record["shares"])
    if mode == OWNER_MODE:
        assert record["permissions"] == []
        assert diagnosis["checks"]["chen"]["permission_note"] == "Samba 访问只读，服务器本地所有者仍可写。"
        for share in shares:
            assert [permission_record(p) for p in (Path(share["saved"]), Path(share["saved"])/"old.md")] == original_permissions[share["agent"]]
            original_command(["runuser", "-u", share["samba_user"], "--", "test", "-w", share["saved"]])
    else:
        assert diagnosis["checks"]["chen"]["unix_reader_access"] == "READ_TRAVERSE_NO_WRITE"
        # Earlier V1.2.1 records have no explicit mode and remain ACL-compatible.
        for share in record["shares"]:
            share.pop("permission_mode")
        record_path.write_text(json.dumps(record))
        assert results(cfg, "apply", True)["status"] == "RESULTS_ALREADY_APPLIED"
    # Recorded identity/mode drift must not silently switch permission strategies.
    original_stat = Path(shares[0]["saved"]).stat()
    os.chown(shares[0]["saved"], 24003, -1)
    try:
        assert "RESULTS_IDENTITY_OR_PERMISSION_MODE_CHANGED" in results(cfg, "diagnose")["issues"]
        for action in ("apply", "rollback"):
            with pytest.raises(Fault, match="RESULTS_IDENTITY_OR_PERMISSION_MODE_CHANGED"):
                results(cfg, action, True)
    finally:
        os.chown(shares[0]["saved"], original_stat.st_uid, -1)
    for parameter in ("write list", "admin users", "force user", "force group"):
        assert original_command(["testparm", "-s", str(conf), "--section-name=Chen-Results", "--parameter-name="+parameter]).strip() == ""
    for parameter, expected in (("read only", "yes"), ("guest ok", "no"), ("valid users", "chen")):
        assert original_command(["testparm", "-s", str(conf), "--section-name=Chen-Results", "--parameter-name="+parameter]).strip().lower() == expected
    assert diagnosis["smb_protocol_acceptance"] == "NOT_RUN"
    assert diagnosis["checks"]["chen"]["samba_policy"] == "READ_ONLY_CONFIGURED"
    fragment_path = tmp_path/"admin"/"results.conf"
    original_fragment = fragment_path.read_text()
    fragment_path.write_text(original_fragment.replace("read only = yes", "read only = no"))
    try:
        assert "RESULTS_SAMBA_POLICY_CHANGED:chen" in results(cfg, "diagnose")["issues"]
        with pytest.raises(Fault, match="RESULTS_INSTALLATION_DRIFT"):
            results(cfg, "apply", True)
    finally:
        fragment_path.write_text(original_fragment)
    assert all((units/s["unit"]).exists() for s in planned["shares"])
    assert len([c for c in systemd_calls if c[1] == "enable"]) == 3
    credentials = {}
    for user in ("chen", "liang", "azl"):
        password = secrets.token_urlsafe(18)
        auth = tmp_path/(".auth-"+user)
        auth.write_text("username = "+user+"\npassword = "+password+"\n")
        os.chmod(auth, 0o600)
        credentials[user] = auth
        configured = subprocess.run(["smbpasswd", "-s", "-a", user], input=password+"\n"+password+"\n",
                                    capture_output=True, text=True)
        assert configured.returncode == 0
    daemon = subprocess.Popen(["smbd", "--foreground", "--no-process-group", "-s", str(conf)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def smb(user, share, instruction):
        # Only test credentials; never use this pattern with real credentials in logs.
        return subprocess.run(["smbclient", "//127.0.0.1/"+share, "-A", str(credentials[user]), "-c", instruction],
                              text=True, capture_output=True, timeout=20)
    try:
        for _ in range(50):
            if smb("chen", "Chen-Results", "ls").returncode == 0:
                break
            time.sleep(0.1)
        assert daemon.poll() is None
        for share in shares:
            user, name, agent = share["samba_user"], share["name"], share["agent"]
            downloaded = tmp_path/(agent+"-download.md")
            assert smb(user, name, f"get old.md {downloaded}").returncode == 0
            assert downloaded.read_bytes() == originals[agent]
            for operation in (f"put {downloaded} overwrite.md", f"put {downloaded} old.md", "del old.md", "rename old.md moved.md"):
                denied = smb(user, name, operation)
                assert "NT_STATUS_ACCESS_DENIED" in denied.stdout+denied.stderr, operation
            assert not (Path(share["saved"])/"overwrite.md").exists()
            assert not (Path(share["saved"])/"moved.md").exists()
            assert (Path(share["saved"])/"old.md").read_bytes() == originals[agent]
            for other in credentials:
                if other != user:
                    response = smb(other, name, "ls")
                    assert response.returncode != 0 and "NT_STATUS_ACCESS_DENIED" in response.stdout+response.stderr
            # Actual writer UID publishes restrictive files + atomically replaces JSON.
            # This is a real filesystem publisher check, not a mocked save engine.
            script = ("import os;from pathlib import Path;from nas_filetools.catalog import atomic_json;"
                      "from nas_filetools.saved_permissions import publish_saved_permissions;"
                      f"saved=Path({share['saved']!r});p=saved/'text'/'new-version';p.mkdir(parents=True);"
                      "f=p/'content.md';f.write_text('New result');os.chmod(f,0o440);"
                      "atomic_json(p/'saved.json',{'version':1});publish_saved_permissions(saved,p);"
                      "atomic_json(p/'saved.json',{'version':2});publish_saved_permissions(saved,p)")
            writer = subprocess.run(["runuser", "-u", writers[agent], "--", sys.executable, "-c", script],
                                    text=True, capture_output=True)
            assert writer.returncode == 0, writer.stderr
            new_download = tmp_path/(agent+"-new.md")
            assert smb(user, name, f"get text/new-version/content.md {new_download}").returncode == 0
            assert new_download.read_text() == "New result"
            metadata = tmp_path/(agent+"-metadata.json")
            assert smb(user, name, f"get text/new-version/saved.json {metadata}").returncode == 0
            assert json.loads(metadata.read_text())["version"] == 2
        # Full core registration -> actual text worker -> save -> immediate SMB read
        # as the same nonroot Gateway/Worker UID, with new category/version dirs.
        workspace = Path(shares[0]["saved"]).parent.parent
        core = '''import json,time,sys
from pathlib import Path
from nas_filetools.contracts import Limits
from nas_filetools.store import Store
from nas_filetools.management import register_source
from nas_filetools.service import dispatch
from nas_filetools.worker import Supervisor
w=Path(sys.argv[1]);(w/'business.txt').write_text('Actual core saved evidence')
s=Store(w/'filetools',Limits(enabled_agents=('chen',),workspace_mode=True,gateway_workspace=str(w),source_roots={'workspace':{'path':str(w),'kind':'workspace'}},script_isolation='development'))
i={'agent_id':'chen','user_id':'chen','session_hash':'a'*64}
r=register_source(s,i,{'source_path':'business.txt'})
j=dispatch(s,i,'extract',{'attachment_id':r['attachment_id'],'config':{'mode':'full'}})
worker=Supervisor(s)
try:
 for _ in range(400):
  worker.tick();state=s.status(i,j['job_id'])
  if state['status'] not in ('QUEUED','RUNNING'):break
  time.sleep(.025)
 assert state['status']=='SUCCEEDED',state
 saved=s.save_result(i,j['job_id'])
 with s.db() as db:row=db.execute('SELECT path FROM saved WHERE id=?',(saved['saved_id'],)).fetchone()
 print(json.dumps({'relative':str(Path(row[0]).relative_to('saved')),'artifact_file':state['artifacts'][0]['file'],'saved':saved}))
finally:worker.close()
'''
        completed = subprocess.run(["runuser", "-u", writers["chen"], "--", sys.executable, "-c", core, str(workspace)],
                                   capture_output=True, text=True, timeout=30)
        assert completed.returncode == 0, completed.stderr
        published = json.loads(completed.stdout)
        retrieved = tmp_path/"core-saved.md"
        assert smb("chen", "Chen-Results", f"get {published['relative']}/{published['artifact_file']} {retrieved}").returncode == 0
        assert "Actual core saved evidence" in retrieved.read_text()
        # Same-UID reapply also accepts old custom ACLs and new saved versions.
        assert results(cfg, "apply", True)["status"] == "RESULTS_ALREADY_APPLIED"
        before_rollback = {str(p): permission_record(p) for share in shares for p in module.walk(share["saved"])}
        assert all(s["permission_mode"] == mode for s in results(cfg, "rollback")["shares"])
        # Later admin edits are protected; no rollback overwrites an unrelated share edit.
        with conf.open("a") as output:
            output.write("\n# Later administrator change\n")
        with pytest.raises(Fault, match="SAMBA_CONFIG_CHANGED_AFTER_APPLY"):
            results(cfg, "rollback", True)
        conf.write_bytes(previous + ("\n[global]\n"+module.MARKER+"\ninclude = "+str(tmp_path/"admin"/"results.conf")+"\n").encode())
        fragment = tmp_path/"admin"/"results.conf"
        fragment_before = fragment.read_bytes()
        fragment.write_bytes(fragment_before+b"\n# Later fragment edit\n")
        with pytest.raises(Fault, match="RESULTS_FRAGMENT_CHANGED"):
            results(cfg, "rollback", True)
        fragment.write_bytes(fragment_before)
        fail_unmount["remaining"] = 1
        with pytest.raises(Fault, match="TEST_BUSY_MOUNT"):
            results(cfg, "rollback", True)
        assert conf.read_bytes() == previous
        assert all(binding_matches(s) for s in planned["shares"])
        # Our own partial config restoration is distinguishable from unrelated edits.
        assert results(cfg, "rollback", True)["saved_data_preserved"]
        assert conf.read_bytes() == previous
        assert results(cfg, "rollback", True)["status"] == "RESULTS_ALREADY_ROLLED_BACK"
        assert not (tmp_path/"results").exists()
        assert not any(units.iterdir())
        for share in shares:
            assert (Path(share["saved"])/"old.md").read_bytes() == originals[share["agent"]]
            assert (Path(share["saved"])/"text"/"new-version"/"content.md").read_text() == "New result"
            if mode == OWNER_MODE:
                assert {str(p): permission_record(p) for p in module.walk(share["saved"])} == {
                    k: v for k, v in before_rollback.items() if Path(k).is_relative_to(Path(share["saved"]))}
            else:
                assert [permission_record(p) for p in (Path(share["saved"]), Path(share["saved"])/"old.md")] == original_permissions[share["agent"]]
    finally:
        daemon.terminate()
        daemon.wait(timeout=10)
        for auth in credentials.values():
            auth.unlink(missing_ok=True)


@pytest.mark.parametrize("mode", [ACL_MODE, OWNER_MODE])
def test_apply_failure_restores_acl_and_saved_data(tmp_path, monkeypatch, mode):
    import pwd
    import nas_filetools.samba_results as module
    saved = tmp_path/"agent"/"filetools"/"saved"
    saved.mkdir(parents=True)
    old = saved/"old.txt"
    old.write_text("Retained")
    writer = pwd.getpwnam("chen" if mode == OWNER_MODE else "filetools")
    os.chown(saved, writer.pw_uid, writer.pw_gid)
    os.chown(old, writer.pw_uid, writer.pw_gid)
    units = tmp_path/"units"
    units.mkdir()
    conf = tmp_path/"smb.conf"
    conf.write_text("[global]\nworkgroup=WORKGROUP\n")
    cfg = tmp_path/"config.json"
    cfg.write_text(json.dumps({"state_dir": str(tmp_path/"admin"), "results_root": str(tmp_path/"results"),
                               "smb_conf": str(conf), "unit_dir": str(units), "shares": [
        {"agent": "chen", "samba_user": "chen", "name": "Chen-Results", "saved": str(saved)}]}))
    previous = conf.read_bytes()
    original = module.command
    if mode == OWNER_MODE:
        original(["setfacl", "-m", "g:24003:r--", str(saved)])
        original(["setfacl", "-m", "d:g:24003:r--", str(saved)])
        original(["setfacl", "-m", "g:24003:r--", str(old)])
    prior_permissions = [permission_record(p) for p in (saved, old)]
    def run(args, timeout=60):
        if args[0] == "systemctl":
            return ""
        if args[0] == "mount":
            raise Fault("TEST_INJECTED_MOUNT_FAILURE")
        return original(args, timeout)
    monkeypatch.setattr(module, "command", run)
    with pytest.raises(Fault, match="TEST_INJECTED_MOUNT_FAILURE"):
        results(cfg, "apply", True)
    assert old.read_text() == "Retained" and conf.read_bytes() == previous
    assert not (tmp_path/"results").exists()
    assert not any(units.iterdir())
    assert [permission_record(p) for p in (saved, old)] == prior_permissions
