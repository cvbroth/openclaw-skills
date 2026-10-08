"""Sanitized phase measurements; never infer OCR correctness or missing timings."""
import argparse
import json
from pathlib import Path


def summarize(folder):
    metrics = json.loads((folder/'metrics.json').read_bytes()) if (folder/'metrics.json').exists() else None
    receipt = json.loads((folder/'run-receipt.json').read_bytes()) if (folder/'run-receipt.json').exists() else None
    events = [json.loads(line) for line in (folder/'phase-events.jsonl').read_text().splitlines()] if (folder/'phase-events.jsonl').exists() else []
    phases = []
    for event in events:
        if event['name'] in ('layout_analysis','vision_encoding','generate','region','language_generation'):
            phases.append({key:event[key] for key in ('page','region','name','state','monotonic','process_cpu_seconds','wall_seconds','cpu_seconds','batch_box_counts','language_steps','language_wall','language_cpu','generated_token_shape','reached_configured_token_limit') if key in event})
    return {'metrics':metrics,'receipt':receipt,'phases':phases,
            'interpretation':'nested timings are not additive; language forward omits sampling/projector overhead; absence is unknown, not zero; no OCR accuracy claim'}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.write_text(json.dumps(summarize(args.folder),ensure_ascii=False,indent=2))
