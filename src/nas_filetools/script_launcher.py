"""Child-only Linux filesystem/network restriction; never claim cwd is a sandbox."""
import ctypes
import errno
import os
import runpy
import sys
from pathlib import Path


def restrict(folder, input_file=None):
    if sys.platform != "linux" or os.uname().machine not in ("x86_64", "aarch64"):
        raise RuntimeError("SCRIPT_ISOLATION_UNAVAILABLE")
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise RuntimeError("LANDLOCK_ABI_3_REQUIRED")
    # ABI 3 covers TRUNCATE; ABI 1/2 cannot enforce the same write boundary.
    handled = (1 << 15)-1
    ruleset = ctypes.c_uint64(handled)
    fd = libc.syscall(444, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0)
    if fd < 0:
        raise RuntimeError("LANDLOCK_CREATE_FAILED")
    class Rule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed", ctypes.c_uint64), ("parent", ctypes.c_int32)]
    def allow(path, access):
        if not Path(path).exists():
            return
        parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
        try:
            rule = Rule(access, parent)
            if libc.syscall(445, fd, 1, ctypes.byref(rule), 0) != 0:
                raise RuntimeError("LANDLOCK_RULE_FAILED")
        finally:
            os.close(parent)
    for path in {"/usr", "/lib", "/lib64", sys.prefix, sys.base_prefix}:
        allow(path, (1 << 0) | (1 << 2) | (1 << 3))  # execute/read_file/read_dir
    allow(str(folder), handled)
    if input_file:
        allow(str(input_file), 1 << 2)  # Read the sole input, with no write/truncate/unlink rights.
    allow("/dev/null", (1 << 1) | (1 << 2))
    if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.syscall(446, fd, 0) != 0:
        raise RuntimeError("LANDLOCK_RESTRICT_FAILED")
    os.close(fd)
    sec = ctypes.CDLL("libseccomp.so.2")
    sec.seccomp_init.restype = ctypes.c_void_p
    sec.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    sec.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    sec.seccomp_load.argtypes = [ctypes.c_void_p]
    sec.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = sec.seccomp_init(0x7FFF0000)
    if not ctx:
        raise RuntimeError("SECCOMP_INIT_FAILED")
    try:
        for name in ("socket", "connect", "bind", "listen", "accept", "accept4", "ptrace", "mount", "umount2",
                     "unshare", "setns", "bpf", "process_vm_readv", "process_vm_writev", "kill", "tgkill", "tkill", "setsid", "setpgid"):
            number = sec.seccomp_syscall_resolve_name(name.encode())
            if number >= 0 and sec.seccomp_rule_add(ctx, 0x00050000 | errno.EPERM, number, 0) != 0:
                raise RuntimeError("SECCOMP_RULE_FAILED")
        if sec.seccomp_load(ctx) != 0:
            raise RuntimeError("SECCOMP_LOAD_FAILED")
    finally:
        sec.seccomp_release(ctx)


if __name__ == "__main__":
    folder = Path(sys.argv[1]).resolve()
    os.chdir(folder)
    if sys.argv[2] == "landlock":
        restrict(folder, Path(sys.argv[6]).resolve() if len(sys.argv)>6 else None)
    if os.name == "posix":
        import resource
        memory, seconds, output = map(int, sys.argv[3:6])
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds+1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (output, output))
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    try:
        runpy.run_path(str(folder/"operation.py"), run_name="__main__")
    except OSError as error:
        if error.errno == errno.EFBIG:
            sys.exit(73)  # Linux per-file output resource limit.
        raise
    except MemoryError:
        sys.exit(74)
