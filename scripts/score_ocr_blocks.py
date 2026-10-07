"""CER on explicitly image-verified private blocks, not whole-book accuracy.

Only whitespace is removed. Case, negations, numbers, circled numbers and
punctuation remain significant. Model confidence is never used as accuracy.
"""
import argparse
import hashlib
import json
from pathlib import Path


def character_errors(reference, hypothesis):
    reference, hypothesis = ''.join(reference.split()), ''.join(hypothesis.split())
    if not reference:
        raise ValueError('EMPTY_VERIFIED_REFERENCE')
    previous = list(range(len(hypothesis) + 1))
    for index, expected in enumerate(reference, 1):
        current = [index]
        for column, actual in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + (expected != actual)))
        previous = current
    edits = previous[-1]
    return {'reference_characters': len(reference), 'edit_distance': edits, 'cer': edits / len(reference),
            'normalization': 'whitespace only; all other Unicode characters significant'}


def score(path, output):
    annotated = json.loads(path.read_bytes())
    rows = []
    for block in annotated['blocks']:
        if block.get('image_verified') is not True or not block.get('reference_image_sha256') or not block.get('review_method'):
            raise ValueError('IMAGE_REFERENCE_REVIEW_REQUIRED')
        row = {k: block[k] for k in ('id', 'physical_page', 'reference_image_sha256', 'review_method')}
        row['reference_sha256'] = hashlib.sha256(block['reference'].encode()).hexdigest()
        row['engines'] = {engine: character_errors(block['reference'], text) if text is not None else
                         {'status': 'no completed recognition; CER unavailable'}
                         for engine, text in block['hypotheses'].items()}
        row['completeness'] = block.get('completeness', {})
        rows.append(row)
    output.write_text(json.dumps({'scope': 'selected image-verified blocks only; not entire pages/book',
                                  'annotation_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'blocks': rows}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--annotations', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    score(args.annotations, args.output)
