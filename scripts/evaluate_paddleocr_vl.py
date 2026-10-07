"""Offline three-image CPU evaluation; input images only, never prior OCR hints.

The monitor bounds imports/model loading/pages separately and records real peak
RSS. Network isolation and CPU/RAM ceilings are enforced by the test container.
"""
import argparse
import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path


def record(path, value):
    temporary = path.with_suffix('.temporary')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def process_cpu_seconds():
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


def validate_ppstructure_compatibility(config):
    constraint = config.get('compatibility_constraints', {})
    if (constraint.get('disabled_chart_predictor_still_initialized')
            and not config['options'].get('use_chart_recognition', False)
            and 'chart_recognition_model_dir' not in config['models']):
        raise RuntimeError(
            'PPSTRUCTUREV3_CONFIG_BLOCKED: pinned PaddleX initializes ChartRecognition even when disabled; '
            'a pinned local auxiliary chart model is required even though business recognition is disabled')


def build_pipeline(engine, models):
    if engine == 'paddleocr-vl-1.5':
        from paddleocr import PaddleOCRVL
        return PaddleOCRVL(paddlex_config=str(Path(__file__).resolve().parents[1] / 'deploy/paddleocr-vl-cpu-eval.yaml'),
            pipeline_version='v1.5', device='cpu', cpu_threads=2,
            layout_detection_model_name='PP-DocLayoutV3', layout_detection_model_dir=str(models / 'layout'),
            vl_rec_model_name='PaddleOCR-VL-1.5-0.9B', vl_rec_model_dir=str(models / 'vl'),
            use_doc_orientation_classify=False, use_doc_unwarping=False, use_layout_detection=True)
    if engine == 'ppstructurev3':
        import yaml
        config_path = Path(__file__).resolve().parents[1] / 'deploy/ppstructurev3-text-only.yaml'
        config = yaml.safe_load(config_path.read_text())
        validate_ppstructure_compatibility(config)
        from paddleocr import PPStructureV3
        parameters = {**config['models'], **config['options'], **config.get('runtime', {}),
                      'device': config['device'], 'cpu_threads': config['cpu_threads']}
        parameters = {key: (str(models / value) if key.endswith('_model_dir') and value else value)
                      for key, value in parameters.items()}
        return PPStructureV3(**parameters)
    raise ValueError('UNKNOWN_ENGINE')


def child(images, models, output, pages, engine):
    stage = output / 'stage.json'
    record(stage, {'phase': 'import', 'started': time.monotonic()})
    started, import_cpu_started = time.monotonic(), process_cpu_seconds()
    if engine == 'paddleocr-vl-1.5':
        from paddleocr import PaddleOCRVL  # noqa: F401
    elif engine == 'ppstructurev3':
        from paddleocr import PPStructureV3  # noqa: F401
    imported, import_cpu_finished = time.monotonic(), process_cpu_seconds()
    config_path = Path(__file__).resolve().parents[1] / (
        'deploy/ppstructurev3-text-only.yaml' if engine == 'ppstructurev3' else 'deploy/paddleocr-vl-cpu-eval.yaml')
    metrics = {'engine': engine,
               'pipeline_config_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest(),
               'package_import_seconds': imported - started,
               'package_import_process_cpu_seconds': import_cpu_finished - import_cpu_started,
               'device': 'cpu', 'cpu_threads': 2,
               'gpu_peak_vram_bytes': None, 'gpu_status': 'no CUDA device exposed', 'pages': []}
    record(output / 'metrics.json', metrics)
    record(stage, {'phase': 'model_load', 'started': imported})
    model_load_started = time.monotonic()
    model_load_cpu_started = process_cpu_seconds()
    try:
        pipeline = build_pipeline(engine, models)
    except Exception as error:
        metrics.update(model_load_attempt_seconds=time.monotonic() - model_load_started,
                       model_load_attempt_process_cpu_seconds=process_cpu_seconds() - model_load_cpu_started,
                       model_load_error_type=type(error).__name__, model_load_error=str(error)[:500])
        record(output / 'metrics.json', metrics)
        raise
    metrics.update(model_load_seconds=time.monotonic() - model_load_started,
                   model_load_process_cpu_seconds=process_cpu_seconds() - model_load_cpu_started,
                   process_peak_rss_after_load_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    record(output / 'metrics.json', metrics)
    for index, page in enumerate(pages):
        incoming = images / f'page-{page}.png'
        started, page_cpu_started = time.monotonic(), process_cpu_seconds()
        record(stage, {'phase': 'page', 'page': page, 'started': started})
        directory = output / f'page-{page}'
        directory.mkdir(exist_ok=True)
        count = 0
        failure_phase = 'inference'
        inference_finished = None
        try:
            results = list(pipeline.predict(str(incoming)))
            inference_finished = time.monotonic()
            failure_phase = 'export'
            for result in results:
                result.save_to_json(str(directory))
                result.save_to_markdown(str(directory))
                count += 1
        except Exception as error:
            metrics['pages'].append({'physical_page': page, 'status': 'FAILED',
                'elapsed_seconds': time.monotonic() - started,
                'process_cpu_seconds': process_cpu_seconds() - page_cpu_started,
                'error_type': type(error).__name__, 'error': str(error)[:500],
                'failure_phase': failure_phase,
                'process_peak_rss_kib_cumulative': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                'input_image_sha256': hashlib.sha256(incoming.read_bytes()).hexdigest()})
            record(output / 'metrics.json', metrics)
            raise
        metrics['pages'].append({'physical_page': page, 'status': 'SUCCEEDED',
            'elapsed_seconds': time.monotonic() - started,
            'process_cpu_seconds': process_cpu_seconds() - page_cpu_started,
            'inference_seconds': inference_finished - started,
            'export_seconds': time.monotonic() - inference_finished,
            'inference_order': index + 1, 'cold_first_inference': index == 0,
            'process_peak_rss_kib_cumulative': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'page_results': count, 'input_image_sha256': hashlib.sha256(incoming.read_bytes()).hexdigest()})
        record(output / 'metrics.json', metrics)
    record(stage, {'phase': 'complete', 'started': time.monotonic()})


def sample_peak_rss(status, previous):
    # Exiting/zombie processes can have no VmRSS/VmHWM at all.
    values = [previous]
    values.extend(int(line.split()[1]) for line in status.splitlines()
                  if line.startswith(('VmRSS:', 'VmHWM:')))
    return max(values)


def monitor(images, models, output, pages, load_timeout, page_timeout, engine):
    output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-B', __file__, '--child', '--images', str(images), '--models', str(models),
               '--output', str(output), '--engine', engine, '--pages', *map(str, pages)]
    started, peak = time.monotonic(), 0
    with (output / 'stdout.log').open('wb') as stdout, (output / 'stderr.log').open('wb') as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
        timeout = None
        try:
            while process.poll() is None:
                try:
                    status = Path(f'/proc/{process.pid}/status').read_text()
                    peak = sample_peak_rss(status, peak)
                except (OSError, ValueError):
                    pass
                phase = {'phase': 'import', 'started': started}
                try:
                    phase = json.loads((output / 'stage.json').read_bytes())
                except (OSError, ValueError):
                    pass
                record(output / 'monitor-progress.json', {'wall_seconds': time.monotonic() - started,
                    'monitored_process_peak_rss_kib': peak, 'stage': phase})
                maximum = page_timeout if phase['phase'] == 'page' else load_timeout
                if time.monotonic() - phase['started'] > maximum or time.monotonic() - started > load_timeout + page_timeout * len(pages):
                    timeout = {'phase': phase, 'limit_seconds': maximum}
                    break
                time.sleep(0.2)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
    receipt = {'status': 'TIMED_OUT' if timeout else ('SUCCEEDED' if process.returncode == 0 else 'FAILED'),
               'wall_seconds': time.monotonic() - started, 'exit_code': process.returncode,
               'monitored_process_peak_rss_kib': peak, 'timeout': timeout,
               'model_load_limit_seconds': load_timeout, 'page_limit_seconds': page_timeout,
               'engine': engine, 'pages_requested': pages, 'offline': True, 'identity': 'independent evaluation, not FileTools production'}
    try:
        receipt['container_memory_peak_bytes'] = int(Path('/sys/fs/cgroup/memory.peak').read_text())
    except (OSError, ValueError):
        receipt['container_memory_peak_bytes'] = None
    try:
        receipt['container_cpu_stat'] = dict(line.split() for line in Path('/sys/fs/cgroup/cpu.stat').read_text().splitlines())
    except (OSError, ValueError):
        receipt['container_cpu_stat'] = None
    record(output / 'run-receipt.json', receipt)
    print(json.dumps(receipt))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('images', 'models', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--engine', choices=('paddleocr-vl-1.5', 'ppstructurev3'), default='paddleocr-vl-1.5')
    parser.add_argument('--pages', nargs='+', type=int, choices=(6, 10, 30), default=[6, 10, 30])
    parser.add_argument('--load-timeout', type=int, default=180)
    parser.add_argument('--page-timeout', type=int, default=300)
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args()
    if args.child:
        child(args.images, args.models, args.output, args.pages, args.engine)
    else:
        receipt = monitor(args.images, args.models, args.output, args.pages, args.load_timeout, args.page_timeout, args.engine)
        sys.exit(0 if receipt['status'] == 'SUCCEEDED' else 2)
