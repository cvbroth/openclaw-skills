"""Own each FileTools task in a dedicated subreaper; preserve sibling previews.

The generic ManagedChild assumes a dedicated parent. A threaded HTTP manager
also owns source-preview children, so its global cleanup must run in this owner
process, never directly in the HTTP service.
"""

import os
import signal
import subprocess
import sys
from ..process_tree import ManagedChild, enable_subreaper, terminate_descendants, reap_known_descendants


class StandaloneChild:
    def __init__(self, command, **kwargs):
        if os.name == "nt":
            self.delegate = ManagedChild(command, **kwargs)
            self.process = self.delegate.process
        else:
            self.delegate = None
            enable_subreaper()
            self.process = subprocess.Popen(
                [sys.executable, "-m", __name__, *command], start_new_session=True, **kwargs
            )

    def close(self):
        if self.delegate is not None:
            return self.delegate.close()
        known = terminate_descendants(self.process.pid)
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.process.wait(timeout=5)
        reap_known_descendants(known)


def main():
    child = ManagedChild(sys.argv[1:])
    try:
        code = child.process.wait()
    finally:
        child.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
