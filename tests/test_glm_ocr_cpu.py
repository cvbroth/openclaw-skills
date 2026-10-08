import importlib.util
import json
from pathlib import Path


spec = importlib.util.spec_from_file_location('glm_cpu', Path(__file__).parents[1] / 'scripts/run_glm_ocr_cpu.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_stream_adapter_preserves_raw_text():
    text, status, terminal = module.adapt_events([
        {'response': 'A. 原字\n'}, {'response': '<script>非</script>'},
        {'done': True, 'done_reason': 'stop', 'eval_count': 10}])
    assert text == 'A. 原字\n<script>非</script>'
    assert status == 'SUCCEEDED'
    assert terminal['eval_count'] == 10


def test_partial_and_length_are_not_success():
    assert module.adapt_events([{'response': '部分'}])[1] == 'PARTIAL_NO_TERMINAL'
    assert module.adapt_events([{'response': '部分', 'done': True, 'done_reason': 'length'}])[1] == 'PARTIAL_TERMINATED'
    assert module.adapt_events([{'error': 'model unavailable'}])[1] == 'FAILED'
    assert module.adapt_events([])[1] == 'FAILED'
    assert module.adapt_events([{'done': True, 'done_reason': 'stop'}])[1] == 'FAILED_EMPTY_OUTPUT'


def test_diagnostic_adds_only_control_stops_not_native_eog_registration():
    baseline = module.generation_options(2)
    fixed = module.generation_options(2, True)
    assert fixed.pop('stop') == ['<|endoftext|>', '<|user|>']
    assert fixed == baseline


def test_interrupt_still_writes_abort_receipt_and_resources(tmp_path, monkeypatch):
    import argparse
    import io

    class Process:
        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    image = tmp_path / "synthetic.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (40).to_bytes(4, "big") + (20).to_bytes(4, "big"))
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: Process())
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"{}"))
    monkeypatch.setattr(module, "request", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    output = tmp_path / "output"
    assert (
        module.main(
            argparse.Namespace(
                output=output,
                image=image,
                page=1,
                timeout=30,
                model="synthetic",
                modelfile=None,
                threads=1,
                diagnostic_stop_strings=False,
            )
        )
        == 1
    )
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["status"] == "ABORTED"
    assert receipt["request_seconds"] is None
    assert (output / "final-resources.json").is_file()
