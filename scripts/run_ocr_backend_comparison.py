"""Bounded, offline CPU research runner. Docker enforces isolation/resources.

Reuses the existing Paddle watchdog primitives; stages and pages are durable.
Each invocation uses one candidate. Completed pages are never overwritten.
"""
import argparse
import hashlib
import fcntl
import importlib.metadata
import json
import os
import resource
import signal
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from evaluate_paddleocr_vl import record, sample_peak_rss


def cpu():
    value = resource.getrusage(resource.RUSAGE_SELF)
    return value.ru_utime + value.ru_stime


def tensor_description(value):
    import numpy as np
    array = np.asarray(value)
    return {'shape': list(array.shape), 'dtype': str(array.dtype)}


def generation_capture(original, prepare, output, get_page):
    """Observe official CPU calls without altering prompts, pixels or outputs.

    MonkeyOCR's region workers can call concurrently even with one input page.
    Capture IDs must be local to a call, including after generation returns.
    """
    call_index = 0
    call_lock = threading.Lock()

    def capture(image, question, min_pixels=None, max_tokens=None, temperature=None, top_p=None):
        nonlocal call_index
        with call_lock:
            call_index += 1
            current_call = call_index
        prepared = prepare(image, max_pixels=1003520, min_pixels=min_pixels)
        folder = output / f'page-{get_page()}' / 'raw-generations'
        folder.mkdir(parents=True, exist_ok=True)
        incoming = folder / f'{current_call:04}-input.png'
        # PIL encoding mutates temporary encoder attributes: never encode a
        # shared model-input Image object from concurrent region workers.
        prepared.copy().save(incoming)
        call = {'prepared_size': list(prepared.size), 'prepared_png_sha256': hashlib.sha256(incoming.read_bytes()).hexdigest(),
                'prompt': question, 'max_tokens': max_tokens, 'status': 'RUNNING'}
        record(folder / f'{current_call:04}.json', call)
        value = original(image, question, min_pixels, max_tokens, temperature, top_p)
        call.update(status='SUCCEEDED', raw_text=value)
        record(folder / f'{current_call:04}.json', call)
        return value

    return capture


def archive_attempt(output):
    history = output / 'attempt-history'
    number = len(list(history.glob('attempt-*'))) + 1
    target = history / f'attempt-{number}'
    target.mkdir(parents=True)
    for name in ('run-receipt.json', 'metrics.json', 'stdout.log', 'stderr.log', 'stage.json', 'progress.json', 'resource-samples.jsonl', 'phase-events.jsonl', 'activity.json'):
        source = output / name
        if source.exists():
            shutil.copy2(source, target / name)
            if name in ('resource-samples.jsonl','phase-events.jsonl','activity.json'):
                source.unlink()
    for folder in output.glob('page-*'):
        receipt = folder / 'page-receipt.json'
        successful = receipt.exists() and json.loads(receipt.read_bytes()).get('status') == 'SUCCEEDED'
        if folder.is_dir() and not successful:
            shutil.move(str(folder), target / folder.name)
    return target


def child(args):
    output = args.output
    stage = output / 'stage.json'
    started = time.monotonic()
    record(stage, {'phase': 'import', 'started': started})
    if args.backend == 'paddle':
        from evaluate_paddleocr_vl import build_pipeline
    elif args.backend == 'monkey':
        sys.path.insert(0, str(args.source / 'parsing'))
        import torch
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        from cpu.core_runner import BackendConfig, BackendManager, PipelineConfig, load_image, run_pipeline
    elif args.backend == 'mineru':
        from mineru.parser import MinerUParser
        from mineru.parser.writer import FileBasedDataWriter
    else:
        raise ValueError('Candidate adapter not installed')
    metrics = {'backend': args.backend, 'device': 'cpu', 'cpu_threads': 2,
               'import_seconds': time.monotonic() - started, 'pages': [], 'versions': {}}
    for package in ('paddleocr', 'paddlex', 'paddlepaddle', 'numpy', 'torch', 'transformers', 'accelerate', 'mineru', 'onnxruntime'):
        try:
            metrics['versions'][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    record(output / 'metrics.json', metrics)
    loading = time.monotonic()
    record(stage, {'phase': 'model_load', 'started': loading})
    if args.backend == 'paddle':
        if args.paddle_version == '1.5':
            pipeline = build_pipeline('paddleocr-vl-1.5', args.models, cpu_threads=args.cpu_threads)
        else:
            from paddleocr import PaddleOCRVL
            pipeline = PaddleOCRVL(paddlex_config=str(Path(__file__).resolve().parents[1] / 'deploy/paddleocr-vl16-cpu-eval.yaml'),
                pipeline_version='v1.6', device='cpu', cpu_threads=args.cpu_threads,
                layout_detection_model_name='PP-DocLayoutV3', layout_detection_model_dir=str(args.models/'layout'),
                vl_rec_model_name='PaddleOCR-VL-1.6-0.9B', vl_rec_model_dir=str(args.models/'vl'),
                use_doc_orientation_classify=False, use_doc_unwarping=False, use_layout_detection=True)
        import paddle
        metrics['paddle_flags'] = paddle.get_flags(['FLAGS_paddle_num_threads'])
        metrics['paddle_version'] = args.paddle_version
        if args.instrument_paddle:
            from paddle_vl_observer import Observer
            observer = Observer(output).install(pipeline)
    elif args.backend == 'mineru':
        import onnxruntime as ort
        pipeline = MinerUParser(tier='basic', parse_mode='ocr', image_analysis=True)
        metrics['model_load_scope'] = 'parser constructor only; ONNX weights are lazy-loaded in first inference'
        metrics['onnx_initializations'] = []
        original_session = ort.InferenceSession

        class ObservedSession(original_session):
            def __init__(self, *values, **kwargs):
                initialization_started = time.monotonic()
                cumulative = sum(x['seconds'] for x in metrics['onnx_initializations'])
                record(stage, {'phase': 'model_load', 'started': initialization_started - cumulative})
                super().__init__(*values, **kwargs)
                self.observed_model_path = str(values[0]) if values else 'unprovided'
                options = self.get_session_options()
                metrics['onnx_initializations'].append({
                    'model_path': str(values[0]) if values else str(kwargs.get('path_or_bytes', 'unprovided')),
                    'seconds': time.monotonic() - initialization_started,
                    'providers': self.get_providers(), 'intra_op_threads': options.intra_op_num_threads,
                    'inter_op_threads': options.inter_op_num_threads})
                record(output / 'metrics.json', metrics)
                record(stage, {'phase': 'page', 'physical_page': active_page, 'started': page_start})

            def run(self, output_names, input_feed, run_options=None):
                if args.observe_shapes:
                    sample = {'model_path': self.observed_model_path,
                              'inputs': {key: tensor_description(value) for key, value in input_feed.items()}}
                    samples = metrics.setdefault('observed_model_tensor_shapes', [])
                    if sample not in samples:
                        samples.append(sample)
                        record(output / 'metrics.json', metrics)
                return super().run(output_names, input_feed, run_options)

        ort.InferenceSession = ObservedSession
    else:
        manager = BackendManager()
        config = BackendConfig(model_path=str(args.models), backend='transformers', device='cpu',
                               dtype='float32', attn_implementation='eager', max_pixels=1003520,
                               preprocess_batch_size=1, skip_preprocess=False)
        _, model = manager.get(config)
        model._generate_one = generation_capture(model._generate_one, load_image, output, lambda: active_page)
    metrics['cpu_threads'] = args.cpu_threads
    metrics['model_load_seconds'] = time.monotonic() - loading
    record(output / 'metrics.json', metrics)
    inference_index = 0
    for active_page in args.pages:
        folder = output / f'page-{active_page}'
        incoming = args.images / f'page-{active_page}.png'
        if (folder / 'page-receipt.json').exists():
            old = json.loads((folder / 'page-receipt.json').read_bytes())
            if old.get('status') != 'SUCCEEDED' or old['input_sha256'] != hashlib.sha256(incoming.read_bytes()).hexdigest():
                raise ValueError('RESUME_INPUT_OR_STATUS_MISMATCH')
            continue
        folder.mkdir(parents=True, exist_ok=True)
        page_start, cpu_start = time.monotonic(), cpu()
        record(stage, {'phase': 'page', 'physical_page': active_page, 'started': page_start})
        if args.backend == 'paddle':
            if args.instrument_paddle:
                observer.page = active_page
            for result in pipeline.predict(str(incoming)):
                result.save_to_json(str(folder))
                result.save_to_markdown(str(folder))
        elif args.backend == 'mineru':
            result = pipeline.parse(incoming)
            result.save(FileBasedDataWriter(str(folder)))
            (folder / 'raw.md').write_text(result.markdown())
            (folder / 'full-mode.md').write_text(result.markdown(add_markers=True))
        else:
            run_pipeline(PipelineConfig(input_path=str(incoming), output_path=str(folder), backend=config,
                                        page_max_inflight=1, keep_header_footer=True,
                                        retry_repeat=False, show_progress_bar=False), backend_manager=manager)
        receipt = {'physical_page': active_page, 'status': 'SUCCEEDED',
                   'elapsed_seconds': time.monotonic() - page_start,
                   'process_cpu_seconds': cpu() - cpu_start,
                   'process_peak_rss_kib_cumulative': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   'first_inference_in_process': inference_index == 0,
                   'input_sha256': hashlib.sha256(incoming.read_bytes()).hexdigest()}
        record(folder / 'page-receipt.json', receipt)
        metrics['pages'].append(receipt)
        record(output / 'metrics.json', metrics)
        inference_index += 1
    record(stage, {'phase': 'complete', 'started': time.monotonic()})


def monitor(args):
    args.output.mkdir(parents=True, exist_ok=True)
    if any((args.output / name).exists() for name in ('run-receipt.json', 'stage.json', 'stdout.log')):
        if not args.resume:
            raise ValueError('Run already has a receipt; use --resume or a distinct attempt directory')
        archive_attempt(args.output)
    command = [sys.executable, '-B', __file__, '--child', '--backend', args.backend,
               '--images', str(args.images), '--models', str(args.models), '--output', str(args.output),
               '--source', str(args.source), '--pages', *map(str, args.pages)]
    command.extend(['--paddle-version', args.paddle_version, '--cpu-threads', str(args.cpu_threads)])
    if args.instrument_paddle:
        command.append('--instrument-paddle')
    if args.observe_shapes:
        command.append('--observe-shapes')
    start, peak, timeout = time.monotonic(), 0, None
    sampled_at = 0
    with (args.output / 'stdout.log').open('wb') as stdout, (args.output / 'stderr.log').open('wb') as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
        while process.poll() is None:
            try:
                peak = sample_peak_rss(Path(f'/proc/{process.pid}/status').read_text(), peak)
            except OSError:
                pass
            phase = {'phase': 'import', 'started': start}
            try:
                phase = json.loads((args.output / 'stage.json').read_bytes())
            except (OSError, ValueError):
                pass
            if time.monotonic() - sampled_at >= 5:
                sampled_at = time.monotonic()
                snapshot = {'wall_seconds': sampled_at-start, 'stage': phase, 'process_peak_rss_kib': peak,
                            'host_loadavg': Path('/proc/loadavg').read_text().strip()}
                for name in ('memory.current','cpu.stat'):
                    try:
                        snapshot['cgroup_'+name] = Path('/sys/fs/cgroup',name).read_text().strip()
                    except OSError:
                        snapshot['cgroup_'+name] = None
                with (args.output/'resource-samples.jsonl').open('a') as samples:
                    samples.write(json.dumps(snapshot)+'\n')
            limit = args.page_timeout if phase['phase'] == 'page' else args.load_timeout
            record(args.output / 'progress.json', {'stage': phase, 'wall_seconds': time.monotonic() - start,
                                                  'process_peak_rss_kib': peak})
            if time.monotonic() - phase['started'] > limit:
                timeout = {'stage': phase, 'limit_seconds': limit}
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                break
            time.sleep(.2)
    receipt = {'status': 'TIMED_OUT' if timeout else ('SUCCEEDED' if process.returncode == 0 else 'FAILED'),
               'exit_code': process.returncode, 'wall_seconds': time.monotonic() - start,
               'process_peak_rss_kib': peak, 'timeout': timeout, 'pages_requested': args.pages,
               'backend': args.backend, 'model_load_limit_seconds': args.load_timeout,
               'page_limit_seconds': args.page_timeout}
    for name in ('memory.peak', 'memory.events', 'memory.swap.peak', 'cpu.stat'):
        try:
            receipt['cgroup_' + name] = Path('/sys/fs/cgroup', name).read_text().strip()
        except OSError:
            receipt['cgroup_' + name] = None
    record(args.output / 'run-receipt.json', receipt)
    print(json.dumps(receipt))
    return receipt['status'] == 'SUCCEEDED'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', choices=['paddle', 'monkey', 'mineru'], required=True)
    for name in ('images', 'models', 'output', 'source'):
        parser.add_argument('--' + name, type=Path, default=Path('/unused'))
    parser.add_argument('--pages', type=int, nargs='+', required=True)
    parser.add_argument('--load-timeout', type=int, default=180)
    parser.add_argument('--page-timeout', type=int, default=300)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--paddle-version', choices=['1.5','1.6'], default='1.5')
    parser.add_argument('--cpu-threads', type=int, default=2)
    parser.add_argument('--instrument-paddle', action='store_true')
    parser.add_argument('--resume', action='store_true', help='archive prior run logs; skip only successful pages with identical input SHA')
    parser.add_argument('--observe-shapes', action='store_true', help='separate diagnostic: record actual ONNX input shapes, never tensor contents')
    args = parser.parse_args()
    if args.cpu_threads < 1:
        parser.error('cpu threads must be positive')
    if len(set(args.pages)) != len(args.pages) or min(args.pages) < 1:
        parser.error('distinct positive physical pages required')
    if args.child:
        child(args)
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        with (args.output / 'runner.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            sys.exit(0 if monitor(args) else 2)
