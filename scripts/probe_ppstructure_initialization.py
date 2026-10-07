"""Measure official per-model construction without changing model behavior.

Observer delegates to the original BasePipeline.create_model and is restored.
No page inference. This probe is separate from the successful three-page run.
"""
import argparse
import json
from pathlib import Path
import resource
import time

from paddlex.inference.pipelines.base import BasePipeline
from evaluate_paddleocr_vl import build_pipeline

parser = argparse.ArgumentParser()
parser.add_argument('--models', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
original = BasePipeline.create_model
rows = []


def current_rss_kib():
    return next(int(line.split()[1]) for line in Path('/proc/self/status').read_text().splitlines()
                if line.startswith('VmRSS:'))


def observe(self, config, *positional, **keywords):
    started, before = time.monotonic(), current_rss_kib()
    model = original(self, config, *positional, **keywords)
    rows.append({'model_name': config.get('model_name'),
                 'construction_seconds': time.monotonic() - started,
                 'rss_before_kib': before, 'rss_after_kib': current_rss_kib(),
                 'cumulative_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
    return model


BasePipeline.create_model = observe
try:
    pipeline = build_pipeline('ppstructurev3', args.models)
finally:
    BasePipeline.create_model = original
args.output.write_text(json.dumps({'purpose': 'observer-only initialization calibration; not OCR speed',
                                   'models': rows}, indent=2))
