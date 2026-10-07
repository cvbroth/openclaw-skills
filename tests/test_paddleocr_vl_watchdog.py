"""Synthetic stalled child verifies bounds, not model performance."""
import importlib.util
import json
from pathlib import Path

path=Path(__file__).resolve().parents[1]/'scripts/evaluate_paddleocr_vl.py'
spec=importlib.util.spec_from_file_location('evaluation',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_stalled_test_child_is_stopped_without_extending_limit(tmp_path,monkeypatch):
    fake=tmp_path/'child.py'
    fake.write_text('import time\ntime.sleep(20)\n')
    monkeypatch.setattr(module,'__file__',str(fake))
    output=tmp_path/'results'
    module.monitor(tmp_path,tmp_path,output,[6],1,1,'paddleocr-vl-1.5')
    result=json.loads((output/'run-receipt.json').read_text())
    assert result['status']=='TIMED_OUT'
    assert result['timeout']['limit_seconds']==1
    assert result['wall_seconds']<5
    assert result['exit_code'] != 0


def test_zombie_status_keeps_previous_peak_without_crashing():
    # Regression: the first real OOM left /proc/status without memory fields.
    assert module.sample_peak_rss('Name:\tpython\nState:\tZ (zombie)\n', 123) == 123
