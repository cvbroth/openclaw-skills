"""Resumable, serial PP-StructureV3 page runner for the locked OCR expansion."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def run(args):
    images = args.images.resolve()
    models = args.models.resolve()
    previous = args.previous.resolve()
    output = args.output.resolve()
    expected = json.loads(args.manifest.read_text())
    rows = {row['physical_page']: row for row in expected}
    if len(rows) != 20 or set(rows) != set(args.pages):
        raise SystemExit('locked manifest must contain exactly the requested 20 distinct pages')
    for page, row in rows.items():
        image = images / f'page-{page}.png'
        if not image.is_file() or sha256(image) != row['image_sha256']:
            raise SystemExit(f'input page {page} missing or SHA-256 mismatch')
    actual_image_id = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', args.image_id],
                                     text=True, capture_output=True)
    if actual_image_id.returncode or actual_image_id.stdout.strip() != args.expected_image_id:
        raise SystemExit('fixed PP-StructureV3 image ID check failed; no OCR was started')
    output.mkdir(parents=True, exist_ok=True)
    progress_path = output / 'batch-progress.json'
    progress = json.loads(progress_path.read_text()) if progress_path.exists() else {
        'engine': 'ppstructurev3', 'configuration': 'deploy/ppstructurev3-text-only.yaml',
        'serial': True, 'limit': {'cpus': 2, 'memory_bytes': 17179869184,
                                  'memory_swap_bytes': 17179869184,
                                  'load_timeout_seconds': 180, 'page_timeout_seconds': 300,
                                  'network': 'none', 'device': 'cpu', 'cpu_threads': 2},
        'pages': {}}
    # The three earlier pages are reused only if their input and native outputs
    # match the already-reported successful run. No new inference is performed.
    old_metrics = json.loads((previous / 'metrics.json').read_text())
    old_receipt = json.loads((previous / 'run-receipt.json').read_text())
    if old_receipt.get('status') != 'SUCCEEDED' or old_metrics.get('engine') != 'ppstructurev3':
        raise SystemExit('previous three-page run is not a successful PP-StructureV3 receipt')
    old_by_page = {row['physical_page']: row for row in old_metrics['pages']}
    for page in (6, 10, 30):
        old = previous / f'page-{page}'
        expected_row = old_by_page.get(page)
        if (not expected_row or expected_row.get('status') != 'SUCCEEDED'
                or expected_row.get('input_image_sha256') != rows[page]['image_sha256']
                or not (old / f'page-{page}_res.json').is_file()
                or not (old / f'page-{page}.md').is_file()):
            raise SystemExit(f'prior page {page} cannot be safely reused')
        progress['pages'].setdefault(str(page), {'status': 'REUSED_PRIOR_SUCCESS',
            'input_image_sha256': rows[page]['image_sha256'],
            'native_json': str(old / f'page-{page}_res.json'),
            'markdown': str(old / f'page-{page}.md'),
            'prior_metrics': expected_row})
    write_json(progress_path, progress)
    runner = Path(__file__).with_name('run_ocr_cpu_trial.sh')
    new_attempts = 0
    for page in args.pages:
        if page in (6, 10, 30):
            continue
        key = str(page)
        record = progress['pages'].get(key)
        if record and record.get('status') == 'SUCCEEDED':
            if record.get('input_image_sha256') != rows[page]['image_sha256']:
                raise SystemExit(f'completed page {page} has a changed input digest')
            continue
        if record:
            # Failed/time-limited attempts remain immutable and are never retried
            # automatically. A resumed run advances to the next unattempted page.
            continue
        if new_attempts >= args.max_new_pages:
            break
        target = output / f'page-{page}-attempt-1'
        started = time.monotonic()
        started_unix = time.time()
        result = subprocess.run([str(runner), 'ppstructurev3', args.expected_image_id,
                                 str(models), str(images), str(target), str(page)],
                                text=True, capture_output=True)
        attempt = {'physical_page': page, 'input_image_sha256': rows[page]['image_sha256'],
                   'attempt': 1, 'started_unix_seconds': started_unix,
                   'wall_seconds': time.monotonic() - started, 'exit_code': result.returncode,
                   'runner_stdout': result.stdout[-4000:], 'runner_stderr': result.stderr[-4000:],
                   'result_directory': str(target)}
        receipt_path = target / 'run-receipt.json'
        if receipt_path.is_file():
            attempt['receipt'] = json.loads(receipt_path.read_text())
            attempt['status'] = attempt['receipt'].get('status')
        else:
            attempt['status'] = 'FAILED_BEFORE_RECEIPT'
        progress['pages'][key] = attempt
        write_json(progress_path, progress)
        new_attempts += 1
        print(json.dumps({'page': page, 'status': attempt['status'],
                          'wall_seconds': attempt['wall_seconds']}, ensure_ascii=False), flush=True)
        if attempt['status'] == 'FAILED_BEFORE_RECEIPT' and not target.exists():
            attempt['status'] = 'STOPPED_BEFORE_CONTAINER'
            write_json(progress_path, progress)
            print(f'Stopping: pre-container gate failed for physical page {page}', file=sys.stderr)
            break
        # Continue after terminal errors: each following page is a separate
        # attempt/container, and the original failure remains checkpointed.
    return progress


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--expected-image-id', required=True)
    parser.add_argument('--max-new-pages', type=int, default=1)
    parser.add_argument('--pages', nargs='+', type=int, required=True)
    args = parser.parse_args()
    if len(set(args.pages)) != 20 or any(page < 1 for page in args.pages):
        parser.error('--pages must be exactly 20 distinct positive physical pages')
    if args.max_new_pages < 1:
        parser.error('--max-new-pages must be positive')
    run(args)


if __name__ == '__main__':
    main()
