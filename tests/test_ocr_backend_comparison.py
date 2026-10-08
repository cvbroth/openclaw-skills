"""Synthetic research adapters: no book text or model dependency."""
import hashlib
import concurrent.futures
import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
SPEC = importlib.util.spec_from_file_location('comparison', Path(__file__).parents[1] / 'scripts/ocr_backend_comparison.py')
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def manifest():
    return {'document_id': 'synthetic', 'source_pdf_sha256': 'source', 'physical_pages': [9, 10],
            'images': [{'physical_page': p, 'printed_page': p - 5, 'image': f'images/page-{p}.png',
                        'width': 100, 'height': 200, 'sha256': f'image-{p}'} for p in (9, 10)]}


def test_native_coordinates_and_verbatim_unicode():
    raw = 'A. 不应改写\nB．① ② <script> &'
    items = [{'block_content': raw, 'block_bbox': [10, 20, 30, 40], 'block_label': 'text', 'block_order': 7}]
    block = comparison.normalize_blocks(items, 9, 'native pixels')[0]
    assert block['text'] == raw
    assert block['native_coordinates'] == [10, 20, 30, 40]
    assert block['native_order'] == 7
    assert comparison.normalize_blocks([{'text': raw}], 10)[0]['native_coordinates'] is None
    assert block['id'] != comparison.normalize_blocks(items, 10)[0]['id']
    assert items[0]['block_content'] == raw


def test_failed_pages_are_unknown_not_empty_recognition(tmp_path):
    write(tmp_path / 'page-9/receipt.json', {'status': 'TIMED_OUT', 'elapsed_seconds': 300})
    value = comparison.aggregate(manifest(), tmp_path, 'synthetic')
    assert value['pages'][0]['receipt']['status'] == 'TIMED_OUT'
    assert value['pages'][1]['receipt']['status'] == 'NOT_RUN'
    assert value['pages'][1]['raw_markdown_sha256'] is None
    assert value['pages'][1]['blocks'] == []
    assert value['pages'][0]['diagnostics'] is None
    assert value['pages'][1]['diagnostics'] is None


def test_number_reset_is_only_anomaly_not_dropped_content():
    text = '12. one\nA. 否\nB. 非\n1. two\nA. 123\nB. 不'
    result = comparison.diagnostics(text)
    assert result['question_number_resets'] == 1
    assert result['option_prefix_candidates']['A'] == 2
    assert 'not content correctness' in result['interpretation']


def test_m3_reuse_checks_source_and_raw_response(tmp_path):
    incoming, output = tmp_path / 'historical', tmp_path / 'output'
    m = manifest()
    write(incoming / 'manifest.json', m)
    for p in (9, 10):
        folder = incoming / f'attempts/page-{p}/attempt-1'
        write(folder / 'receipt.json', {'status': 'succeeded'})
        write(folder / 'response.raw.json', {'content': [{'type': 'text', 'text': '原始不改写'}]})
        (folder / 'transcription.txt').write_text('原始不改写')
    comparison.import_m3(incoming, m, output)
    assert (output / 'page-9/raw.md').read_text() == '原始不改写'
    assert json.loads((output / 'page-9/receipt.json').read_text())['new_calls'] == 0
    (incoming / 'attempts/page-9/attempt-1/transcription.txt').write_text('被改写')
    with pytest.raises(ValueError, match='RAW_RESPONSE_TEXT_MISMATCH'):
        comparison.import_m3(incoming, m, tmp_path / 'rejected')
    m['source_pdf_sha256'] = 'different'
    with pytest.raises(ValueError, match='SOURCE_DOCUMENT_MISMATCH'):
        comparison.import_m3(incoming, m, tmp_path / 'wrong-source')


def test_bundle_no_fetch_safe_text_and_original_bytes(tmp_path):
    m = manifest()
    write(tmp_path / 'manifest.json', m)
    images = tmp_path / 'images'
    images.mkdir()
    (images / 'page-9.png').write_bytes(b'synthetic image bytes')
    method = tmp_path / 'candidate'
    raw = '</script><script>alert("x")</script>\nA．不应规范化'
    write(method / 'page-9/blocks.json', comparison.normalize_blocks([{'text': raw}], 9))
    (method / 'page-9/raw.md').write_text(raw)
    before = comparison.sha(method / 'page-9/raw.md')
    comparison.bundle(tmp_path / 'manifest.json', [('local', method)], tmp_path / 'delivery')
    source = (tmp_path / 'delivery/index.html').read_text()
    assert '</script><script>alert' not in source
    assert '\\u003c/script>' in source
    assert 'fetch(' not in source
    assert '.textContent=' in source
    assert comparison.sha(tmp_path / 'delivery/local/page-9/raw.md') == before
    assert hashlib.sha256(raw.encode()).hexdigest() == before


def test_concurrent_region_capture_keeps_call_identity(tmp_path):
    sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
    from run_ocr_backend_comparison import generation_capture
    from PIL import Image

    def original(image, question, *args):
        time.sleep(.02)
        return 'raw:' + question

    capture = generation_capture(original, lambda image, **kwargs: image, tmp_path, lambda: 12)
    incoming = Image.new('RGB', (28, 28), 'white')
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda index: capture(incoming, f'synthetic-{index}'), range(24)))
    records = [json.loads(path.read_text()) for path in (tmp_path / 'page-12/raw-generations').glob('*.json')]
    assert len(records) == len(values) == 24
    assert len({r['prompt'] for r in records}) == 24
    assert all(r['status'] == 'SUCCEEDED' and r['raw_text'] == 'raw:' + r['prompt'] for r in records)


def test_mineru_native_export_keeps_headers_and_normalized_coords(tmp_path):
    native = {'pages': [{'blocks': [
        {'type': 'header', 'bbox': [.1, .1, .5, .2], 'content': '合成标题', 'index': 0},
        {'type': 'text', 'bbox': [.1, .2, .9, .8], 'content': 'A. 不改字\nB. 123', 'index': 1},
        {'type': 'image', 'bbox': [.2, .3, .5, .8], 'content': {'native': 'preserved elsewhere'}, 'index': 2}]}]}
    write(tmp_path / 'structured_content.json', native)
    before = comparison.sha(tmp_path / 'structured_content.json')
    blocks = comparison.adapt_mineru(tmp_path, 12)
    assert len(blocks) == 3
    assert blocks[0]['type'] == 'header'
    assert blocks[1]['text'] == 'A. 不改字\nB. 123'
    assert blocks[2]['text'] == '' and blocks[2]['type'] == 'image'
    assert comparison.sha(tmp_path / 'structured_content.json') == before


def test_resume_archives_partial_raw_output_preserves_completed_pages(tmp_path):
    from run_ocr_backend_comparison import archive_attempt
    write(tmp_path / 'run-receipt.json', {'status': 'TIMED_OUT'})
    write(tmp_path / 'page-9/page-receipt.json', {'status': 'SUCCEEDED'})
    (tmp_path / 'page-9/raw.md').write_text('completed synthetic')
    (tmp_path / 'page-10').mkdir()
    (tmp_path / 'page-10/raw.log').write_text('partial synthetic')
    target = archive_attempt(tmp_path)
    assert (tmp_path / 'page-9/raw.md').read_text() == 'completed synthetic'
    assert (target / 'page-10/raw.log').read_text() == 'partial synthetic'
    assert not (tmp_path / 'page-10').exists()
    assert json.loads((target / 'run-receipt.json').read_text())['status'] == 'TIMED_OUT'


def test_shape_observer_handles_native_list_without_altering_feed():
    import numpy as np
    from run_ocr_backend_comparison import tensor_description
    feed = [[1, 2], [3, 4]]
    assert tensor_description(feed)['shape'] == [2, 2]
    assert feed == [[1, 2], [3, 4]]
    tensor = np.zeros((1, 3, 800, 800), dtype=np.float32)
    assert tensor_description(tensor) == {'shape': [1, 3, 800, 800], 'dtype': 'float32'}


def test_paddle_adapter_requires_completed_page_keeps_raw_coordinates(tmp_path):
    with pytest.raises(ValueError, match='ONE_COMPLETED_NATIVE_PAGE_REQUIRED'):
        comparison.adapt_paddle(tmp_path,12)
    native={'res':{'width':1819,'height':2573,'parsing_res_list':[
        {'block_label':'text','block_content':'合成 A. 不改字','block_bbox':[20,30,400,200],'block_order':1}]}}
    write(tmp_path/'page-12_res.json',native)
    (tmp_path/'page-12.md').write_text('原始 **合成** A. 不改字\n')
    before=comparison.sha(tmp_path/'page-12.md')
    result=comparison.adapt_paddle(tmp_path,12)
    assert result[0]['text']=='合成 A. 不改字'
    assert result[0]['native_coordinates']==[20,30,400,200]
    assert result[0]['native_order']==1
    assert comparison.sha(tmp_path/'raw.md')==before
    assert json.loads((tmp_path/'page-12_res.json').read_bytes())==native


def test_monkey_native_coordinates_remain_in_preprocessed_frame(tmp_path):
    write(tmp_path/'jsons/page.json',{'layouts':[{'content':'A. 不改写','label':'Text','bbox':[1,2,3,4]}, {'content':'![image](../images/native.jpg)','label':'Picture','bbox':[5,6,7,8]}]})
    (tmp_path/'markdowns').mkdir()
    (tmp_path/'markdowns/page.md').write_text('A. 不改写\n')
    blocks=comparison.adapt_monkey(tmp_path,23)
    assert blocks[0]['text']=='A. 不改写'
    assert blocks[0]['native_coordinates']==[1,2,3,4]
    assert 'preprocessed-page' in blocks[0]['coordinate_system']
    assert blocks[1]['image_references']==['../images/native.jpg']
    assert (tmp_path/'raw.md').read_bytes()==(tmp_path/'markdowns/page.md').read_bytes()


def test_monkey_partial_is_labelled_verbatim_and_does_not_invent_coordinates(tmp_path):
    folder=tmp_path/'page-23'
    raw=folder/'raw-generations'
    raw.mkdir(parents=True)
    (raw/'0001-text.txt').write_text('layout raw')
    (raw/'0002-text.txt').write_text('A. 仍是原始字\nB. 不改写')
    events=[{'name':'request','state':'started','call':1,'query':'categories and coordinates'},
            {'name':'request','state':'completed','call':1},
            {'name':'request','state':'started','call':2,'query':'text'},
            {'name':'request','state':'completed','call':2},
            {'name':'request','state':'started','call':3,'query':'text'}]
    (tmp_path/'phase-events.jsonl').write_text('\n'.join(map(json.dumps,events)))
    blocks=comparison.adapt_monkey_partial(folder,tmp_path,23)
    assert len(blocks)==1 and blocks[0]['native_coordinates'] is None
    assert blocks[0]['text']==(raw/'0002-text.txt').read_text()
    assert '部分输出' in (folder/'raw.md').read_text()
    assert 'layout raw' not in (folder/'raw.md').read_text()
    assert (raw/'0001-text.txt').read_text()=='layout raw'
    (raw/'0003-text.txt').write_text('not matched to completed call')
    with pytest.raises(ValueError,match='UNMATCHED_PARTIAL_CALL'):
        comparison.adapt_monkey_partial(folder,tmp_path,23)
