"""Isolated official Ollama GLM-OCR recognizer; no cloud or OCR correction.

Run inside a network-none, CPU/memory-limited research container. The native
loopback API and streamed response remain separate from display adapters.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import threading
import time
import traceback
import urllib.request


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


def adapt_events(events):
    text = ''.join(event.get('response', '') for event in events)
    terminal = events[-1] if events else {}
    if terminal.get('error'):
        status = 'FAILED'
    elif terminal.get('done') and terminal.get('done_reason') == 'stop':
        status = 'SUCCEEDED' if text.strip() else 'FAILED_EMPTY_OUTPUT'
    elif terminal.get('done'):
        status = 'PARTIAL_TERMINATED'
    else:
        status = 'PARTIAL_NO_TERMINAL' if text else 'FAILED'
    return text, status, terminal


def generation_options(threads, diagnostic_stop_strings=False):
    options = {'num_thread': threads, 'num_gpu': 0, 'num_ctx': 8192,
               'num_predict': 4096, 'temperature': 0}
    if diagnostic_stop_strings:
        # Official GLM-OCR generation_config EOS IDs [59246,59253], also
        # checked against the actual official Ollama GGUF token strings.
        # Diagnostic only: these strings DO NOT register native EOG IDs;
        # control tokens can be filtered before decoded-text stop matching.
        # Never stop on a page number or body substring.
        options['stop'] = ['<|endoftext|>', '<|user|>']
    return options


def request(payload, timeout):
    data = json.dumps(payload).encode()
    req = urllib.request.Request('http://127.0.0.1:11434/api/generate', data=data,
                                 headers={'Content-Type': 'application/json'})
    return urllib.request.urlopen(req, timeout=timeout)


def cgroup_snapshot():
    root = Path('/sys/fs/cgroup')
    return {name: (root / name).read_text() for name in
            ('memory.current', 'memory.peak', 'memory.swap.peak', 'memory.events', 'cpu.stat', 'cpu.max', 'memory.max', 'memory.swap.max')
            if (root / name).is_file()}


def main(args):
    root = args.output
    root.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    stop = threading.Event()

    def monitor():
        with (root / 'resources.jsonl').open('w') as stream:
            while not stop.is_set():
                sample = {'elapsed_seconds': time.monotonic() - started, 'cgroup': cgroup_snapshot()}
                # Per-process RSS is sampled, not an exact lifetime peak.
                sample['processes'] = []
                for proc in Path('/proc').glob('[0-9]*'):
                    try:
                        status = (proc / 'status').read_text()
                        fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
                        sample['processes'].append({k: fields.get(k, '').strip() for k in ('Name', 'Pid', 'VmRSS', 'VmHWM', 'Threads')})
                    except (OSError, ProcessLookupError):
                        pass
                stream.write(json.dumps(sample) + '\n')
                stream.flush()
                stop.wait(2)

    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    log = (root / 'server.log').open('wb')
    server = subprocess.Popen(['/bin/ollama', 'serve'], stdout=log, stderr=log)
    events = []
    error = None
    def hard_timeout():
        write(root / 'timeout.json', {'status': 'TIMEOUT', 'wall_limit_seconds': args.timeout,
                                     'elapsed_seconds': time.monotonic() - started,
                                     'partial_output': 'see response.raw.jsonl and transcription.partial.txt; not a completed page'})
        os._exit(124)

    timer = threading.Timer(args.timeout, hard_timeout)
    timer.daemon = True
    timer.start()  # Hard whole-process ceiling, including startup/load.
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen('http://127.0.0.1:11434/api/version', timeout=1) as res:
                    write(root / 'version.json', json.load(res))
                break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError('OLLAMA_START_FAILED')
        show = urllib.request.Request('http://127.0.0.1:11434/api/show',
                                      data=json.dumps({'model': args.model}).encode(),
                                      headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(show, timeout=30) as response:
            write(root / 'model-show.json', json.load(response))
        data = args.image.read_bytes()
        metadata = {'physical_page': args.page, 'image_bytes': len(data),
                    'image_sha256': hashlib.sha256(data).hexdigest(),
                    'mime': 'image/png', 'dimensions': [int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')],
                    'model': args.model, 'prompt': 'Text Recognition:',
                    'options': generation_options(args.threads, args.diagnostic_stop_strings),
                    'endpoint': 'container loopback /api/generate', 'layout_model': None,
                    'route': 'official whole-image recognizer only; not SDK layout pipeline'}
        write(root / 'request-metadata.json', metadata)
        payload = {'model': args.model, 'prompt': metadata['prompt'],
                   'images': [base64.b64encode(data).decode()], 'stream': True,
                   'keep_alive': 0, 'options': metadata['options']}
        submitted = base64.b64decode(payload['images'][0], validate=True)
        if submitted != data:
            raise ValueError('SUBMITTED_IMAGE_BYTE_MISMATCH')
        write(root / 'submitted-image.json', {'sha256': hashlib.sha256(submitted).hexdigest(),
              'bytes': len(submitted), 'mime': metadata['mime'], 'dimensions': metadata['dimensions'],
              'scope': 'decoded actual request base64 before local HTTP submission; not internal vision tensor'})
        inference_start = time.monotonic()
        with request(payload, args.timeout) as response, (root / 'response.raw.jsonl').open('wb') as raw, (root / 'transcription.partial.txt').open('w') as partial:
            for line in response:
                raw.write(line)
                raw.flush()
                event = json.loads(line)
                events.append(event)
                partial.write(event.get('response', ''))
                partial.flush()
        inference_seconds = time.monotonic() - inference_start
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
        (root / 'exception.txt').write_text(traceback.format_exc())
        if isinstance(exc, urllib.error.HTTPError):
            (root / 'http-error.raw').write_bytes(exc.read())
        inference_seconds = None
    finally:
        text, status, terminal = adapt_events(events)
        if error:
            status = 'FAILED' if not text else 'PARTIAL_ERROR'
        (root / 'raw.md').write_text(text)
        write(root / 'response.json', terminal)
        write(root / 'blocks.json', [{'id': f'p{args.page:03}-b0001', 'type': 'unsegmented_transcription',
                                     'text': text, 'reading_order': 0, 'native_coordinates': None,
                                     'coordinate_system': None, 'image_references': [], 'native_order': None}] if text else [])
        write(root / 'receipt.json', {'status': status, 'error': error, 'elapsed_seconds': time.monotonic() - started,
                                      'request_seconds': inference_seconds, 'output_characters': len(text),
                                      'native_markdown': 'model response unchanged; no native layout JSON',
                                      'layout_model': None, 'terminal': terminal})
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        timer.cancel()
        stop.set()
        watcher.join(timeout=3)
        write(root / 'final-resources.json', {'cgroup': cgroup_snapshot(),
              'elapsed_seconds_including_shutdown': time.monotonic() - started,
              'child_maxrss_kib': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
              'child_cpu_seconds': resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
              'scope': 'child-process getrusage maximum plus sampled per-process RSS and cgroup peak; not summed RSS'})
        log.close()
    return 0 if status == 'SUCCEEDED' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--page', type=int, required=True)
    parser.add_argument('--model', default='glm-ocr:q8_0')
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--diagnostic-stop-strings', action='store_true',
                        help='reproduce an ineffective text-stop diagnostic; not an EOG registration fix')
    args = parser.parse_args()
    if args.page < 1 or not 1 <= args.threads <= 2 or not 1 <= args.timeout <= 1800:
        parser.error('positive physical page, 1–2 threads and 1–1800 second timeout required')
    raise SystemExit(main(args))
