"""Concurrent original previews must survive a formatting/analysis child exit."""

import subprocess
import sys
import time
from nas_filetools.standalone.scoped_child import StandaloneChild


def test_task_completion_does_not_kill_independent_preview_child():
    preview = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(15)"])
    try:
        child = StandaloneChild([sys.executable, "-c", 'print("task completed")'], stdout=subprocess.PIPE)
        assert child.process.wait(timeout=8) == 0
        child.close()
        assert preview.poll() is None
    finally:
        preview.kill()
        preview.wait(timeout=5)


def test_cancel_reclaims_owned_detached_descendant_only(tmp_path):
    marker = tmp_path / "late-write"
    descendant = "import time,pathlib,sys;time.sleep(3);pathlib.Path(sys.argv[1]).write_text('escaped')"
    script = (
        "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',"
        + repr(descendant)
        + ",sys.argv[1]],start_new_session=True);"
        "print('ready',flush=True);time.sleep(20)"
    )
    child = StandaloneChild([sys.executable, "-c", script, str(marker)], stdout=subprocess.PIPE)
    assert child.process.stdout.readline().strip() == b"ready"
    child.close()
    time.sleep(3.2)
    assert not marker.exists()
