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


def child(images, models, output, pages):
    stage = output / 'stage.json'
    record(stage, {'phase': 'import', 'started': time.monotonic()})
    started = time.monotonic()
    from paddleocr import PaddleOCRVL
    imported = time.monotonic()
    metrics = {'package_import_seconds': imported - started, 'device': 'cpu', 'cpu_threads': 2,
               'gpu_peak_vram_bytes': None, 'gpu_status': 'no CUDA device exposed', 'pages': []}
    record(output / 'metrics.json', metrics)
    record(stage, {'phase': 'model_load', 'started': imported})
    pipeline = PaddleOCRVL(paddlex_config=str(Path(__file__).resolve().parents[1] / 'deploy/paddleocr-vl-cpu-eval.yaml'),
        pipeline_version='v1.5', device='cpu', cpu_threads=2,
        layout_detection_model_name='PP-DocLayoutV3', layout_detection_model_dir=str(models / 'layout'),
        vl_rec_model_name='PaddleOCR-VL-1.5-0.9B', vl_rec_model_dir=str(models / 'vl'),
        use_doc_orientation_classify=False, use_doc_unwarping=False, use_layout_detection=True)
    metrics.update(model_load_seconds=time.monotonic() - imported,
                   process_peak_rss_after_load_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    record(output / 'metrics.json', metrics)
    for index, page in enumerate(pages):
        incoming = images / f'page-{page}.png'
        started = time.monotonic()
        record(stage, {'phase': 'page', 'page': page, 'started': started})
        directory = output / f'page-{page}'
        directory.mkdir(exist_ok=True)
        count = 0
        for result in pipeline.predict(str(incoming)):
            result.save_to_json(str(directory))
            result.save_to_markdown(str(directory))
            count += 1
        metrics['pages'].append({'physical_page': page, 'elapsed_seconds': time.monotonic() - started,
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


def monitor(images, models, output, pages, load_timeout, page_timeout):
    output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-B', __file__, '--child', '--images', str(images), '--models', str(models),
               '--output', str(output), '--pages', *map(str, pages)]
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
               'pages_requested': pages, 'offline': True, 'identity': 'independent evaluation, not FileTools production'}
    try:
        receipt['container_memory_peak_bytes'] = int(Path('/sys/fs/cgroup/memory.peak').read_text())
    except (OSError, ValueError):
        receipt['container_memory_peak_bytes'] = None
    record(output / 'run-receipt.json', receipt)
    print(json.dumps(receipt))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('images', 'models', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--pages', nargs='+', type=int, choices=(6, 10, 30), default=[6, 10, 30])
    parser.add_argument('--load-timeout', type=int, default=180)
    parser.add_argument('--page-timeout', type=int, default=300)
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args()
    if args.child:
        child(args.images, args.models, args.output, args.pages)
    else:
        receipt = monitor(args.images, args.models, args.output, args.pages, args.load_timeout, args.page_timeout)
        sys.exit(0 if receipt['status'] == 'SUCCEEDED' else 2)
