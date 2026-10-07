"""Text-free native-to-Markdown coverage evidence, not visual/CER acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def compact(text):
    return ''.join(text.split())


def audit(native_path, markdown_path):
    native = json.loads(native_path.read_bytes())
    blocks = native['parsing_res_list']
    body = '\n'.join(block['block_content'] for block in blocks)
    markdown = compact(markdown_path.read_text())
    cursor, missing = 0, []
    for index, block in enumerate(blocks):
        content = compact(block['block_content'])
        found = markdown.find(content, cursor)
        if found < 0:
            missing.append(index)
        else:
            cursor = found + len(content)
    assembled = compact(body)
    raw_missing = [hashlib.sha256(text.encode()).hexdigest()
                   for text in native['overall_ocr_res']['rec_texts']
                   if compact(text) and compact(text) not in assembled]
    return {
        'native_sha256': hashlib.sha256(native_path.read_bytes()).hexdigest(),
        'markdown_sha256': hashlib.sha256(markdown_path.read_bytes()).hexdigest(),
        'parsing_blocks': len(blocks), 'markdown_missing_or_reordered_block_indices': missing,
        'raw_ocr_lines_not_found_in_parsing_sha256': raw_missing,
        'candidate_question_numbers': re.findall(r'(?:^|\n)(\d+)[.．、]', body),
        'option_prefix_sequence': re.findall(r'[A-Da-d][.．、，]', body),
        'model_settings': native['model_settings'],
        'boundary': 'literal coverage only; candidate numbers/prefixes are not verified semantic structure',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--markdown', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(audit(args.native, args.markdown), indent=2) + '\n')
