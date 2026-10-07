import json
from pathlib import Path
import tempfile
import unittest

from nas_filetools.ocr_m3_comparison import (
    load_comparison_config,
    score_visual_quality,
    select_review_regions,
    validate_usage,
    extract_response,
    screening_decision,
    apply_review_suggestions,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "deploy/ocr-m3-comparison-v1.json"


class ComparisonTests(unittest.TestCase):
    def test_malformed_json_salvage_is_explicit_and_preserves_text(self):
        raw = '{"body_text":"题干有"引号"\\nA.甲","nonbody_text":[]},"bad":true}'
        value, record = extract_response(raw)
        self.assertFalse(record["strict_json"])
        self.assertEqual(value["body_text"], '题干有"引号"\nA.甲')
        self.assertEqual(record["salvaged_fields"], ["body_text"])

    def setUp(self):
        self.config = load_comparison_config(CONFIG)

    def assessment(self, grade="good"):
        return {
            "dimensions": {
                name: {"grade": grade, "reason": "synthetic", "regions": []}
                for name in self.config["visual_quality"]["dimensions"]
            },
            "critical_flags": [],
        }

    def test_score_is_program_generated_and_not_acceptance(self):
        result = score_visual_quality(self.assessment(), self.config["visual_quality"])
        self.assertEqual(result["experimental_readability_score"], 100)
        self.assertEqual(result["screening_suggestion"], "正常抽查")
        self.assertEqual(result["human_acceptance_status"], "未确认")
        self.assertTrue(result["not_accuracy_or_probability"])

    def test_critical_damage_cannot_be_averaged_away(self):
        assessment = self.assessment()
        assessment["critical_flags"] = ["critical_body_unreadable"]
        result = score_visual_quality(assessment, self.config["visual_quality"])
        self.assertEqual(result["experimental_readability_score"], 39)
        self.assertEqual(result["screening_suggestion"], "需要更清晰来源")

    def test_unknown_is_not_zero_risk(self):
        assessment = self.assessment("unknown")
        result = score_visual_quality(assessment, self.config["visual_quality"])
        self.assertIsNone(result["experimental_readability_score"])
        self.assertEqual(result["screening_suggestion"], "unknown")

    def test_candidate_selection_uses_risk_and_merges_neighbours(self):
        items = [
            {"id": "a", "bbox": [10, 10, 30, 30], "risks": ["low_score"]},
            {"id": "b", "bbox": [35, 12, 55, 32], "risks": ["pending"]},
            {"id": "c", "bbox": [300, 300, 330, 330], "risks": ["body_review"]},
        ]
        regions, receipt = select_review_regions(
            items, 400, 400, {**self.config["candidate_selection"], "merge_gap_px": 6}
        )
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0]["ids"], ["a", "b"])
        self.assertEqual(receipt["selected_item_count"], 2)

    def test_config_rejects_bad_weight_sum(self):
        value = json.loads(CONFIG.read_text())
        value["visual_quality"]["dimensions"]["clarity"]["weight"] = 0.9
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "DIMENSION_WEIGHT_SUM"):
                load_comparison_config(path)

    def test_usage_requires_exact_route(self):
        envelope = {
            "provider": "minimax-portal",
            "model": "MiniMax-M3",
            "usage": {"input": 2, "output": 3, "cacheRead": 1, "cacheWrite": 0, "total": 6, "cost": {"total": 0}},
        }
        self.assertEqual(validate_usage(envelope)["total"], 6)
        envelope["provider"] = "other"
        with self.assertRaisesRegex(ValueError, "MODEL_ROUTE"):
            validate_usage(envelope)

    def test_blocker_overrides_high_quality_without_human_acceptance(self):
        value = screening_decision({"screening_suggestion": "正常抽查"}, ["order"], "hash", self.config)
        self.assertEqual(value["screening_suggestion"], "需人工查看")
        self.assertFalse(value["normal_page_sample_selected"])
        self.assertEqual(value["human_acceptance_status"], "未确认")

    def test_normal_page_is_sampled_not_forced_to_human_confirmation(self):
        config = self.config
        config["candidate_selection"]["normal_page_sample_fraction"] = 0
        value = screening_decision({"screening_suggestion": "正常抽查"}, [], "hash", config)
        self.assertEqual(value["screening_suggestion"], "正常抽查")
        self.assertFalse(value["normal_page_sample_selected"])
        self.assertEqual(value["human_acceptance_status"], "未确认")

    def test_known_source_damage_cannot_be_cleared_by_model_high_score(self):
        value = screening_decision({"screening_suggestion": "正常抽查"}, ["source_damage"], "hash", self.config)
        self.assertEqual(value["screening_suggestion"], "需要更清晰来源")

    def test_model_changes_do_not_overwrite_source_or_confirm_human(self):
        blocks = [{"block_content": "原文"}]
        items = [{"id": "x", "target": "p1-b-0", "current_text": "原文"}]
        revised, decisions = apply_review_suggestions(1, items, blocks, [{"id": "x", "status": "replace", "replacement": "新文"}])
        self.assertEqual(blocks[0]["block_content"], "原文")
        self.assertEqual(revised[0]["block_content"], "新文")
        self.assertEqual(decisions[0]["human_status"], "未确认")
        with self.assertRaisesRegex(ValueError, "CANDIDATE_ID_COVERAGE"):
            apply_review_suggestions(1, items, blocks, [])

    def test_conflicting_model_edits_to_same_target_are_rejected(self):
        items = [{"id": name, "target": "p1-b-0", "current_text": "原文"} for name in ("a", "b")]
        rows = [{"id": name, "status": "replace", "replacement": text}
                for name, text in (("a", "新文"), ("b", "异文"))]
        blocks = [{"block_content": "原文"}]
        with self.assertRaisesRegex(ValueError, "TARGET_EDIT_CONFLICT"):
            apply_review_suggestions(1, items, blocks, rows)
        self.assertEqual(blocks[0]["block_content"], "原文")

    def test_unknown_weight_boundary_and_critical_cap(self):
        value = self.assessment()
        value["dimensions"]["crop_obstruction"]["grade"] = "unknown"
        result = score_visual_quality(value, self.config["visual_quality"])
        self.assertEqual(result["experimental_readability_score"], 100)
        value["dimensions"]["deformation"]["grade"] = "unknown"
        self.assertIsNone(score_visual_quality(value, self.config["visual_quality"])["experimental_readability_score"])

    def test_overflow_candidates_remain_explicit(self):
        items = [{"id": str(i), "bbox": [10, i * 100, 30, i * 100 + 20], "risks": ["pending"]}
                 for i in range(3)]
        regions, receipt = select_review_regions(items, 400, 400,
            {**self.config["candidate_selection"], "merge_gap_px": 0, "maximum_regions_per_page": 1})
        self.assertEqual(len(regions), 1)
        self.assertEqual(receipt["overflow_item_ids"], ["1", "2"])

    def test_invalid_bbox_makes_visual_score_unknown_to_caller(self):
        value = self.assessment()
        value["dimensions"]["crop_obstruction"]["regions"] = [[0, 0, 0, 100]]
        with self.assertRaisesRegex(ValueError, "ASSESSMENT_REGIONS"):
            score_visual_quality(value, self.config["visual_quality"])


if __name__ == "__main__":
    unittest.main()
