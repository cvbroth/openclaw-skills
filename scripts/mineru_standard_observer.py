"""Scoped CPU Engine configuration and passive capture for MinerU 4 Standard.

No installed source edits, alternate pipeline, prompt/image/output replacement,
or cloud endpoints. Capture exact data-URI bytes already prepared by the client.
Engine CPU/slot settings use its supported constructor parameters explicitly.
"""
import base64
import dataclasses
import hashlib
import io
import json
import threading
import time


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


def capture_images(messages, folder):
    from PIL import Image
    records = []
    for message in messages:
        content = message.get('content')
        if not isinstance(content, list):
            continue
        for part in content:
            if part.get('type') != 'image_url':
                continue
            url = part['image_url']['url']
            if not url.startswith('data:image/'):
                raise ValueError('LOCAL_EXPERIMENT_REQUIRES_EMBEDDED_IMAGE')
            header, payload = url.split(',', 1)
            data = base64.b64decode(payload, validate=True)
            image = Image.open(io.BytesIO(data))
            name = f'input-{len(records)+1}.{image.format.lower()}'
            (folder / name).write_bytes(data)
            records.append({'file': name, 'width': image.width, 'height': image.height,
                            'format': image.format, 'mime': header[5:].split(';')[0],
                            'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    return records


def install(output, get_page, threads):
    import mineru_llama_cpp
    from mineru.config import config
    if config.model.vlm.server_url or config.model.vlm.engine != 'llama-cpp':
        raise ValueError('EXPLICIT_LOCAL_LLAMA_CPP_REQUIRED')
    original_engine = mineru_llama_cpp.Engine
    lock = threading.Lock()
    sequence = 0

    def event(phase, seconds):
        with lock, (output / 'standard-phases.jsonl').open('a') as stream:
            stream.write(json.dumps({'physical_page': get_page(), 'phase': phase,
                                     'seconds': seconds, 'monotonic': time.monotonic()}) + '\n')

    class CPUObservedEngine(original_engine):
        def __init__(self, model, mmproj, **kwargs):
            settings = {**kwargs, 'n_threads': threads, 'n_gpu_layers': 0,
                        'n_parallel': 1, 'verbosity': 3}
            write(output / 'engine-settings.json', {'model': str(model), 'mmproj': str(mmproj),
                                                   **settings})
            start = time.monotonic()
            super().__init__(model, mmproj, **settings)
            event('vlm_model_load', time.monotonic() - start)

        def generate(self, messages, sampling_params=None):
            nonlocal sequence
            with lock:
                sequence += 1
                call = sequence
            folder = output / f'page-{get_page()}' / 'raw-generations' / f'{call:04}'
            folder.mkdir(parents=True)
            capture_start = time.monotonic()
            record = {'status': 'RUNNING', 'images': capture_images(messages, folder),
                      'sampling_params': sampling_params.to_json_fields() if sampling_params else None,
                      'capture_seconds': time.monotonic() - capture_start}
            # Full requests remain private alongside raw responses; no logger
            # prints business text or encoded image payloads.
            write(folder / 'request.json', messages)
            write(folder / 'receipt.json', record)
            start = time.monotonic()
            try:
                result = super().generate(messages, sampling_params)
            except BaseException as exc:
                record.update(status='FAILED', error_type=type(exc).__name__,
                              elapsed_seconds=time.monotonic()-start)
                write(folder / 'receipt.json', record)
                raise
            write(folder / 'response.json', dataclasses.asdict(result))
            (folder / 'text.txt').write_text(result.content)
            record.update(status='SUCCEEDED', elapsed_seconds=time.monotonic()-start,
                          finish_reason=result.finish_reason, tokens_evaluated=result.tokens_evaluated,
                          tokens_predicted=result.tokens_predicted)
            write(folder / 'receipt.json', record)
            event('visual_generation_inclusive', record['elapsed_seconds'])
            return result

    mineru_llama_cpp.Engine = CPUObservedEngine
    # Existing async Engine.agenerate delegates to self.generate: one capture,
    # no duplicate preparation or second inference.
    from mineru_vl_utils.mineru_client import MinerUClientHelper
    original_extract = MinerUClientHelper.prepare_for_extract

    def extract(self, image, blocks, *args, **kwargs):
        folder = output / f'page-{get_page()}'
        folder.mkdir(parents=True, exist_ok=True)
        write(folder / 'extract-layout.json', {
            'image_size': list(image.size), 'coordinate_system': 'normalized xyxy on this internal page image',
            'blocks': [dict(block) for block in blocks]})
        return original_extract(self, image, blocks, *args, **kwargs)

    MinerUClientHelper.prepare_for_extract = extract
    from mineru.backend.analysis.pdf import window
    original_prepare = window._prepare_pdf_window

    def prepare(*args, **kwargs):
        start = time.monotonic()
        value = original_prepare(*args, **kwargs)
        event('window_prepare_layout_inclusive', time.monotonic()-start)
        return value

    window._prepare_pdf_window = prepare
    from mineru.parser.base import ParseResult
    original_save = ParseResult.save

    def save(self, *args, **kwargs):
        start = time.monotonic()
        result = original_save(self, *args, **kwargs)
        event('native_export', time.monotonic()-start)
        return result

    ParseResult.save = save
