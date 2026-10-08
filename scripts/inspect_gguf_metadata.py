"""Read GGUF identity/tensor metadata without loading weights or token strings."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import struct


def inspect(path, selected_token_ids=()):
    with path.open('rb') as stream:
        def number(fmt):
            size = struct.calcsize('<' + fmt)
            return struct.unpack('<' + fmt, stream.read(size))[0]

        def string(keep=True):
            size = number('Q')
            if keep:
                return stream.read(size).decode()
            stream.seek(size, 1)

        def value(kind, keep=True):
            scalar = {0: 'B', 1: 'b', 2: 'H', 3: 'h', 4: 'I', 5: 'i', 6: 'f', 7: '?', 10: 'Q', 11: 'q', 12: 'd'}
            if kind in scalar:
                return number(scalar[kind])
            if kind == 8:
                return string(keep)
            if kind == 9:
                subtype, count = number('I'), number('Q')
                if keep and count <= 32:
                    return [value(subtype) for _ in range(count)]
                for _ in range(count):
                    value(subtype, False)
                return {'array_count': count, 'type': subtype}
            raise ValueError('UNSUPPORTED_GGUF_VALUE_TYPE')

        if stream.read(4) != b'GGUF':
            raise ValueError('NOT_GGUF')
        version, count, metadata_count = number('I'), number('Q'), number('Q')
        if version != 3:
            raise ValueError('ONLY_GGUF_V3_SUPPORTED')
        metadata = {}
        selected_tokens = {}
        for _ in range(metadata_count):
            key = string()
            kind = number('I')
            if key == 'tokenizer.ggml.tokens' and selected_token_ids:
                if kind != 9 or number('I') != 8:
                    raise ValueError('EXPECTED_STRING_TOKEN_ARRAY')
                token_count = number('Q')
                for index in range(token_count):
                    token = string(index in selected_token_ids)
                    if index in selected_token_ids:
                        selected_tokens[index] = token
                continue
            kept = not key.startswith('tokenizer.')
            item = value(kind, kept)
            if kept:
                metadata[key] = item
        types, elements = Counter(), Counter()
        for _ in range(count):
            string(False)
            dimensions = number('I')
            shape = [number('Q') for _ in range(dimensions)]
            kind = number('I')
            number('Q')
            types[kind] += 1
            elements[kind] += math.prod(shape)
    return {'gguf_version': version, 'metadata': metadata, 'tensor_count': count,
            'explicitly_selected_tokens': selected_tokens,
            'tensor_type_counts': dict(types), 'tensor_elements_by_type': dict(elements),
            'total_tensor_elements': sum(elements.values()),
            'scope': 'stored tensor metadata; not runtime accumulator precision or independent upstream weight equivalence'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--token-id', type=int, action='append', default=[])
    args = parser.parse_args()
    args.output.write_text(json.dumps(inspect(args.path, set(args.token_id)), indent=2))
