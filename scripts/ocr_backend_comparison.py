"""Minimal loss-conscious research adapters and offline comparison, no API calls.

Raw text/native results remain separate; this module never corrects transcription.
"""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_blocks(items, page, coordinate_system=None):
    blocks = []
    for index, item in enumerate(items):
        text = item.get('text', item.get('block_content', item.get('content', '')))
        if not isinstance(text, str):
            raise ValueError('NON_TEXT_BLOCK requires an explicit native adapter')
        blocks.append({'id': f'p{page:03}-b{index + 1:04}',
                       'type': item.get('type', item.get('block_label', item.get('label', 'unprovided'))),
                       'text': text, 'reading_order': index,
                       'native_coordinates': item.get('bbox', item.get('block_bbox')),
                       'coordinate_system': coordinate_system,
                       'image_references': item.get('image_references', []),
                       'native_order': item.get('block_order', item.get('index'))})
    return blocks


def diagnostics(text):
    lines = [line for line in text.splitlines() if line.strip()]
    repeats = sorted({line for line in lines if len(line) >= 24 and lines.count(line) > 1})
    numbers = [int(n) for n in re.findall(r'(?m)^\s*(?:#+\s*)?(\d+)[.．、]', text)]
    return {'empty': not text.strip(), 'characters': len(text),
            'question_prefix_candidates': numbers,
            'option_prefix_candidates': {letter: len(re.findall(rf'(?<![A-Za-z]){letter}[.．、]', text))
                                         for letter in 'ABCD'},
            'duplicate_long_line_count': len(repeats),
            'question_number_resets': sum(a >= b for a, b in zip(numbers, numbers[1:])),
            'interpretation': 'pattern alerts only; resets may be legitimate; not content correctness or verified question counts'}


def adapt_mineru(folder, page):
    """Use the tool's own structured export, preserving original native trees.

    DocVortex 2.0 block bbox is normalized xyxy; native point dimensions remain
    in the original extensions (PNG is internally wrapped as PDF by MinerU).
    """
    native = json.loads((folder / 'structured_content.json').read_bytes())
    if len(native['pages']) != 1:
        raise ValueError('ONE_IMAGE_ONE_PAGE_EXPECTED')
    items = native['pages'][0]['blocks']
    # Exported text is already a string. A non-string structural block is kept
    # as nontext in the adapter; its complete body remains in native JSON.
    rows = []
    for item in items:
        text = item.get('content')
        rows.append({**item, 'text': text if isinstance(text, str) else '',
                     'image_references': [item['image_path']] if item.get('image_path') else []})
    blocks = normalize_blocks(rows, page, 'native DocVortex normalized xyxy [0,1], origin top-left')
    (folder / 'blocks.json').write_text(json.dumps(blocks, ensure_ascii=False, indent=2))
    return blocks


def adapt_paddle(folder, page):
    """Adapt only completed native page output; never assemble partial regions."""
    candidates = list(folder.glob('*_res.json'))
    if len(candidates) != 1:
        raise ValueError('ONE_COMPLETED_NATIVE_PAGE_REQUIRED')
    native = json.loads(candidates[0].read_bytes())
    native = native.get('res', native)
    if 'parsing_res_list' not in native:
        raise ValueError('NATIVE_PARSING_BLOCKS_MISSING')
    blocks = normalize_blocks(native['parsing_res_list'], page,
                              'native source-image pixel xyxy, origin top-left')
    (folder / 'blocks.json').write_text(json.dumps(blocks, ensure_ascii=False, indent=2))
    markdown = [path for path in folder.glob('*.md') if path.name != 'raw.md']
    if len(markdown) != 1:
        raise ValueError('ONE_NATIVE_MARKDOWN_REQUIRED')
    shutil.copy2(markdown[0], folder / 'raw.md')
    return blocks


def import_m3(experiment, manifest, output):
    output.mkdir(parents=True, exist_ok=True)
    source_manifest = json.loads((experiment / 'manifest.json').read_bytes())
    if source_manifest['source_pdf_sha256'] != manifest['source_pdf_sha256']:
        raise ValueError('SOURCE_DOCUMENT_MISMATCH')
    source_images = {x['physical_page']: x for x in source_manifest['images']}
    for image in manifest['images']:
        page = image['physical_page']
        folder = output / f'page-{page}'
        folder.mkdir(exist_ok=True)
        if page not in source_images:
            (folder / 'receipt.json').write_text(json.dumps({'status': 'HISTORICAL_RESULT_MISSING', 'new_calls': 0}))
            continue
        if image['sha256'] != source_images[page]['sha256']:
            raise ValueError('M3_IMAGE_MISMATCH')
        attempts = sorted((experiment / 'attempts' / f'page-{page}').glob('attempt-*'),
                          key=lambda path: int(path.name.split('-')[-1]))
        if not attempts:
            raise ValueError('SOURCE_RECEIPT_MISSING')
        for attempt in attempts:
            dest = folder / attempt.name
            dest.mkdir(exist_ok=True)
            for name in ('response.raw.json', 'receipt.json', 'transcription.txt'):
                source = attempt / name
                if source.exists():
                    shutil.copy2(source, dest / name)
        latest = attempts[-1]
        receipt = json.loads((latest / 'receipt.json').read_bytes())
        receipt.update(reused_history=True, input_sha256=image['sha256'], new_calls=0)
        (folder / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
        text_path = latest / 'transcription.txt'
        if text_path.exists():
            raw = json.loads((latest / 'response.raw.json').read_bytes())
            raw_text = '\n'.join(x['text'] for x in raw.get('content', []) if x.get('type') == 'text')
            if text_path.read_text() != raw_text:
                raise ValueError('RAW_RESPONSE_TEXT_MISMATCH')
            shutil.copy2(text_path, folder / 'raw.md')
            (folder / 'blocks.json').write_text(json.dumps(
                normalize_blocks([{'text': raw_text, 'type': 'unsegmented_transcription'}], page),
                ensure_ascii=False, indent=2))


def aggregate(manifest, root, method):
    pages, markdown = [], []
    for image in manifest['images']:
        page = image['physical_page']
        folder = root / f'page-{page}'
        raw = folder / 'raw.md'
        native_blocks = folder / 'blocks.json'
        receipt_path = folder / 'receipt.json'
        receipt = json.loads(receipt_path.read_bytes()) if receipt_path.exists() else {'status': 'NOT_RUN'}
        blocks = json.loads(native_blocks.read_bytes()) if native_blocks.exists() else []
        text = raw.read_text() if raw.exists() else ''
        pages.append({'physical_page': page, 'printed_page': image.get('printed_page'),
                      'input_image': image['image'], 'input_sha256': image['sha256'],
                      'source_page_dimensions': [image['width'], image['height']],
                      'receipt': receipt, 'blocks': blocks,
                      'diagnostics': diagnostics(text) if raw.exists() else None,
                      'raw_markdown_sha256': sha(raw) if raw.exists() else None,
                      'coordinates_provided': any(b['native_coordinates'] is not None for b in blocks)})
        if raw.exists():
            markdown.append(f'<!-- physical page {page}; raw transcription below -->\n' + text)
    document = {'schema': 'ocr-comparison-minimal-v1', 'method': method,
                'document_id': manifest['document_id'], 'source_pdf_sha256': manifest['source_pdf_sha256'],
                'conversion': 'source text unchanged; page comments are transport delimiters, not original text; native JSON preserved',
                'pages': pages}
    root.mkdir(parents=True, exist_ok=True)
    (root / 'structure.json').write_text(json.dumps(document, ensure_ascii=False, indent=2))
    (root / 'content.md').write_text('\n\n'.join(markdown))
    return document


def bundle(manifest_path, candidates, output):
    manifest = json.loads(manifest_path.read_bytes())
    if output.exists():
        raise ValueError('DELIVERY_ALREADY_EXISTS')
    output.mkdir(parents=True)
    shutil.copy2(manifest_path, output / 'manifest.json')
    shutil.copytree(manifest_path.parent / 'images', output / 'images')
    methods = []
    for name, path in candidates:
        structure = aggregate(manifest, path, name)
        shutil.copytree(path, output / name)
        for item in structure['pages']:
            raw = path / f"page-{item['physical_page']}" / 'raw.md'
            item['display_raw_markdown'] = raw.read_text() if raw.exists() else None
        methods.append(structure)
    # Inline data supports file:// without fetch or web services. Never HTML-insert model text.
    payload = json.dumps({'manifest': manifest, 'methods': methods}, ensure_ascii=False).replace('<', '\\u003c')
    page_links = ''.join(f'<option value="{p}">{p}</option>' for p in manifest['physical_pages'])
    source = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>OCR后端原始结果对照</title>
<style>body{font:16px "Microsoft YaHei","PingFang SC","Noto Sans CJK SC",sans-serif;margin:20px;background:#f5f5f5}main{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}section{min-width:0;background:white;padding:12px}img{width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}article{border-bottom:2px solid #ddd;padding-bottom:20px;margin-bottom:20px}details pre{font-size:12px}nav{position:sticky;top:0;background:white;padding:12px}.error{color:#a21}a{overflow-wrap:anywhere}</style>
<h1>OCR后端小规模对照</h1><p>原始文字未纠错。缺失、失败及未运行均不填正常；程序提示不代表人工验收。点击原图可放大。</p>
<nav>物理页 <select id="page">OPTIONS</select></nav><main><section><h2 id="source-title"></h2><a id="full" target="_blank"><img id="image"></a><p id="dimensions"></p></section><section id="methods"></section></main>
<script>const DATA=PAYLOAD;const select=document.getElementById('page');
function show(){const p=Number(select.value),im=DATA.manifest.images.find(x=>x.physical_page===p);document.getElementById('source-title').textContent='物理 '+p+' / 印刷 '+im.printed_page;document.getElementById('image').src=im.image;document.getElementById('full').href=im.image;document.getElementById('dimensions').textContent=im.width+'×'+im.height+' PNG / 220dpi / '+im.sha256;const parent=document.getElementById('methods');parent.replaceChildren();for(const method of DATA.methods){const item=method.pages.find(x=>x.physical_page===p),box=document.createElement('article'),h=document.createElement('h2'),status=document.createElement('pre'),pre=document.createElement('pre'),a=document.createElement('a');h.textContent=method.method;status.textContent=JSON.stringify(item.receipt,null,2);pre.textContent=item.display_raw_markdown??'无转写输出；请查看状态/日志';a.href=method.method+'/page-'+p+'/raw.md';a.textContent='原始Markdown（如有）；原生JSON/日志见同目录';const label=document.createElement('p'),details=document.createElement('details'),summary=document.createElement('summary');label.textContent='状态：'+item.receipt.status+' / 源输入 '+im.width+'×'+im.height+' PNG（内部处理见报告）';summary.textContent='展开原始回执';details.append(summary,status);box.append(h,label,details,pre);if(item.display_raw_markdown!==null){box.append(a);}const info=document.createElement('a');info.href=method.method+'/structure.json';info.textContent='统一结构JSON（含状态与原生坐标）';box.append(document.createElement('br'),info);parent.append(box);}}select.addEventListener('change',show);show();</script></html>'''
    (output / 'index.html').write_text(source.replace('OPTIONS', page_links).replace('PAYLOAD', payload))
    (output / 'README.md').write_text('解压后离线打开index.html，选择物理页，点击原图放大。各候选目录含原始文件与structure.json/content.md。未提供坐标时为null；未运行不等于空识别。没有新增M3调用，没有人工审核状态或准确率声明。\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='action', required=True)
    m3 = sub.add_parser('import-m3')
    m3.add_argument('--experiment', type=Path, required=True)
    m3.add_argument('--manifest', type=Path, required=True)
    m3.add_argument('--output', type=Path, required=True)
    build = sub.add_parser('bundle')
    build.add_argument('--manifest', type=Path, required=True)
    build.add_argument('--candidate', action='append', required=True, help='safe-name=directory')
    build.add_argument('--output', type=Path, required=True)
    adapt = sub.add_parser('adapt-mineru')
    adapt.add_argument('--folder', type=Path, required=True)
    adapt.add_argument('--page', type=int, required=True)
    paddle = sub.add_parser('adapt-paddle')
    paddle.add_argument('--folder', type=Path, required=True)
    paddle.add_argument('--page', type=int, required=True)
    args = parser.parse_args()
    if args.action == 'import-m3':
        import_m3(args.experiment, json.loads(args.manifest.read_bytes()), args.output)
    elif args.action == 'adapt-mineru':
        adapt_mineru(args.folder, args.page)
    elif args.action == 'adapt-paddle':
        adapt_paddle(args.folder, args.page)
    else:
        pairs = []
        for item in args.candidate:
            name, path = item.split('=', 1)
            if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
                raise ValueError('UNSAFE_CANDIDATE_NAME')
            pairs.append((name, Path(path)))
        bundle(args.manifest, pairs, args.output)
