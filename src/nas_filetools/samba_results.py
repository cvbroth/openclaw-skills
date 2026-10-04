"""Optional administrator-only Samba entry: plan/apply/diagnose/rollback.

Touches only explicit saved trees, our fragment, our mount units and one include
line. Existing shares, accounts, tunnels, Gateway config and business data remain.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import sys
from contextlib import ExitStack
from pathlib import Path

from .catalog import atomic_json, timestamp
from .contracts import AGENT_USERS, Fault, strict
from .operations import command
from .registry_lock import RegistryLock
from .saved_permissions import ACCESS, DEFAULT, acl_bytes, readers, set_read_acl

MARKER = "# NAS FileTools saved results (managed V1.2.1)"


def path_value(value):
    # systemd/Samba have different escaping rules: keep the administrative paths
    # unambiguous instead of accepting shell/config injection or symlink aliases.
    if not isinstance(value, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value) or ".." in Path(value).parts:
        raise Fault("INVALID_SHARE_PATH")
    path = Path(value)
    if str(path) == "/" or any(p.is_symlink() for p in [path, *path.parents]):
        raise Fault("UNSAFE_SHARE_PATH")
    return path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def settings(config):
    if sys.platform != "linux":
        raise Fault("LINUX_SAMBA_ADMIN_REQUIRED", "Generate and verify Samba permissions on Linux; never infer NAS UIDs from Windows.")
    import pwd
    raw = json.loads(Path(config).read_text(encoding="utf-8"))
    strict(raw, ("state_dir", "results_root", "smb_conf", "unit_dir", "shares"), ("state_dir", "results_root", "smb_conf", "shares"))
    state = path_value(raw["state_dir"])
    root = path_value(raw["results_root"])
    conf = path_value(raw["smb_conf"])
    units = path_value(raw.get("unit_dir", "/etc/systemd/system"))
    if not conf.is_file() or not isinstance(raw["shares"], list) or not 1 <= len(raw["shares"]) <= 4:
        raise Fault("INVALID_RESULTS_SHARES")
    shares, seen = [], set()
    for item in raw["shares"]:
        strict(item, ("agent", "samba_user", "name", "saved"), ("agent", "samba_user", "name", "saved"))
        if item["agent"] not in AGENT_USERS or item["samba_user"] != AGENT_USERS[item["agent"]] or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,63}", item["name"]):
            raise Fault("INVALID_SHARE_IDENTITY")
        saved = path_value(item["saved"])
        if saved.parts[-2:] != ("filetools", "saved") or not saved.is_dir():
            raise Fault("SAVED_DIRECTORY_REQUIRED", "Install/diagnose the real Agent workspace first; do not mount a missing saved directory.")
        # Existing accounts only; no credentials are read or supplied to this CLI.
        try:
            account = pwd.getpwnam(item["samba_user"])
        except KeyError:
            raise Fault("EXISTING_SAMBA_UNIX_ACCOUNT_REQUIRED") from None
        if account.pw_uid == 0 or account.pw_uid == saved.stat().st_uid:
            raise Fault("SHARE_READER_IS_WRITER", "Samba account must differ from the verified Gateway/Worker owner.")
        destination = root/(item["samba_user"]+"-main" if item["agent"] == "main" else item["samba_user"])
        if any(key in seen for key in (item["name"], str(saved), str(destination))):
            raise Fault("DUPLICATE_RESULTS_SHARE")
        seen.update((item["name"], str(saved), str(destination)))
        unit = command(["systemd-escape", "--path", "--suffix=mount", str(destination)]).strip()
        shares.append({**item, "saved": str(saved), "entry": str(destination), "uid": account.pw_uid,
                       "gid": account.pw_gid, "writer_uid": saved.stat().st_uid, "unit": unit})
    paths = [state, root, conf, units]
    if state == root or any(state.is_relative_to(Path(s["saved"])) or root.is_relative_to(Path(s["saved"])) or
                            Path(s["saved"]).is_relative_to(root) for s in shares):
        raise Fault("SHARE_PATH_OVERLAP")
    return raw, paths, shares


def fragment(shares):
    return MARKER+"\n"+"\n".join(
        f"[{s['name']}]\n    path = {s['entry']}\n    valid users = {s['samba_user']}\n"
        "    read only = yes\n    guest ok = no\n    browseable = yes\n"
        "    write list =\n    admin users =\n    force user =\n    force group =\n"
        "    veto files = /.saving-*/.migration-*/*.tmp-*/\n    delete veto files = no\n" for s in shares)


def unit_text(share):
    return ("[Unit]\nDescription=NAS FileTools saved-only results\n"
            f"RequiresMountsFor={share['saved']}\nBefore=smbd.service\n\n[Mount]\n"
            f"What={share['saved']}\nWhere={share['entry']}\nType=none\nOptions=bind\n\n"
            "[Install]\nWantedBy=local-fs.target\n")


def walk(saved):
    result = [Path(saved), *Path(saved).rglob("*")]
    if len(result) > 100000:
        raise Fault("SAVED_ACL_PLAN_LIMIT")
    if any(p.is_symlink() or not (p.is_dir() or p.is_file()) for p in result):
        raise Fault("SAVED_SYMLINK_DENIED")
    return result


def permission_record(path):
    return {"path": str(path), "mode": path.stat().st_mode & 0o777,
            "acl": {name: base64.b64encode(value).decode() if (value := acl_bytes(path, name)) else None
                    for name in (ACCESS, DEFAULT) if name != DEFAULT or path.is_dir()}}


def restore_permissions(record):
    path = Path(record["path"])
    if not path.exists():
        return
    if path.is_symlink():
        raise Fault("SAVED_SYMLINK_DENIED")
    os.chmod(path, record["mode"])
    for name, value in record["acl"].items():
        if value:
            os.setxattr(path, name, base64.b64decode(value), follow_symlinks=False)
        elif acl_bytes(path, name):
            os.removexattr(path, name, follow_symlinks=False)


def binding_matches(share):
    target = Path(share["entry"])
    # Same inode/device validates the live bind independently of escaped findmnt
    # source strings (which often include a device prefix + bracketed subpath).
    return mounted(target) and target.stat().st_ino == Path(share["saved"]).stat().st_ino and target.stat().st_dev == Path(share["saved"]).stat().st_dev


def mounted(path):
    # os.path.ismount cannot recognize a same-filesystem bind mount on Linux.
    return any(line.split()[4] == str(path) for line in Path("/proc/self/mountinfo").read_text().splitlines())


def results(config, action="plan", apply=False):
    raw, paths, shares = settings(config)
    with ExitStack() as locks:
        if apply and action in ("apply", "rollback"):
            # Serialize with the existing manager's save operation, no second lock
            # scheme. A bare saved-only test fixture has no live registry/manager.
            for share in sorted(shares, key=lambda s: s["saved"]):
                lock = Path(share["saved"]).parent/".registry.lock"
                if lock.exists():
                    locks.enter_context(RegistryLock(lock))
        return _results(raw, paths, shares, action, apply)


def _results(raw, paths, shares, action, apply):
    state, root, conf, units = paths
    record_path = state/"results-rollback.json"
    include = f"\n[global]\n{MARKER}\ninclude = {state}/results.conf\n"
    plan = {"status": "RESULTS_PLAN", "shares": shares, "fragment": fragment(shares),
            "mount_units": {s["unit"]: unit_text(s) for s in shares}, "changes_applied": False,
            "requires": ["root administrator, existing Unix and Samba accounts, POSIX ACL filesystem",
                         "existing saved owner must be verified Gateway/Worker UID; no force user or group grants",
                         "apply grants saved-only read ACLs, creates bind mount units, adds one include; smbd reload remains explicit",
                         "incoming source binds must be configured separately; production QQ acceptance is pending"]}
    if action == "plan":
        # Plan does not create directories/config/ACLs or read Samba credentials.
        plan["existing_paths"] = {str(p): p.exists() for p in (state, root, units)}
        plan["saved_nodes"] = {s["agent"]: len(walk(s["saved"])) for s in shares}
        return plan
    if action == "diagnose":
        checks, issues = {}, []
        for share in shares:
            valid = binding_matches(share)
            checks[share["agent"]] = {"bind_matches_saved": valid, "writer_uid": share["writer_uid"], "reader_uid": share["uid"]}
            if not valid:
                issues.append("RESULTS_BIND_MISSING_OR_CHANGED:"+share["agent"])
            if readers(share["saved"]) != [share["uid"]]:
                issues.append("SAVED_DEFAULT_ACL_MISSING_OR_CHANGED:"+share["agent"])
            checks[share["agent"]]["systemd_unit_exists"] = (units/share["unit"]).is_file()
            if not checks[share["agent"]]["systemd_unit_exists"]:
                issues.append("RESULTS_MOUNT_UNIT_MISSING:"+share["agent"])
            if valid:
                try:
                    command(["runuser", "-u", share["samba_user"], "--", "test", "-r", share["entry"]], 30)
                    command(["runuser", "-u", share["samba_user"], "--", "test", "-x", share["entry"]], 30)
                    # A reader must also be unable to create/delete files at the root.
                    command(["runuser", "-u", share["samba_user"], "--", "test", "!", "-w", share["entry"]], 30)
                    checks[share["agent"]]["unix_reader_access"] = "READ_TRAVERSE_NO_WRITE"
                except Fault:
                    issues.append("RESULTS_UNIX_ACCESS_FAILED:"+share["agent"])
        try:
            command(["testparm", "-s", str(conf)], 30)
            checks["testparm"] = "PASSED"
        except Fault as error:
            issues.append(error.code)
        return {"status": "RESULTS_DIAGNOSED", "checks": checks, "issues": issues,
                "smb_account_read_write_and_cross_user": "Run documented smbclient checks with real accounts; no credentials in CLI output",
                "production_acceptance": "PENDING"}
    if action == "rollback":
        if not record_path.exists():
            raise Fault("RESULTS_ROLLBACK_RECORD_REQUIRED")
        record = json.loads(record_path.read_text())
        if record["settings"] != raw:
            raise Fault("RESULTS_CONFIG_CHANGED")
        if not apply:
            return {"status": "RESULTS_ROLLBACK_PLAN", "record": str(record_path), "saved_data_preserved": True}
        return undo(record, record_path)
    if action != "apply" or not apply:
        raise Fault("EXPLICIT_APPLY_REQUIRED")
    if os.geteuid() != 0:
        raise Fault("ROOT_ADMIN_REQUIRED")
    if record_path.exists():
        record = json.loads(record_path.read_text())
        if record["settings"] != raw or record.get("rolled_back") or digest(conf) != record["installed_conf_sha"]:
            raise Fault("RESULTS_CONFIG_CHANGED")
        if any(not binding_matches(s) or readers(s["saved"]) != [s["uid"]] for s in shares) or digest(state/"results.conf") != record["fragment_sha"] or any(
                not Path(unit["path"]).is_file() or digest(unit["path"]) != unit["sha"] for unit in record["created_units"]):
            raise Fault("RESULTS_INSTALLATION_DRIFT", "Diagnose mount units/ACLs before reapplying; do not overlay another mount.")
        return {"status": "RESULTS_ALREADY_APPLIED", "record": str(record_path), "changes_applied": False}
    # Never consume an unrelated existing target, fragment, include or mount unit.
    if state.exists() and any(state.iterdir()) or MARKER in conf.read_text() or any(
            Path(s["entry"]).exists() or (units/s["unit"]).exists() or f"[{s['name']}]" in conf.read_text() for s in shares):
        raise Fault("RESULTS_INSTALLATION_CONFLICT")
    command(["testparm", "-s", str(conf)], 30)
    for binary in ("mount", "umount", "systemctl", "testparm", "runuser"):
        if not shutil.which(binary):
            raise Fault("SAMBA_ADMIN_DEPENDENCY_MISSING")
    permissions = []
    for share in shares:
        for path in walk(share["saved"]):
            if path.stat().st_uid != share["writer_uid"]:
                raise Fault("SAVED_OWNERSHIP_REQUIRES_REVIEW", "Review inconsistent saved owners; this command never recursively chowns a workspace.")
            # An unrelated custom named ACL needs explicit administrator review.
            prior = permission_record(path)
            for value in prior["acl"].values():
                if value:
                    import struct
                    if any(tag in (2, 8) for tag, _, _ in struct.iter_unpack("<HHI", base64.b64decode(value)[4:])):
                        raise Fault("EXISTING_SAVED_ACL_REQUIRES_REVIEW")
            permissions.append(prior)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state, 0o700)
    # smbd root can load our private fragment; personal users use the bind entry.
    backup = state/"previous-smb.conf"
    shutil.copy2(conf, backup)
    os.chmod(backup, 0o600)
    record = {"settings": raw, "shares": shares, "permissions": permissions, "conf": str(conf),
              "backup": str(backup), "before_conf_sha": digest(conf), "installed_conf_sha": digest(conf),
              "created_entries": [], "created_units": [], "root_created": not root.exists(), "time": timestamp()}
    atomic_json(record_path, record)
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o711)
        (state/"results.conf").write_text(fragment(shares), encoding="utf-8")
        os.chmod(state/"results.conf", 0o600)
        record["fragment_sha"] = digest(state/"results.conf")
        for share in shares:
            for path in walk(share["saved"]):
                set_read_acl(path, [share["uid"]])
            entry = Path(share["entry"])
            entry.mkdir(mode=0o700)
            record["created_entries"].append(str(entry))
            unit = units/share["unit"]
            unit.write_text(unit_text(share), encoding="utf-8")
            record["created_units"].append({"path": str(unit), "sha": digest(unit)})
            atomic_json(record_path, record)
            command(["mount", "--bind", share["saved"], share["entry"]], 30)
            if not binding_matches(share):
                raise Fault("RESULTS_BIND_VERIFY_FAILED")
        command(["systemctl", "daemon-reload"], 30)
        for share in shares:
            command(["systemctl", "enable", share["unit"]], 30)
        # Modify the existing inode so bind-mounted config consumers see the include.
        with conf.open("a", encoding="utf-8") as output:
            output.write(include)
        record["installed_conf_sha"] = digest(conf)
        atomic_json(record_path, record)
        command(["testparm", "-s", str(conf)], 30)
    except Exception:
        # Persist all positively owned resources before cleanup; leave record for review.
        atomic_json(record_path, record)
        undo(record, record_path)
        raise
    return {"status": "RESULTS_APPLIED", "changes_applied": True, "record": str(record_path),
            "next": "Explicitly reload smbd using the existing server service, then run account/read/write/cross-user acceptance checks.",
            "production_acceptance": "PENDING"}


def undo(record, record_path):
    if os.geteuid() != 0:
        raise Fault("ROOT_ADMIN_REQUIRED")
    if record.get("rolled_back"):
        return {"status": "RESULTS_ALREADY_ROLLED_BACK", "saved_data_preserved": True}
    conf = Path(record["conf"])
    if digest(conf) != record["installed_conf_sha"] or digest(record["backup"]) != record["before_conf_sha"]:
        raise Fault("SAMBA_CONFIG_CHANGED_AFTER_APPLY", "Preserve later administrator edits; remove only our include manually after review.")
    for unit in record["created_units"]:
        path = Path(unit["path"])
        if path.exists() and digest(path) != unit["sha"]:
            raise Fault("RESULTS_UNIT_CHANGED")
    for share in record["shares"]:
        entry = Path(share["entry"])
        if mounted(entry) and not binding_matches(share):
            raise Fault("RESULTS_MOUNT_CHANGED")
    # Restore original config bytes without changing its existing mode/ownership.
    with conf.open("wb") as output:
        output.write(Path(record["backup"]).read_bytes())
    for share in record["shares"]:
        if mounted(share["entry"]):
            command(["umount", share["entry"]], 30)
    for unit in record["created_units"]:
        command(["systemctl", "disable", Path(unit["path"]).name], 30)
        Path(unit["path"]).unlink(missing_ok=True)
    if record["created_units"]:
        command(["systemctl", "daemon-reload"], 30)
    previous = {r["path"]: r for r in record["permissions"]}
    for share in record["shares"]:
        for path in walk(share["saved"]):
            if str(path) in previous:
                restore_permissions(previous[str(path)])
            else:
                # New results remain. Remove our reader entries/defaults, retaining
                # the writer's permissions; our dedicated tree had no prior named ACL.
                for name in (ACCESS, DEFAULT):
                    if (name != DEFAULT or path.is_dir()) and acl_bytes(path, name):
                        os.removexattr(path, name, follow_symlinks=False)
                os.chmod(path, path.stat().st_mode & 0o700)
    for entry in record["created_entries"]:
        Path(entry).rmdir()  # Empty unmounted entrances only, never saved data.
    root = Path(record["settings"]["results_root"])
    if record["root_created"] and root.exists() and not any(root.iterdir()):
        root.rmdir()
    (Path(record_path).parent/"results.conf").unlink(missing_ok=True)
    record["rolled_back"] = timestamp()
    atomic_json(record_path, record)
    return {"status": "RESULTS_ROLLED_BACK", "saved_data_preserved": True,
            "next": "Reload the existing smbd service explicitly. Saved and original uploads were retained."}
