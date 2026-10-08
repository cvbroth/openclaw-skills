"""Whitelist public runtime metrics; never export transcription/context/token IDs."""
import argparse
import json
from pathlib import Path


def summarize(root):
    receipt = json.loads((root / 'receipt.json').read_bytes())
    resource = json.loads((root / 'final-resources.json').read_bytes())
    terminal = receipt.get('terminal', {})
    cgroup = resource['cgroup']
    cpu = dict(line.split() for line in cgroup['cpu.stat'].splitlines())
    samples = [json.loads(line) for line in (root / 'resources.jsonl').read_text().splitlines()]
    high_water = []
    for sample in samples:
        for process in sample.get('processes', []):
            value = process.get('VmHWM', '')
            if value:
                high_water.append(int(value.split()[0]))
    native = {key: terminal[key] for key in ('model', 'done', 'done_reason', 'total_duration', 'load_duration',
              'prompt_eval_count', 'prompt_eval_duration', 'eval_count', 'eval_duration') if key in terminal}
    wall = resource['elapsed_seconds_including_shutdown']
    return {'status': receipt['status'], 'elapsed_seconds': receipt['elapsed_seconds'],
            'elapsed_seconds_including_shutdown': wall, 'request_seconds': receipt['request_seconds'],
            'output_characters': receipt['output_characters'], 'native_timing_ns_and_counts': native,
            'cgroup_peak_bytes': int(cgroup['memory.peak']),
            'cgroup_swap_peak_bytes': int(cgroup['memory.swap.peak']),
            'cgroup_memory_events': cgroup['memory.events'],
            'cgroup_cpu_seconds': int(cpu['usage_usec']) / 1e6,
            'average_cpu_cores': int(cpu['usage_usec']) / 1e6 / wall,
            'sampled_process_high_water_max_kib': max(high_water, default=None),
            'child_maxrss_kib': resource['child_maxrss_kib'],
            'child_cpu_seconds': resource['child_cpu_seconds'],
            'scope': 'native API intervals are nested; prompt_eval is not independently measured visual encoder; process high-water sampling and cgroup peak have different scopes'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(summarize(args.root), ensure_ascii=False, indent=2))
