"""Export faults must not be mislabeled as model recognition failures."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location(
    'ocr_evaluator', Path(__file__).resolve().parents[1] / 'scripts/evaluate_paddleocr_vl.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_native_result_retained_when_markdown_export_fails(tmp_path, monkeypatch):
    class Result:
        def save_to_json(self, directory):
            Path(directory, 'native.json').write_text('{"recognized":true}')

        def save_to_markdown(self, directory):
            raise ValueError('synthetic markdown export failure')

    monkeypatch.setitem(sys.modules, 'paddleocr', SimpleNamespace(PaddleOCRVL=object))
    monkeypatch.setattr(MODULE, 'build_pipeline', lambda *_: SimpleNamespace(predict=lambda _: [Result()]))
    Path(tmp_path, 'page-6.png').write_bytes(b'synthetic image')
    try:
        MODULE.child(tmp_path, tmp_path, tmp_path, [6], 'paddleocr-vl-1.5')
    except ValueError:
        pass
    else:
        raise AssertionError('export failure must propagate')
    metrics = json.loads(Path(tmp_path, 'metrics.json').read_text())
    assert metrics['pages'][0]['failure_phase'] == 'export'
    assert Path(tmp_path, 'page-6/native.json').is_file()
