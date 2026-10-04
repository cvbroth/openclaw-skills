"""Bound script descendants before running code; reclaim even when the leader has exited."""
import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .contracts import Fault


def enable_subreaper():
    if sys.platform == "linux" and ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) != 0:
        raise Fault("SCRIPT_TREE_BOUNDARY_UNAVAILABLE")


def reap_known_descendants(known):
    """Reap only recorded children, preserving unrelated multiprocessing bookkeeping."""
    if sys.platform != "linux":
        return
    deadline = time.monotonic()+3
    while known and time.monotonic() < deadline:
        for pid, started in list(known.items()):
            try:
                current = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
                if current != started:
                    known.pop(pid)
                    continue
                try:
                    os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    pass  # Adoption may still be in flight after the leader's death.
            except (OSError, IndexError):
                known.pop(pid)
        if known:
            time.sleep(.02)
    if known:
        raise Fault("SCRIPT_TREE_RECLAIM_FAILED")


def windows_job():
    from ctypes import wintypes
    class Basic(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong), ("flags", wintypes.DWORD),
            ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t), ("active", wintypes.DWORD),
            ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]
    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", ctypes.c_ulonglong*6), ("process_mem", ctypes.c_size_t),
                   ("job_mem", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    info = Extended()
    info.basic.flags = 0x2000 | 0x8  # KILL_ON_JOB_CLOSE, ACTIVE_PROCESS limit; no breakaway.
    info.basic.active = 32
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        if handle:
            kernel.CloseHandle(handle)
        raise Fault("SCRIPT_TREE_BOUNDARY_UNAVAILABLE")
    return kernel, handle


def linux_descendants(root_pid=None):
    # A dedicated worker becomes subreaper, so double-fork/setsid children reparent here.
    parents = {}
    for item in Path("/proc").iterdir():
        if not item.name.isdigit():
            continue
        try:
            value = (item/"stat").read_text().rsplit(")", 1)[1].split()
            parents[int(item.name)] = (int(value[1]), value[19])  # ppid, starttime.
        except (OSError, ValueError, IndexError):
            continue
    selected, frontier = {}, {root_pid or os.getpid()}
    while frontier:
        next_level = {pid for pid, (parent, _) in parents.items() if parent in frontier and pid not in selected}
        selected.update({pid: parents[pid][1] for pid in next_level})
        frontier = next_level
    return selected


def terminate_descendants(pid):
    if sys.platform != "linux":
        return {}
    # Freeze before killing so writers/forking children cannot race publication or cancellation.
    known = {}
    for _ in range(8):
        current = linux_descendants(pid)
        for child, started in current.items():
            try:
                check = Path(f"/proc/{child}/stat").read_text().rsplit(")", 1)[1].split()[19]
                if check == started:
                    os.kill(child, signal.SIGSTOP)
                    known[child] = started
            except (OSError, IndexError):
                pass
        if current.keys() <= known.keys() and len(current) == len(known):
            # A second scan catches a fork completed just before its parent's SIGSTOP.
            if linux_descendants(pid).keys() <= known.keys():
                break
    for child, started in known.items():
        try:
            check = Path(f"/proc/{child}/stat").read_text().rsplit(")", 1)[1].split()[19]
            if check == started:
                os.kill(child, signal.SIGKILL)
        except (OSError, IndexError):
            pass
    return known


class ManagedChild:
    def __init__(self, command, **kwargs):
        self.job = None
        if os.name == "nt":
            self.kernel, self.job = windows_job()
            try:
                self.process = subprocess.Popen(command, creationflags=0x4, **kwargs)  # Suspended until job-bound.
                if not self.kernel.AssignProcessToJobObject(self.job, int(self.process._handle)):
                    raise Fault("SCRIPT_TREE_BOUNDARY_UNAVAILABLE")
                resume = ctypes.WinDLL("ntdll").NtResumeProcess
                resume.argtypes = [ctypes.c_void_p]
                if resume(int(self.process._handle)) != 0:
                    raise Fault("SCRIPT_TREE_BOUNDARY_UNAVAILABLE")
            except Exception:
                if hasattr(self, "process"):
                    self.process.kill()
                    self.process.wait()
                self.close()
                raise
        else:
            enable_subreaper()
            self.process = subprocess.Popen(command, start_new_session=True, **kwargs)

    def close(self):
        if os.name == "nt":
            if self.job:
                self.kernel.TerminateJobObject(self.job, 1)
                accounting = (ctypes.c_byte*48)()
                deadline = time.monotonic()+3
                stopped = False
                while time.monotonic() < deadline:
                    if not self.kernel.QueryInformationJobObject(self.job, 1, accounting, 48, None):
                        break
                    if ctypes.c_uint32.from_buffer(accounting, 40).value == 0:
                        stopped = True
                        break
                    time.sleep(0.02)
                self.kernel.CloseHandle(self.job)
                self.job = None
                if not stopped:
                    raise Fault("SCRIPT_TREE_RECLAIM_FAILED")
        elif hasattr(self, "process"):
            terminate_descendants(os.getpid())
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if sys.platform == "linux":
                deadline = time.monotonic()+3
                while time.monotonic() < deadline:
                    descendants = linux_descendants()
                    if not descendants:
                        break
                    for pid, started in descendants.items():
                        try:
                            current = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
                            if current == started:
                                os.kill(pid, signal.SIGKILL)
                        except (OSError, IndexError):
                            pass
                    while True:
                        try:
                            if os.waitpid(-1, os.WNOHANG)[0] == 0:
                                break
                        except ChildProcessError:
                            break
                    time.sleep(0.02)
                if linux_descendants():
                    raise Fault("SCRIPT_TREE_RECLAIM_FAILED")
        if hasattr(self, "process"):
            self.process.wait(timeout=5)
