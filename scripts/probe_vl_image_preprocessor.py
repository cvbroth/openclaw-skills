"""Diagnose the original processor on an image, without loading VLM weights.

Tracing observes the unmodified Paddle __int__ call and preserves its exception.
This is a preprocessing diagnostic, never a completed OCR inference.
"""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
from paddlex.inference.models.doc_vlm.predictor import DocVLMPredictor

parser = argparse.ArgumentParser()
parser.add_argument('--model', type=Path, required=True)
parser.add_argument('--image', type=Path, required=True)
args = parser.parse_args()
context = SimpleNamespace(model_name='PaddleOCR-VL-1.5-0.9B', model_dir=args.model,
                          model_group={'PP-DocBee': [], 'PP-Chart2Table': [],
                                       'PP-DocBee2': [], 'PaddleOCR-VL': ['PaddleOCR-VL-1.5-0.9B']})
processor = DocVLMPredictor.build_processor(context)
observed = []


def trace(frame, event, arg):
    if event == 'call' and frame.f_code.co_name == '_int_' and frame.f_code.co_filename.endswith('math_op_patch.py'):
        tensor = frame.f_locals['var']
        array = np.array(tensor)
        observed.append({'call_file': frame.f_code.co_filename, 'call_line': frame.f_code.co_firstlineno,
                         'caller_file': frame.f_back.f_code.co_filename, 'caller_line': frame.f_back.f_lineno,
                         'tensor_shape': list(tensor.shape), 'array_shape': list(array.shape), 'size': array.size})
    return trace


sys.settrace(trace)
try:
    processor.preprocess([{'image': str(args.image), 'query': 'OCR:'}])
    outcome = {'preprocess': 'SUCCEEDED'}
except Exception as error:
    outcome = {'preprocess': 'FAILED', 'error_type': type(error).__name__, 'error': str(error)}
finally:
    sys.settrace(None)
print(json.dumps({'numpy': np.__version__, 'observed_int_calls': observed, **outcome}, indent=2))
