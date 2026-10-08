import importlib.util
import json
from pathlib import Path


spec = importlib.util.spec_from_file_location('glm_summary', Path(__file__).parents[1] / 'scripts/summarize_glm_ocr_trial.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_summary_whitelists_metrics_not_body_or_context(tmp_path):
    receipt = {'status': 'SUCCEEDED', 'elapsed_seconds': 2, 'request_seconds': 1,
               'output_characters': 13, 'terminal': {'model': 'synthetic', 'done': True,
               'done_reason': 'stop', 'response': 'PRIVATE_BODY', 'context': [1001],
               'eval_count': 13, 'extra': 'SECRET'}}
    resource = {'cgroup': {'cpu.stat': 'usage_usec 2000000\n', 'memory.peak': '4096',
                'memory.swap.peak': '0', 'memory.events': 'oom 0\n'},
                'elapsed_seconds_including_shutdown': 2.5, 'child_maxrss_kib': 4, 'child_cpu_seconds': 1.9}
    for name, value in [('receipt.json', receipt), ('final-resources.json', resource)]:
        (tmp_path/name).write_text(json.dumps(value))
    (tmp_path/'resources.jsonl').write_text(json.dumps({'processes': [{'VmHWM': '5 kB'}]})+'\n')
    summary = module.summarize(tmp_path)
    assert summary['average_cpu_cores'] == .8
    assert summary['sampled_process_high_water_max_kib'] == 5
    assert all(value not in json.dumps(summary) for value in ('PRIVATE_BODY', 'SECRET', '1001'))
