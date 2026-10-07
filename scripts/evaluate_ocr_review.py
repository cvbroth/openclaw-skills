"""Result-only regression/CER and position-aligned preprocessing comparison.

Private text stays in --output; the separate public summary contains only
coordinates, counts, scores and hashes. Inputs are explicit manifests, never
NAS/cache discovery. No OCR inference is invoked by this script.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nas_filetools.ocr_review import compare_lines, raw_lines, reading_rows, reconcile  # noqa: E402
from score_ocr_blocks import character_errors  # noqa: E402


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_path(page, record):
    return (Path(record['native_json']) if record.get('native_json') else
            Path(record['result_directory']) / f'page-{page}' / f'page-{page}_res.json')


def roi_hypothesis(native, block):
    w, h = native['width'], native['height']
    bw, bh = block['bbox_basis']
    box = [value * (w/bw if i % 2 == 0 else h/bh) for i, value in enumerate(block['bbox_on_basis'])]
    lines = [r for r in raw_lines(native) if box[0] <= (r['bbox'][0]+r['bbox'][2])/2 <= box[2]
             and box[1] <= (r['bbox'][1]+r['bbox'][3])/2 <= box[3]]
    hypothesis = '\n'.join(r['text'] for r in reading_rows(lines))
    if block.get('omit_ambiguous_question_prefix'):
        hypothesis = re.sub(r'^\s*\d+[.．、，]?', '', hypothesis)
    return hypothesis, [r['raw_index'] for r in lines], box


def evaluate(args):
    if args.output.exists() or args.public_summary.exists():
        raise ValueError('OUTPUT_EXISTS: preserve prior evidence')
    started = time.monotonic()
    args.output.mkdir(parents=True)
    progress = json.loads(args.batch.read_bytes())['pages']
    sources = {}
    page_rows = []
    for key, record in progress.items():
        page = int(key)
        if record['status'] not in ('SUCCEEDED', 'REUSED_PRIOR_SUCCESS'):
            raise ValueError(f'BASELINE_NOT_SUCCESSFUL:{page}')
        image_sha = digest(args.images/f'page-{page}.png')
        if image_sha != record['input_image_sha256']:
            raise ValueError(f'BASELINE_IMAGE_CHANGED:{page}')
        path = native_path(page, record)
        md = path.with_name(f'page-{page}.md')
        old_hash, old_md_hash = digest(path), digest(md)
        native = json.loads(path.read_bytes())
        tick = time.monotonic()
        result = reconcile(native, page, md.read_text())
        result['elapsed_seconds'] = time.monotonic()-tick
        sources[page] = native
        preserved = [{k:v for k,v in b.items() if k != 'original_index'} for b in result['repaired_blocks']
                     if 'original_index' in b]
        if preserved != native['parsing_res_list']:
            raise AssertionError('ORIGINAL_BLOCKS_CHANGED_OR_REORDERED')
        if result['structure']['covered_after'] < result['structure']['covered_before']:
            raise AssertionError('RECOGNIZED_COVERAGE_REGRESSED')
        if result['structure']['duplicate_regions']:
            raise AssertionError('OVERLAPPING_DUPLICATE_BLOCKS_REQUIRE_REVIEW')
        if any(r['reason'].startswith('restored row order') for r in result['structure']['order_candidates']):
            raise AssertionError('RESTORED_ORDER_REGRESSION')
        target = args.output/f'page-{page}'
        target.mkdir()
        (target/'repaired.md').write_text(result.pop('repaired_markdown'))
        (target/'review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        if digest(path) != old_hash or digest(md) != old_md_hash:
            raise AssertionError('ORIGINAL_EVIDENCE_CHANGED')
        s = result['structure']
        page_rows.append({'physical_page':page, 'image_sha256':image_sha, 'native_sha256':old_hash, 'original_markdown_sha256':old_md_hash,
                          'repaired_markdown_sha256':result['repaired_markdown_sha256'],
                          'covered_before':s['covered_before'], 'covered_after':s['covered_after'],
                          'raw_lines':s['raw_lines'], 'recovered_lines':s['recovered_lines'], 'pending_lines':s['pending_lines'],
                          'native_order_candidates_retained':len(s['order_candidates']),
                          'question_option_candidates':len(s['question_option_candidates']),
                          'duplicate_regions':len(s['duplicate_regions']),
                          'low_score_regions':len(result['low_score_regions']), 'review_status':result['review_status'],
                          'original_blocks_preserved_in_order':True, 'elapsed_seconds':result['elapsed_seconds']})
    reference = json.loads(args.reference.read_bytes())
    variants = json.loads(args.preprocessing_manifest.read_bytes()) if args.preprocessing_manifest else []
    variant_sources = {}
    comparisons = []
    runtimes = []
    for row in variants:
        page, variant = row['physical_page'], row['variant']
        path = args.inference/f'{variant}-page-{page}'/f'page-{page}'/f'page-{page}_res.json'
        if not path.exists():
            continue  # Explicitly reported as unavailable in block scores.
        processed = json.loads(path.read_bytes())
        variant_sources[(variant,page)] = processed
        comparison = compare_lines(sources[page],processed,row['processed_to_original'],page)
        (args.output/f'{variant}-page-{page}-comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2))
        comparisons.append({'physical_page':page,'variant':variant,'native_sha256':digest(path),
                            'matched_groups':len(comparison['matched']),
                            'changed_groups':sum(r['text_changed'] for r in comparison['matched']),
                            'critical_disagreement_groups':sum(r['critical_disagreement'] for r in comparison['matched']),
                            'original_unmatched':len(comparison['original_unmatched']),
                            'processed_unmatched':len(comparison['processed_unmatched']),
                            'split_merge_groups':sum(r['shape'] != [1,1] for r in comparison['matched']), 'winner':None})
        directory = path.parent.parent
        metrics = json.loads((directory/'metrics.json').read_bytes())
        receipt = json.loads((directory/'run-receipt.json').read_bytes())
        limits = (directory/'container-limits.txt').read_text().split()
        state = json.loads((directory/'container-state.json').read_bytes())
        if metrics['pages'][0]['input_image_sha256'] != row['image_sha256']:
            raise ValueError('PREPROCESSING_INFERENCE_IMAGE_HASH_MISMATCH')
        if (receipt['status'] != 'SUCCEEDED' or state['OOMKilled'] or metrics['device'] != 'cpu'
                or metrics['cpu_threads'] != 2 or int(limits[1]) != 17179869184
                or int(limits[2]) != 17179869184 or int(limits[3]) != 2000000000 or limits[4] != 'none'):
            raise ValueError('PREPROCESSING_RUNTIME_OUTSIDE_FIXED_EXPERIMENT_PROFILE')
        runtimes.append({'physical_page':page, 'variant':variant, 'image_id':limits[0],
                         'memory_bytes':int(limits[1]), 'memory_swap_bytes':int(limits[2]),
                         'nano_cpus':int(limits[3]), 'network':limits[4],
                         'metrics':metrics, 'receipt':receipt, 'OOMKilled':state['OOMKilled']})
    blocks = []
    private_blocks = []
    for b in reference['blocks']:
        if not b.get('image_verified') or not b.get('review_method') or not b.get('reference_image_sha256'):
            raise ValueError('SOURCE_IMAGE_REVIEW_REQUIRED')
        page=b['physical_page']
        image=args.images/f'page-{page}.png'
        if digest(image) != b['reference_image_sha256']:
            raise ValueError('REFERENCE_IMAGE_HASH_MISMATCH')
        baseline, indices, box = roi_hypothesis(sources[page],b)
        scores = {'baseline_raw':character_errors(b['reference'], baseline)}
        hypotheses = {'baseline_raw':baseline}
        for variant in sorted({r['variant'] for r in variants if r['physical_page']==page}):
            processed = variant_sources.get((variant,page))
            if processed:
                hypothesis, _, _ = roi_hypothesis(processed,b)
                scores[variant] = character_errors(b['reference'],hypothesis)
                hypotheses[variant]=hypothesis
            else:
                scores[variant]={'status':'unavailable: no successful recognition output'}
        public = {k:b[k] for k in ('id','physical_page','reference_image_sha256','review_method')}
        public.update(reference_sha256=hashlib.sha256(b['reference'].encode()).hexdigest(),bbox=box,
                      reference_characters=len(''.join(b['reference'].split())),scores=scores,
                      raw_indices=indices,ambiguous_prefix_excluded=b.get('omit_ambiguous_question_prefix',False))
        blocks.append(public)
        private_blocks.append({**b,'hypotheses':hypotheses,'scores':scores})
    (args.output/'reference-hypotheses.json').write_text(json.dumps(private_blocks,ensure_ascii=False,indent=2))
    total=sum(b['reference_characters'] for b in blocks)
    if total < 3000:
        raise ValueError('EXPANDED_REFERENCE_BELOW_3000_CHARACTERS')
    summary={'schema':'ocr-review-evaluation-v1','scope':'selected full-question ROIs only; not whole-page/book accuracy',
             'reference_sha256':digest(args.reference),'reference_characters':total,'reference_blocks':blocks,
             'regression_pages':page_rows,'preprocessing_comparison':comparisons,
             'preprocessing_images':variants, 'runtime_runs':runtimes,
             'result_analysis_seconds':time.monotonic()-started,
             'result_analysis_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
             'cer_basis':'native raw OCR lines whose center is in manually selected ROI; row-major within question; whitespace only normalization',
             'review_certification':'开发侧看图核对，未经用户确认',
             'raw_cer_boundary':'recognition metric; layout retention measured separately; all layer originals retained'}
    args.public_summary.parent.mkdir(parents=True,exist_ok=True)
    args.public_summary.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return summary


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    for name in ('batch','reference','images','output','public-summary'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--preprocessing-manifest',type=Path)
    parser.add_argument('--inference',type=Path)
    evaluate(parser.parse_args())
