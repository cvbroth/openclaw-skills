"""Whitelist public measurements; leave raw images/business responses private."""
import argparse
import json
from pathlib import Path


def summarize(root):
    def read(name):
        path = root / name
        return json.loads(path.read_bytes()) if path.exists() else None

    calls = []
    for path in sorted(root.glob('page-*/raw-generations/*/receipt.json')):
        value = json.loads(path.read_bytes())
        response_path = path.parent / 'response.json'
        response = json.loads(response_path.read_bytes()) if response_path.exists() else {}
        calls.append({'call': str(path.parent.relative_to(root)),
                      **{key: value[key] for key in ('status', 'images', 'capture_seconds', 'elapsed_seconds',
                         'finish_reason', 'tokens_evaluated', 'tokens_predicted', 'error_type') if key in value},
                      'engine_timings': response.get('timings'),
                      'returned_characters': len(response['content']) if 'content' in response else None})
    phases_path = root / 'standard-phases.jsonl'
    phases = [json.loads(line) for line in phases_path.read_text().splitlines()] if phases_path.exists() else []
    return {'receipt': read('run-receipt.json'), 'metrics': read('metrics.json'),
            'engine_settings': read('engine-settings.json'), 'phases': phases, 'calls': calls,
            'interpretation': 'nested timings are not additive; prompt_ms is not isolated vision encoder time; '
                              'missing metrics are unknown; no accuracy claim'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(summarize(args.folder), ensure_ascii=False, indent=2))
