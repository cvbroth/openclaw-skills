"""Distinguish OCR/assembly omissions from Markdown export omissions."""
import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    'ocr_export_audit', Path(__file__).resolve().parents[1] / 'scripts/audit_ocr_native_export.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_native_assembly_and_export_omissions_are_separate(tmp_path):
    native = tmp_path / 'result.json'
    markdown = tmp_path / 'result.md'
    native.write_text(json.dumps({'parsing_res_list': [
        {'block_content': '1. 合成题'}, {'block_content': 'A.甲 B.乙'},
        {'block_content': 'C.丙 D.丁'}],
        'overall_ocr_res': {'rec_texts': ['1. 合成题', 'A.甲 B.乙', 'C.丙 D.丁', '合成页边']},
        'model_settings': {'use_chart_recognition': False}}))
    markdown.write_text('1. 合成题\n\nC.丙 D.丁\n\nA.甲 B.乙')
    result = MODULE.audit(native, markdown)
    assert len(result['raw_ocr_lines_not_found_in_parsing_sha256']) == 1
    assert result['markdown_missing_or_reordered_block_indices'] == [2]
    assert result['candidate_question_numbers'] == ['1']
    assert result['option_prefix_sequence'] == ['A.', 'B.', 'C.', 'D.']
