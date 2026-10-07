"""Synthetic spatial regressions. Contains no private question-book text."""
import unittest
from nas_filetools.ocr_review import compare_lines, reconcile, transform_box


def block(text, box, label='text'):
    return {'block_label': label, 'block_content': text, 'block_bbox': box}


def native(lines, blocks):
    return {'overall_ocr_res': {'rec_texts': [t for t,b in lines], 'rec_boxes': [b for t,b in lines],
                                'rec_scores': [.99 for _ in lines]}, 'parsing_res_list': blocks}


class SpatialReviewTests(unittest.TestCase):
    def test_missing_options_restored_at_body_gap_and_existing_d(self):
        a,b,c,d = 'A.甲', 'B.乙', 'C.丙', 'D.丁'
        original = [block('1.请选择', [0,0,100,10]), block(d,[60,40,90,50]), block('2.下一题',[0,60,100,70])]
        data = native([('1.请选择',[0,0,100,10]),(a,[0,20,30,30]),(b,[60,20,90,30]),
                       (c,[0,40,30,50]),(d,[60,40,90,50]),('2.下一题',[0,60,100,70])], original)
        result = reconcile(data, 7)
        texts = [x['block_content'] for x in result['repaired_blocks']]
        self.assertEqual(texts, ['1.请选择',a,b,c,d,'2.下一题'])
        self.assertEqual(result['structure']['recovered_lines'], 3)
        self.assertEqual(result['structure']['covered_after'], 6)
        self.assertEqual(result['structure']['order_candidates'], [])
        self.assertEqual(data['parsing_res_list'], original)
        self.assertEqual(result['review_status'],'需复核')

    def test_same_text_in_distant_region_is_not_coverage(self):
        data = native([('重复',[0,0,30,10]),('重复',[0,100,30,110])], [block('重复',[0,0,30,10])])
        r=reconcile(data,1)
        self.assertEqual(r['structure']['covered_before'],1)
        self.assertEqual(r['structure']['pending_lines'],1)
        self.assertNotIn('重复\n\n重复',r['repaired_markdown'])

    def test_repeated_detection_cannot_reuse_one_text_capacity(self):
        data=native([('甲',[0,0,20,10]),('甲',[0,0,20,10])],[block('甲',[0,0,20,10])])
        self.assertEqual(reconcile(data,1)['structure']['covered_before'],1)

    def test_punctuation_wrap_and_block_split(self):
        data=native([('Ａ．测试，换行',[0,0,100,20])], [block('A.测试\n',[0,0,45,20]),block('换行',[45,0,100,20])])
        self.assertEqual(reconcile(data,1)['structure']['covered_before'],1)
        data=native([('甲乙',[0,0,40,10]),('丙丁',[0,15,40,25])],[block('甲乙\n丙丁',[0,0,40,25])])
        self.assertEqual(reconcile(data,1)['structure']['covered_before'],2)

    def test_conflicting_text_inside_block_is_pending_not_replaced(self):
        r=reconcile(native([('不得',[0,0,50,20])],[block('可以',[0,0,50,20])]),1)
        self.assertEqual(r['review_status'],'无法确定')
        self.assertEqual(r['repaired_markdown'],'可以\n')
        self.assertEqual(r['pending_fragments'][0]['text'],'不得')

    def test_independent_columns_retain_lane_and_original_order(self):
        blocks=[block('左起',[0,0,40,10]),block('左止',[0,40,40,50]),
                block('右起',[60,0,100,10]),block('右止',[60,40,100,50])]
        data=native([('左起',[0,0,40,10]),('左中',[0,20,40,30]),('左止',[0,40,40,50]),
                     ('右起',[60,0,100,10]),('右中',[60,20,100,30]),('右止',[60,40,100,50])],blocks)
        r=reconcile(data,1)
        self.assertEqual([b['block_content'] for b in r['repaired_blocks']],['左起','左中','左止','右起','右中','右止'])

    def test_no_auto_pass_from_high_recognition_score_or_normalization(self):
        r=reconcile(native([('1.不正确',[0,0,50,20])],[block('1.不正确',[0,0,50,20])]),1)
        self.assertEqual(r['review_status'],'需复核')
        self.assertIsNone(r['accuracy'])
        self.assertTrue(r['critical_regions'])
        # Normalization never treats ① and 1 as equivalent.
        r=reconcile(native([('①',[0,0,50,20])],[block('1',[0,0,50,20])]),1)
        self.assertEqual(r['structure']['covered_before'],0)

    def test_missing_and_reordered_markdown_retained_in_new_export(self):
        data=native([('首',[0,0,50,10]),('末',[0,20,50,30])],[block('首',[0,0,50,10]),block('末',[0,20,50,30])])
        r=reconcile(data,1,markdown='末')
        self.assertEqual(len(r['structure']['original_markdown_gaps']),1)
        self.assertEqual(r['repaired_markdown'],'首\n\n末\n')

    def test_affine_all_corners_and_invalid_matrix(self):
        self.assertEqual(transform_box([1,2,4,6],[[0,-1,10],[1,0,0],[0,0,1]]),[4,1,8,4])
        with self.assertRaises(ValueError):
            transform_box([0,0,1,1],[[1,0,0],[0,1,0],[1,0,1]])

    def test_intra_block_reordering_is_flagged_without_silent_rewrite(self):
        data=native([('上行',[0,0,50,10]),('下行',[0,20,50,30])],[block('下行\n上行',[0,0,50,30])])
        result=reconcile(data,1)
        self.assertEqual(result['structure']['covered_after'],2)
        self.assertTrue(result['structure']['order_candidates'])
        self.assertEqual(result['repaired_markdown'],'下行\n上行\n')

    def test_invalid_experimental_thresholds_rejected(self):
        data=native([('甲',[0,0,50,10])],[block('甲',[0,0,50,10])])
        for rules in ({'low_recognition_score':2},{'box_padding_px':float('nan')},{'invented_rule':True}):
            with self.assertRaises(ValueError):
                reconcile(data,1,rules=rules)

    def test_preprocess_split_is_alignment_group_not_disappearance(self):
        a=native([('A.不得100',[0,0,100,10])],[])
        b=native([('A.不得',[0,0,50,10]),('100',[50,0,100,10])],[])
        r=compare_lines(a,b,[[1,0,0],[0,1,0],[0,0,1]])
        self.assertEqual(r['matched'][0]['shape'],[1,2])
        self.assertFalse(r['matched'][0]['text_changed'])
        self.assertEqual(r['processed_unmatched'],[])
        c=native([('A.可以100',[10,0,110,10])],[])
        r=compare_lines(a,c,[[1,0,-10],[0,1,0],[0,0,1]])
        self.assertTrue(r['matched'][0]['critical_disagreement'])
        self.assertIsNone(r['winner'])


if __name__ == '__main__':
    unittest.main()
