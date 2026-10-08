import importlib.util
from pathlib import Path
import struct

import pytest


spec = importlib.util.spec_from_file_location('gguf_identity', Path(__file__).parents[1] / 'scripts/inspect_gguf_metadata.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def string(text):
    data = text.encode()
    return struct.pack('<Q', len(data)) + data


def test_metadata_and_mixed_tensor_types_without_token_text(tmp_path):
    path = tmp_path / 'synthetic.gguf'
    data = b'GGUF' + struct.pack('<IQQ', 3, 2, 2)
    data += string('general.architecture') + struct.pack('<I', 8) + string('synthetic')
    data += string('tokenizer.ggml.tokens') + struct.pack('<IIQ', 9, 8, 1) + string('PRIVATE_TOKEN_TEXT')
    data += string('tensor1') + struct.pack('<IQQIQ', 2, 2, 3, 8, 0)
    data += string('tensor2') + struct.pack('<IQIQ', 1, 4, 1, 0)
    path.write_bytes(data)
    result = module.inspect(path)
    assert result['total_tensor_elements'] == 10
    assert result['tensor_type_counts'] == {8: 1, 1: 1}
    assert result['metadata'] == {'general.architecture': 'synthetic'}
    assert 'PRIVATE_TOKEN_TEXT' not in str(result)


def test_reject_wrong_format(tmp_path):
    path = tmp_path / 'bad.gguf'
    path.write_bytes(b'NOPE')
    with pytest.raises(ValueError, match='NOT_GGUF'):
        module.inspect(path)
