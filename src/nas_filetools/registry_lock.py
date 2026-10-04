"""Reentrant process/thread registry guard for Gateway management and worker."""
import os
import threading
import time

from .contracts import Fault


class RegistryLock:
    def __init__(self, path, timeout=30):
        self.path, self.timeout = path, timeout
        self.thread = threading.RLock()
        self.depth, self.file = 0, None

    def __enter__(self):
        self.thread.acquire()
        if self.depth:
            self.depth += 1
            return self
        try:
            if self.path.is_symlink():
                raise Fault("UNSAFE_REGISTRY_LOCK")
            self.file = self.path.open("a+b")
            if not self.path.stat().st_size:
                self.file.write(b"0")
                self.file.flush()
            deadline = time.monotonic()+self.timeout
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt
                        self.file.seek(0)
                        msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (BlockingIOError, OSError):
                    if time.monotonic() >= deadline:
                        raise Fault("REGISTRY_BUSY", "Retry the same request ID.") from None
                    time.sleep(0.05)
            self.depth = 1
            return self
        except Exception:
            if self.file:
                self.file.close()
            self.thread.release()
            raise

    def __exit__(self, *_args):
        self.depth -= 1
        if not self.depth:
            self.file.close()
            self.file = None
        self.thread.release()
