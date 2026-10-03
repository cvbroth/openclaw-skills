"""Executed on Linux CI/acceptance only; tests real Landlock and seccomp, not mocks."""
import subprocess
import sys
from pathlib import Path

import pytest

from nas_filetools import script_launcher

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Requires Linux Landlock ABI>=3 + libseccomp")


def test_real_linux_script_boundary_denies_host_files_and_network(tmp_path):
    outside = tmp_path/"private.txt"
    outside.write_text("secret")
    job = tmp_path/"job"
    job.mkdir()
    (job/"operation.py").write_text(f"""from pathlib import Path
import socket
try:
    Path({str(outside)!r}).read_text()
except PermissionError:
    pass
else:
    raise AssertionError('host filesystem was readable')
try:
    socket.socket()
except PermissionError:
    pass
else:
    raise AssertionError('network socket allowed')
Path('result.txt').write_text('isolated')
""")
    result = subprocess.run([sys.executable, "-I", str(Path(script_launcher.__file__)), str(job), "landlock",
                             str(4096*1024**2), "10", str(1024**2)], capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode()
    assert (job/"result.txt").read_text() == "isolated"
