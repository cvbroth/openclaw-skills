import base64
import hashlib
import io
import json
import sys
import types
from dataclasses import dataclass

from PIL import Image

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1] / 'scripts'))
from mineru_standard_observer import capture_images, install
from summarize_mineru_standard_trial import summarize


def test_exact_image_bytes_and_multiple_inputs(tmp_path):
    stream = io.BytesIO()
    Image.new('RGB', (181, 257)).save(stream, format='PNG')
    raw = stream.getvalue()
    message = [{'role': 'user', 'content': [
        {'type': 'text', 'text': 'synthetic'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(raw).decode()}}
    ]}]
    images = capture_images(message * 2, tmp_path)
    assert len(images) == 2
    assert images[0]['sha256'] == hashlib.sha256(raw).hexdigest()
    assert (tmp_path / images[0]['file']).read_bytes() == raw
    assert (images[0]['width'], images[0]['height']) == (181, 257)


def test_engine_configuration_and_passive_return(monkeypatch, tmp_path):
    @dataclass
    class Result:
        content: str = 'synthetic raw'
        finish_reason: str = 'stop'
        tokens_evaluated: int = 3
        tokens_predicted: int = 2
    expected = Result()
    calls = []

    class Engine:
        def __init__(self, model, mmproj, **kwargs):
            calls.append(kwargs)

        def generate(self, messages, params):
            calls.append((messages, params))
            return expected

    window = types.SimpleNamespace(_prepare_pdf_window=lambda x: x)
    parser = types.SimpleNamespace(ParseResult=type('Result', (), {'save': lambda self, x: x}))
    modules = {'mineru_llama_cpp': types.SimpleNamespace(Engine=Engine),
               'mineru_vl_utils.mineru_client': types.SimpleNamespace(MinerUClientHelper=type('Client', (), {
                   'prepare_for_extract': lambda self, image, blocks: (image, blocks)})),
               'mineru.config': types.SimpleNamespace(config=types.SimpleNamespace(model=types.SimpleNamespace(
                   vlm=types.SimpleNamespace(server_url='', engine='llama-cpp')))),
               'mineru.backend.analysis.pdf': types.SimpleNamespace(window=window),
               'mineru.parser.base': parser}
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    install(tmp_path, lambda: 12, 2)
    engine = modules['mineru_llama_cpp'].Engine('main.gguf', 'mmproj.gguf')
    messages = [{'role': 'user', 'content': 'synthetic'}]
    assert engine.generate(messages) is expected
    assert calls[0]['n_threads'] == 2 and calls[0]['n_gpu_layers'] == 0 and calls[0]['n_parallel'] == 1
    assert calls[1][0] is messages
    receipt = json.loads((tmp_path / 'page-12/raw-generations/0001/receipt.json').read_text())
    assert receipt['status'] == 'SUCCEEDED'
    assert receipt['tokens_predicted'] == 2
    assert window._prepare_pdf_window('unchanged') == 'unchanged'
    summary = summarize(tmp_path)
    assert summary['calls'][0]['returned_characters'] == len(expected.content)
    assert expected.content not in json.dumps(summary)
    assert 'synthetic' not in json.dumps(summary)
