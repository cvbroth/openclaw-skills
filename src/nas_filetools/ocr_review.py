"""Experimental, offline PP-StructureV3 result reconciliation, not OCR correction.

Native text is immutable. Matching requires both text and geometry; matching
capacity is consumed so repeated text cannot cover several independent regions.
Only unambiguous gaps between spatial anchors may receive recovered raw lines.
"""
import copy
import hashlib
import math
import re
import unicodedata


DEFAULT_RULES = {
    'version': 'experimental-1', 'spatial_overlap': 0.35, 'box_padding_px': 8,
    'lane_overlap': 0.45, 'same_row_overlap': 0.45, 'low_recognition_score': 0.90,
    'status_boundary': 'structural evidence and review state; never accuracy probability',
}
FURNITURE = {'header', 'footer', 'aside_text', 'number', 'page_number'}


def checked_rules(overrides):
    if overrides and set(overrides)-set(DEFAULT_RULES):
        raise ValueError('UNKNOWN_EXPERIMENTAL_RULE')
    rules = {**DEFAULT_RULES, **(overrides or {})}
    for key in ('spatial_overlap', 'lane_overlap', 'same_row_overlap', 'low_recognition_score'):
        if not isinstance(rules[key], (int,float)) or not 0 < rules[key] <= 1:
            raise ValueError(f'INVALID_THRESHOLD:{key}')
    pad = rules['box_padding_px']
    if not isinstance(pad, (int,float)) or not math.isfinite(pad) or pad < 0:
        raise ValueError('INVALID_BOX_PADDING')
    return rules


def normalized(text):
    # Coverage only, NOT CER or output rewriting. Keep circled numbers and
    # semantic symbols. Restrict compatibility folding to fullwidth ASCII.
    text = ''.join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in text)
    return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))


def area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def intersection(a, b):
    return area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def horizontal_overlap(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) / max(1, min(a[2]-a[0], b[2]-b[0]))


def same_row(a, b, threshold=0.45):
    return max(0, min(a[3], b[3]) - max(a[1], b[1])) / max(1, min(a[3]-a[1], b[3]-b[1])) >= threshold


def reading_rows(items, box_key='bbox'):
    """Row-major within an explicit region, not a universal multi-column parser."""
    rows = []
    for item in sorted(items, key=lambda it: (it[box_key][1], it[box_key][0])):
        box = item[box_key]
        if rows and same_row(rows[-1][0][box_key], box):
            rows[-1].append(item)
        else:
            rows.append([item])
    return [item for row in rows for item in sorted(row, key=lambda it: it[box_key][0])]


def valid_box(box):
    return (isinstance(box, (list, tuple)) and len(box) == 4
            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in box)
            and area(box) > 0)


def raw_lines(native):
    ocr = native['overall_ocr_res']
    texts, boxes, scores = ocr['rec_texts'], ocr['rec_boxes'], ocr['rec_scores']
    if not len(texts) == len(boxes) == len(scores):
        raise ValueError('OCR_ARRAY_LENGTH_MISMATCH')
    result = []
    for i, (text, box, score) in enumerate(zip(texts, boxes, scores)):
        if not valid_box(box):
            raise ValueError(f'INVALID_OCR_BOX:{i}')
        result.append({'raw_index': i, 'text': text, 'bbox': box, 'recognition_score': score})
    return result


def _candidates(line, blocks, rules):
    b = line['bbox']
    pad = rules['box_padding_px']
    padded = [b[0]-pad, b[1]-pad, b[2]+pad, b[3]+pad]
    return [i for i, block in enumerate(blocks)
            if intersection(padded, block['block_bbox']) / max(1, min(area(b), area(block['block_bbox'])))
            >= rules['spatial_overlap']]


def spatial_coverage(lines, blocks, rules=None):
    rules = checked_rules(rules)
    normalized_blocks = [normalized(b['block_content']) for b in blocks]
    used = set()
    records = []
    for line in reading_rows(lines):
        word = normalized(line['text'])
        row = {**line, 'state': 'unmatched', 'matched_spans': []}
        if not line['text'].strip():
            row['state'] = 'empty'
            records.append(row)
            continue
        candidates = _candidates(line, blocks, rules)
        row['spatial_candidates'] = candidates
        # Prefer one block; then permit split/merged blocks intersecting the
        # same raw line. Never search the entire page for equal text.
        groups = [[i] for i in candidates]
        if len(candidates) > 1:
            groups.append([r['index'] for r in reading_rows(
                [{'index':i, 'bbox':blocks[i]['block_bbox']} for i in candidates])])
        if word:
            for indices in groups:
                mapping = [(i, j) for i in indices for j in range(len(normalized_blocks[i]))]
                content = ''.join(normalized_blocks[i] for i in indices)
                start = content.find(word)
                while start >= 0:
                    positions = mapping[start:start+len(word)]
                    if not any(position in used for position in positions):
                        used.update(positions)
                        row['state'] = 'covered'
                        row['matching_basis'] = 'spatially intersecting block text; normalization only for coverage'
                        row['repeated_occurrence_ambiguity'] = content.count(word) > 1
                        for i in indices:
                            offsets = [j for block_id, j in positions if block_id == i]
                            if offsets:
                                row['matched_spans'].append({'block_index': i, 'start': min(offsets), 'end': max(offsets)+1})
                        break
                    start = content.find(word, start+1)
                if row['state'] == 'covered':
                    break
        else:
            # Punctuation-only recognized marks are preserved for review;
            # their exact text is not sufficient evidence of body placement.
            row['reason'] = 'punctuation-only or empty after coverage normalization'
        records.append(row)
    return sorted(records, key=lambda row: row['raw_index'])


def insertion_anchor(line, blocks, rules):
    box = line['bbox']
    lane = [(i, b) for i, b in enumerate(blocks) if b['block_label'] not in FURNITURE
            and horizontal_overlap(box, b['block_bbox']) >= rules['lane_overlap']]
    # An unmatched raw line inside another block may be a conflict, not loss.
    if any(intersection(box, b['block_bbox']) / max(1, area(box)) >= rules['spatial_overlap'] for _, b in lane):
        return None, 'intersects existing body block: replacement or intra-block ordering uncertain'
    above = [(i, b) for i, b in lane if b['block_bbox'][3] <= box[1]+rules['box_padding_px']]
    below = [(i, b) for i, b in lane if b['block_bbox'][1] >= box[3]-rules['box_padding_px']]
    if not above or not below:
        return None, 'no pair of body anchors in the same horizontal lane'
    upper_i, upper = max(above, key=lambda it: it[1]['block_bbox'][3])
    lower_i, lower = min(below, key=lambda it: it[1]['block_bbox'][1])
    if upper_i >= lower_i:
        return None, 'spatial anchors conflict with original parsed reading order'
    between = blocks[upper_i+1:lower_i]
    if any(b['block_label'] not in FURNITURE and horizontal_overlap(box, b['block_bbox']) >= rules['lane_overlap']
           and not same_row(box, b['block_bbox'], rules['same_row_overlap']) for b in between):
        return None, 'interleaved columns or competing reading-order anchors'
    before = lower_i
    for i in range(upper_i+1, lower_i):
        b = blocks[i]['block_bbox']
        if (b[1] >= box[3]-rules['box_padding_px']
                or (same_row(box, b, rules['same_row_overlap']) and box[2] <= b[0])):
            before = i
            break
    return {'insert_before_original_index': before, 'upper_original_index': upper_i,
            'lower_original_index': lower_i, 'basis': 'raw rectangle in same-lane body gap; original anchors retain order'}, None


def critical_tokens(text):
    return {'numbers': re.findall(r'\d+', text), 'negations': re.findall(r'不|非|错误|不能|不得|无|未', text),
            'option_labels': re.findall(r'[A-Da-d][.．、，]', text),
            'question_prefix': re.findall(r'^\s*\d+[.．、]', text)}


def structure_warnings(blocks):
    """Question candidates only. Never infer a missing number or reassign options."""
    warnings, questions, current = [], [], None
    for block in blocks:
        if block['block_label'] in FURNITURE:
            continue
        for line in block['block_content'].splitlines():
            match = re.match(r'^\s*(\d+)[.．、]', line)
            if match:
                if current:
                    questions.append(current)
                current = {'number': int(match[1]), 'bbox': block['block_bbox'], 'text': line, 'options': []}
            if current:
                current['options'].extend(re.findall(r'(?<![a-zA-Z])[A-Da-d][.．、，]', line))
    if current:
        questions.append(current)
    for index, question in enumerate(questions):
        labels = [x[0].upper() for x in question['options']]
        if labels != list('ABCD'):
            warnings.append({**question, 'reason': 'option sequence is not A,B,C,D; may be material, OCR label error or page boundary',
                             'page_boundary_candidate': index in (0, len(questions)-1)})
        if index and question['number'] != questions[index-1]['number']+1:
            warnings.append({**question, 'reason': 'question gap/reset/repetition candidate; section reset or recognition error needs source review'})
    return warnings


def reconcile(native, physical_page, markdown=None, rules=None, review_records=None):
    rules = checked_rules(rules)
    blocks = copy.deepcopy(native['parsing_res_list'])
    if any(not valid_box(b['block_bbox']) for b in blocks):
        raise ValueError('INVALID_PARSED_BOX')
    lines = raw_lines(native)
    before = spatial_coverage(lines, blocks, rules)
    recoveries, pending, insertions = [], [], {}
    for line in before:
        if line['state'] != 'unmatched':
            continue
        duplicate = next((r for r in recoveries if normalized(r['text']) == normalized(line['text'])
                          and intersection(r['bbox'], line['bbox']) / max(1, min(area(r['bbox']), area(line['bbox']))) > .8), None)
        if duplicate:
            pending.append({**line, 'physical_page': physical_page, 'reason': 'overlapping duplicate raw detection; not inserted twice'})
            continue
        anchor, reason = insertion_anchor(line, blocks, rules)
        record = {**line, 'physical_page': physical_page, 'source': 'overall_ocr_res.rec_texts/rec_boxes',
                  'review_state': '需复核', 'critical_tokens': critical_tokens(line['text'])}
        if anchor:
            record['placement'] = anchor
            recoveries.append(record)
            insertions.setdefault(anchor['insert_before_original_index'], []).append(record)
        else:
            pending.append({**record, 'reason': reason, 'label': '待核对片段'})
    repaired = []
    for i, block in enumerate(blocks):
        for row in reading_rows(insertions.get(i, [])):
            repaired.append({'block_label': 'recovered_raw_text', 'block_content': row['text'], 'block_bbox': row['bbox'],
                             'source_raw_indices': [row['raw_index']], 'restoration_basis': row['placement']})
        repaired.append({**block, 'original_index': i})
    after = spatial_coverage(lines, repaired, rules)
    duplicates, order = [], []
    for i, block in enumerate(repaired):
        for j in range(i):
            prev = repaired[j]
            if (normalized(block['block_content']) and normalized(block['block_content']) == normalized(prev['block_content'])
                    and intersection(block['block_bbox'], prev['block_bbox']) / max(1, min(area(block['block_bbox']), area(prev['block_bbox']))) > .8):
                duplicates.append({'block_indices': [j, i], 'bbox': block['block_bbox'], 'text': block['block_content'],
                                   'physical_page': physical_page, 'reason': 'same text and overlapping region'})
    body = [(i, b) for i, b in enumerate(repaired) if b['block_label'] not in FURNITURE]
    for (i, a), (j, b) in zip(body, body[1:]):
        if horizontal_overlap(a['block_bbox'], b['block_bbox']) >= rules['lane_overlap'] and b['block_bbox'][3] < a['block_bbox'][1]:
            order.append({'block_indices': [i, j], 'bbox': b['block_bbox'], 'text': b['block_content'],
                          'physical_page': physical_page, 'reason': 'vertical inversion in shared lane; needs review'})
    for block_index, block in enumerate(repaired):
        if block['block_label'] in FURNITURE:
            continue
        rows = []
        for line in after:
            spans = [s for s in line['matched_spans'] if s['block_index'] == block_index]
            if len(spans) == 1:
                rows.append({**line, 'offset':spans[0]['start']})
        rows = reading_rows(rows)
        for previous, following in zip(rows,rows[1:]):
            if following['offset'] < previous['offset']:
                order.append({'block_indices':[block_index], 'physical_page':physical_page,
                              'bbox':following['bbox'],'text':following['text'],
                              'reason':'intra-block row-order ambiguity; original text retained, columns require source review',
                              'raw_indices':[previous['raw_index'],following['raw_index']]})
    # Every restored group must retain row-major order within its anchor gap.
    for upper in {r['placement']['upper_original_index'] for r in recoveries}:
        group = [r for r in recoveries if r['placement']['upper_original_index'] == upper]
        expected = [r['raw_index'] for r in reading_rows(group)]
        actual = [b['source_raw_indices'][0] for b in repaired if b.get('source_raw_indices')
                  and b['source_raw_indices'][0] in expected]
        if expected != actual:
            order.append({'physical_page': physical_page, 'bbox': group[0]['bbox'], 'text': group[0]['text'],
                          'reason': 'restored row order differs inside common anchor gap', 'expected_raw_indices': expected,
                          'actual_raw_indices': actual})
    low_scores = [{**r, 'physical_page': physical_page, 'reason': 'native recognizer score below experimental threshold'} for r in lines
                  if r['text'].strip() and r['recognition_score'] < rules['low_recognition_score']]
    critical = [{**r, 'physical_page': physical_page, 'tokens': critical_tokens(r['text']), 'reason': 'key text requires source review; score is not probability'}
                for r in lines if any(critical_tokens(r['text']).values())]
    markdown_gaps = []
    if markdown is not None:
        cursor, text = 0, normalized(markdown)
        for i, block in enumerate(blocks):
            token = normalized(block['block_content'])
            if not token:
                continue
            found = text.find(token, cursor)
            if found < 0:
                markdown_gaps.append({'original_index': i, 'bbox': block['block_bbox'], 'physical_page': physical_page,
                                      'text': block['block_content'], 'reason': 'native block not found in Markdown in native order'})
            else:
                cursor = found + len(token)
    records = review_records or []
    question_warnings = [{**r, 'physical_page': physical_page} for r in structure_warnings(repaired)]
    confirmed = any(r.get('reviewer_type') == 'human' and r.get('status') == 'confirmed'
                    and r.get('scope') == 'page' and r.get('evidence') for r in records)
    blocking = pending or duplicates or order or question_warnings
    status = '无法确定' if pending else ('通过' if confirmed and not blocking else '需复核')
    result = {
        'schema': 'experimental-spatial-ocr-review-v1', 'physical_page': physical_page, 'rules': rules,
        'recognition': {'source': 'PP-StructureV3 overall_ocr_res.rec_scores (per recognized line)',
                        'meaning': 'recognizer score, not correctness probability',
                        'line_scores': [r['recognition_score'] for r in lines]},
        'structure': {'raw_lines': len(lines), 'covered_before': sum(r['state']=='covered' for r in before),
                      'covered_after': sum(r['state']=='covered' for r in after), 'recovered_lines': len(recoveries),
                      'pending_lines': len(pending), 'duplicate_regions': duplicates, 'order_candidates': order,
                      'question_option_candidates': question_warnings,
                      'original_markdown_gaps': markdown_gaps},
        'coverage_before': before, 'coverage_after': after, 'recovered': recoveries, 'pending_fragments': pending,
        'low_score_regions': low_scores, 'critical_regions': critical, 'review_records': records,
        'review_status': status, 'accuracy': None, 'repaired_blocks': repaired,
        'boundary': 'retains recognized text only; no correction, inferred numbering, question assignment or human certification',
    }
    result['repaired_markdown'] = '\n\n'.join(b['block_content'] for b in repaired) + '\n'
    result['repaired_markdown_sha256'] = hashlib.sha256(result['repaired_markdown'].encode()).hexdigest()
    return result


def transform_box(box, matrix):
    """Map a rectangle through an explicit 3x3 affine transform using all corners."""
    if len(matrix) != 3 or any(len(row) != 3 for row in matrix) or matrix[2] != [0, 0, 1]:
        raise ValueError('AFFINE_MATRIX_REQUIRED')
    points = [(matrix[0][0]*x+matrix[0][1]*y+matrix[0][2], matrix[1][0]*x+matrix[1][1]*y+matrix[1][2])
              for x, y in [(box[0],box[1]),(box[2],box[1]),(box[2],box[3]),(box[0],box[3])]]
    return [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]


def compare_lines(original, processed, processed_to_original, physical_page=None):
    """Position-aligned disagreement evidence. Does not elect a winning OCR."""
    a, b = raw_lines(original), raw_lines(processed)
    for row in b:
        row['bbox_original'] = transform_box(row['bbox'], processed_to_original)
    edges = {}
    for left in a:
        for right in b:
            ab, bb = left['bbox'], right['bbox_original']
            overlap = intersection(ab, bb) / max(1, min(area(ab), area(bb)))
            if overlap >= .5 and same_row(ab, bb):
                x, y = ('a', left['raw_index']), ('b', right['raw_index'])
                edges.setdefault(x, set()).add(y)
                edges.setdefault(y, set()).add(x)
    used_a, used_b, matches = set(), set(), []
    visited = set()
    for start in sorted(edges):
        if start in visited:
            continue
        todo, component = [start], set()
        while todo:
            item = todo.pop()
            if item not in component:
                component.add(item)
                todo.extend(edges[item]-component)
        visited.update(component)
        indices_a = [i for side, i in component if side == 'a']
        indices_b = [i for side, i in component if side == 'b']
        used_a.update(indices_a)
        used_b.update(indices_b)
        left = reading_rows([a[i] for i in indices_a])
        right = reading_rows([b[i] for i in indices_b], 'bbox_original')
        lt, rt = ''.join(r['text'] for r in left), ''.join(r['text'] for r in right)
        region = [min(r['bbox'][0] for r in left), min(r['bbox'][1] for r in left),
                  max(r['bbox'][2] for r in left), max(r['bbox'][3] for r in left)]
        matches.append({'physical_page':physical_page, 'bbox':region,
                        'original_lines': left, 'processed_lines': right, 'original_text': lt, 'processed_text': rt,
                        'shape': [len(left), len(right)], 'text_changed': lt != rt,
                        'critical_disagreement': critical_tokens(lt) != critical_tokens(rt),
                        'score_delta': sum(r['recognition_score'] for r in right)/len(right)
                                       - sum(r['recognition_score'] for r in left)/len(left),
                        'review_status': '需复核',
                        'reason': 'position-aligned OCR disagreement; score/agreement cannot determine correctness'})
    return {'physical_page':physical_page, 'matched': matches,
            'original_unmatched': [{**r, 'physical_page':physical_page, 'review_status':'无法确定',
                                    'reason':'no position-aligned processed detection; split/merge or disappearance requires source review'}
                                   for r in a if r['raw_index'] not in used_a],
            'processed_unmatched': [{**r, 'physical_page':physical_page, 'review_status':'无法确定',
                                     'reason':'no position-aligned original detection; split/merge or appearance requires source review'}
                                    for r in b if r['raw_index'] not in used_b],
            'boundary': 'unmatched may be split/merge, appearance or disappearance; not automatic proof of a missing line',
            'winner': None}
