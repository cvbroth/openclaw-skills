"""Optional Linux saved-only read ACLs. No accounts, packages or daemon in the runtime.

The administrator installs a default ACL on saved/. Every complete publication reapplies
it to actual inodes: chmod 0440/0600 and atomic replacement can narrow inherited masks.
Owner permissions stay intact; Samba readers get r-- / r-x, never write.
"""
import errno
import os
import struct
from pathlib import Path

from .contracts import Fault

ACCESS = "system.posix_acl_access"
DEFAULT = "system.posix_acl_default"


def acl_bytes(path, name):
    if not hasattr(os, "getxattr"):
        return None
    try:
        return os.getxattr(path, name, follow_symlinks=False)
    except OSError as error:
        if error.errno in (errno.ENODATA, errno.ENOTSUP):
            return None
        raise


def readers(path):
    raw = acl_bytes(path, DEFAULT)
    if not raw:
        return []
    if struct.unpack_from("<I", raw)[0] != 2 or (len(raw)-4) % 8:
        raise Fault("SAVED_ACL_INVALID")
    owner = Path(path).stat().st_uid
    return [uid for tag, perms, uid in struct.iter_unpack("<HHI", raw[4:])
            if tag == 2 and perms == 5 and uid != owner]


def set_read_acl(path, uids):
    path = Path(path)
    if path.is_symlink() or not (path.is_dir() or path.is_file()):
        raise Fault("SAVED_SYMLINK_DENIED")
    if any(type(uid) is not int or uid <= 0 for uid in uids):
        raise Fault("INVALID_SAVED_READER_IDENTITY")
    # The owner is governed by USER_OBJ, not a named reader ACL. In particular,
    # a Samba account sharing the writer UID must keep its local owner rights.
    uids = [uid for uid in uids if uid != path.stat().st_uid]
    if not uids:
        return
    directory = path.is_dir()
    # Sole owner is the already verified Gateway/Worker user. Group and other do
    # not receive broad access; each existing personal Samba account is explicit.
    entries = [(1, (path.stat().st_mode >> 6) & 7, 0xffffffff)]
    entries.extend((2, 5 if directory else 4, uid) for uid in sorted(set(uids)))
    entries.extend([(4, 0, 0xffffffff), (16, 5 if directory else 4, 0xffffffff), (32, 0, 0xffffffff)])
    raw = struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *entry) for entry in entries)
    os.setxattr(path, ACCESS, raw, follow_symlinks=False)
    if directory:
        # Default owner rwx lets the writer create new subdirectories and files.
        defaults = [(1, 7, 0xffffffff), *entries[1:]]
        os.setxattr(path, DEFAULT, struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *entry) for entry in defaults), follow_symlinks=False)


def publish_saved_permissions(saved_root, bundle):
    uids = readers(saved_root)
    if not uids:
        return  # Compatibility: no Samba configuration or Linux ACL dependency required.
    bundle = Path(bundle)
    if not bundle.resolve().is_relative_to(Path(saved_root).resolve()):
        raise Fault("SAVED_PATH_ESCAPE")
    # Category directories can themselves be newly created with narrowed masks.
    for directory in reversed([bundle, *bundle.parents]):
        if directory.is_relative_to(Path(saved_root)):
            set_read_acl(directory, uids)
    for path in bundle.rglob("*"):
        set_read_acl(path, uids)
