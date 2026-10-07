"""Synthetic reproduction of the pinned VL processor's scalar expression.

No input text, model weights or patched installed packages. Run under both
baseline and candidate images; NumPy 2.4 release notes explain the boundary.
"""
import importlib.metadata
import json

import numpy as np
import paddle

value = paddle.to_tensor([1, 10, 10]).prod() // 2 // 2
array = np.array(value)
report = {
    'versions': {name: importlib.metadata.version(name)
                 for name in ('numpy', 'paddlepaddle', 'paddlex', 'paddleocr')},
    'expression': 'paddle.to_tensor([1, 10, 10]).prod() // 2 // 2',
    'tensor_shape': list(value.shape), 'array_shape': list(array.shape),
    'array_size': array.size,
    'numpy_requirements': {name: [r for r in importlib.metadata.requires(name) or []
                                 if 'numpy' in r.lower()]
                           for name in ('paddlepaddle', 'paddlex', 'scipy')},
}
try:
    report['int_result'] = int(value)
except Exception as error:
    report.update(error_type=type(error).__name__, error=str(error))
print(json.dumps(report, indent=2))
