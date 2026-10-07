"""Synthetic offline review tests; no private question-book text."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw, ImageFilter
from nas_filetools.ocr_quality import fingerprint, image_metrics, load_config, screen
from nas_filetools.ocr_review import reconcile
from nas_filetools.ocr_review_bundle import (
    apply_receipt,
    import_receipt,
    initialize_bundle,
    make_items,
    render_html,
    seal,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "deploy/ocr-screening-v1.json"
TEMPLATE = ROOT / "src/nas_filetools/review_assets/offline.html"


def fixture():
    block = {"block_label": "text", "block_content": "不选择12", "block_bbox": [10, 10, 90, 30]}
    native = {
        "width": 100,
        "height": 100,
        "parsing_res_list": [block],
        "overall_ocr_res": {"rec_texts": ["不选择12"], "rec_boxes": [[10, 10, 90, 30]], "rec_scores": [0.99]},
    }
    r = reconcile(native, 1)
    page = {
        "physical_page": 1,
        "width": 100,
        "height": 100,
        "printed_page": None,
        "blocks": [{**block, "id": "p1-b-0"}],
        "review_status": "unconfirmed",
    }
    items = make_items(page, r)
    return seal(
        {
            "schema": "offline-ocr-review-v1",
            "revision": 0,
            "parent_hash": None,
            "pages": [page],
            "items": items,
            "history": [],
            "imported_ids": [],
        }
    )


def receipt(base, action="confirm_text", **extra):
    item = base["items"][0]
    return {
        "schema": "offline-ocr-confirmation-v1",
        "receipt_id": "synthetic-1",
        "base_revision_hash": base["revision_hash"],
        "reviewer_type": "human",
        "reviewer_name": "Synthetic Tester",
        "operations": [
            {
                "id": item["id"],
                "action": action,
                "expected_hash": fingerprint(item),
                "reason": "synthetic source inspection",
                **extra,
            }
        ],
    }


def apply(base, r):
    return apply_receipt(base, r, r["reviewer_type"], r["reviewer_name"])


class BundleTests(unittest.TestCase):
    def test_confirm_item_does_not_confirm_page(self):
        b = fixture()
        r = apply(b, receipt(b))
        self.assertEqual(r["items"][0]["status"], "confirmed")
        self.assertEqual(r["pages"][0]["review_status"], "unconfirmed")
        self.assertEqual(b["items"][0]["status"], "unconfirmed")
        self.assertEqual(r["parent_hash"], b["revision_hash"])

    def test_edit_creates_history_and_revision_without_touching_original(self):
        b = fixture()
        r = apply(b, receipt(b, "edit_text", text="不选择13"))
        self.assertEqual(r["pages"][0]["blocks"][0]["block_content"], "不选择13")
        self.assertEqual(b["pages"][0]["blocks"][0]["block_content"], "不选择12")
        self.assertEqual(r["history"][0]["before"]["current_text"], "不选择12")
        self.assertEqual(r["history"][0]["reviewer_type"], "human")

    def test_place_pending_before_real_anchor(self):
        b = fixture()
        i = b["items"][0]
        i["target"] = None
        i["risks"] = ["pending"]
        i["blocking"] = True
        seal(b)
        r = apply(b, receipt(b, "place", bbox=[2, 2, 20, 8], before_target="p1-b-0"))
        self.assertEqual(len(r["pages"][0]["blocks"]), 2)
        self.assertTrue(r["pages"][0]["blocks"][0]["id"].endswith("-placed"))
        self.assertEqual(r["items"][0]["status"], "confirmed")
        for bbox in ([-1, 0, 20, 5], [0, 0, 200, 5], [0, 0, float("nan"), 5]):
            with self.assertRaises(ValueError):
                apply(b, receipt(b, "place", bbox=bbox, before_target="p1-b-0"))

    def test_text_confirmation_does_not_resolve_pending_layout(self):
        b = fixture()
        b["items"][0]["risks"] = ["pending"]
        b["items"][0]["blocking"] = True
        seal(b)
        r = apply(b, receipt(b))
        self.assertEqual(r["items"][0]["status"], "text_confirmed_layout_pending")

    def test_edit_pending_does_not_insert_or_resolve_position(self):
        b = fixture()
        b["items"][0]["target"] = None
        b["items"][0]["risks"] = ["pending"]
        b["items"][0]["blocking"] = True
        seal(b)
        r = apply(b, receipt(b, "edit_text", text="独立修订待定位"))
        self.assertEqual(r["items"][0]["current_text"], "独立修订待定位")
        self.assertEqual(r["items"][0]["status"], "text_confirmed_layout_pending")
        self.assertEqual(r["pages"][0]["blocks"], b["pages"][0]["blocks"])

    def test_new_edit_invalidates_prior_whole_page_acceptance(self):
        b = fixture()
        b["pages"][0]["review_status"] = "human-page-confirmed"
        seal(b)
        r = apply(b, receipt(b, "edit_text", text="独立修订"))
        self.assertEqual(r["pages"][0]["review_status"], "unconfirmed")

    def test_source_damage_cannot_be_cleared_by_empty_text_or_nonbody(self):
        b = fixture()
        b["items"][0]["risks"] = ["source_damage"]
        b["items"][0]["blocking"] = True
        seal(b)
        for action in ("confirm_text", "nonbody", "place"):
            with self.assertRaisesRegex(ValueError, "DAMAGED_SOURCE"):
                apply(b, receipt(b, action))
        self.assertEqual(apply(b, receipt(b, "source_unreadable"))["items"][0]["status"], "source_unreadable")

    def test_unknown_conflict_stale_duplicate_rejected(self):
        b = fixture()
        for change in ("unknown", "conflict", "stale", "duplicate", "invalid_action", "empty_reason"):
            r = receipt(b)
            if change == "unknown":
                r["operations"][0]["id"] = "missing"
            if change == "conflict":
                r["operations"][0]["expected_hash"] = "wrong"
            if change == "stale":
                r["base_revision_hash"] = "old"
            if change == "duplicate":
                r["operations"] *= 2
            if change == "invalid_action":
                r["operations"][0]["action"] = "execute"
            if change == "empty_reason":
                r["operations"][0]["reason"] = " "
            with self.assertRaises(ValueError):
                apply(b, r)
        r = apply(b, receipt(b))
        with self.assertRaisesRegex(ValueError, "DUPLICATE_IMPORT"):
            apply(r, receipt(b))

    def test_uncertain_unreadable_nonbody_and_human_page_boundary(self):
        for action in ("uncertain", "source_unreadable", "nonbody"):
            b = fixture()
            r = apply(b, receipt(b, action))
            self.assertEqual(r["items"][0]["status"], action)
            if action == "nonbody":
                self.assertTrue(r["pages"][0]["blocks"][0]["excluded_from_body"])
        b = fixture()
        r = receipt(b)
        r["operations"] = [
            {
                "id": "1",
                "action": "confirm_page",
                "expected_hash": fingerprint(b["pages"][0]),
                "reason": "whole source page reviewed",
            }
        ]
        self.assertEqual(apply(b, r)["pages"][0]["review_status"], "human-page-confirmed")
        r["reviewer_type"] = "developer-agent"
        with self.assertRaises(ValueError):
            apply(b, r)
        r["reviewer_type"] = "human"
        b["items"][0]["blocking"] = True
        seal(b)
        r["base_revision_hash"] = b["revision_hash"]
        with self.assertRaises(ValueError):
            apply(b, r)

    def test_same_target_two_edits_conflict(self):
        b = fixture()
        alias = copy.deepcopy(b["items"][0])
        alias["id"] = "alias"
        b["items"].append(alias)
        seal(b)
        r = receipt(b, "edit_text", text="甲")
        r["operations"].append({**r["operations"][0], "id": "alias", "expected_hash": fingerprint(alias)})
        with self.assertRaisesRegex(ValueError, "TARGET_CONFLICT"):
            apply(b, r)

    def test_script_safe_and_no_network_ui(self):
        b = fixture()
        b["items"][0]["current_text"] = "</script><img onerror=alert(1)>&"
        seal(b)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "index.html"
            render_html(b, p, TEMPLATE)
            s = p.read_text()
        self.assertNotIn("</script><img", s)
        self.assertIn("\\u003c/script>", s)
        self.assertNotIn("innerHTML", s)
        self.assertNotIn("fetch(", s)
        self.assertIn("textContent", s)

    def test_disk_import_export_source_hashes_and_repeat(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            im = root / "image.png"
            Image.new("RGB", (100, 100), "white").save(im)
            native = root / "native.json"
            native.write_text("{}")
            md = root / "source.md"
            md.write_text("原稿")
            block = {"block_label": "text", "block_content": "不选择12", "block_bbox": [10, 10, 90, 30]}
            n = {
                "parsing_res_list": [block],
                "overall_ocr_res": {
                    "rec_texts": ["不选择12"],
                    "rec_boxes": [[10, 10, 90, 30]],
                    "rec_scores": [0.99],
                },
            }
            pages = [
                {
                    "physical_page": 1,
                    "width": 100,
                    "height": 100,
                    "image_path": im,
                    "native_path": native,
                    "markdown_path": md,
                    "review": reconcile(n, 1),
                }
            ]
            bundle = root / "bundle"
            b = initialize_bundle(bundle, pages, load_config(CONFIG), "synthetic-hash", TEMPLATE)
            r = receipt(b, "edit_text", text="独立修订")
            res = import_receipt(bundle, r, "human", "Synthetic Tester")
            self.assertEqual(res["revision"], 1)
            self.assertEqual(json.loads((bundle / "revisions/revision-0.json").read_text())["revision"], 0)
            self.assertEqual(md.read_text(), "原稿")
            self.assertIn("独立修订", (bundle / "revisions/revision-1.md").read_text())
            with self.assertRaisesRegex(ValueError, "DUPLICATE_IMPORT"):
                import_receipt(bundle, r, "human", "Synthetic Tester")
            (bundle / "assets/page-1-native.json").write_text("tamper")
            with self.assertRaisesRegex(ValueError, "SOURCE_ASSET_CHANGED"):
                import_receipt(bundle, receipt(res), "human", "Synthetic Tester")


class QualityTests(unittest.TestCase):
    def test_invalid_configuration_and_blockers_cannot_be_disabled(self):
        original = json.loads(CONFIG.read_text())
        for path, value in [
            (("image", "minimum_dpi"), True),
            (("ocr_structure", "spatial_overlap"), True),
            (("image", "analysis_width"), 0),
            (("future_visual", "normal_page_sample_fraction"), 1.5),
            (("mandatory_review", "pending"), False),
            (("scoring", "enabled"), True),
            (("risk", "low_score_fraction_medium"), float("nan")),
        ]:
            c = copy.deepcopy(original)
            c[path[0]][path[1]] = value
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "config.json"
                p.write_text(json.dumps(c))
                with self.assertRaises(ValueError):
                    load_config(p)

    def test_quality_blur_contrast_skew_and_edge_proxies(self):
        settings = load_config(CONFIG)["image"]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "source.png"
            im = Image.new("L", (600, 800), 255)
            draw = ImageDraw.Draw(im)
            for y in range(100, 700, 30):
                draw.rectangle((60, y, 540, y + 7), fill=0)
            im.save(p)
            clear = image_metrics(p, settings, 220)
            im.filter(ImageFilter.GaussianBlur(4)).save(p)
            blur = image_metrics(p, settings, 220)
            self.assertLess(blur["edge_variance"], clear["edge_variance"])
            im.rotate(2, fillcolor=255).save(p)
            tilt = image_metrics(p, settings, 220)
            self.assertEqual(abs(tilt["skew_degrees_coarse"]), 2)
            Image.new("L", (600, 800), 180).save(p)
            flat = image_metrics(p, settings)
            self.assertEqual(flat["contrast_p95_p5"], 0)
            draw.rectangle((0, 0, 10, 800), fill=0)
            im.save(p)
            self.assertGreater(max(image_metrics(p, settings)["edge_ink_fractions"]), 0)

    def test_unknowns_and_blockers_not_averaged(self):
        c = load_config(CONFIG)
        r = screen(None, None, [], c)
        self.assertEqual(r["image"]["risk"], "unknown")
        self.assertEqual(r["structure"]["risk"], "unknown")
        b = {"block_label": "text", "block_content": "甲", "block_bbox": [0, 0, 50, 20]}
        n = {
            "parsing_res_list": [b],
            "overall_ocr_res": {"rec_texts": ["乙"], "rec_boxes": [[0, 0, 50, 20]], "rec_scores": [0.999]},
        }
        result = screen(None, reconcile(n, 1), [], c)
        self.assertEqual(result["structure"]["risk"], "high")
        self.assertFalse(result["page_verified"])
        self.assertIsNone(result["total_score"])
        self.assertIn("unknown", result["recognition"]["variant_coverage"])

    def test_score_threshold_boundary(self):
        c = load_config(CONFIG)
        b = {"block_label": "text", "block_content": "甲", "block_bbox": [0, 0, 50, 20]}
        for score, count in ((0.9, 0), (0.899, 1)):
            n = {
                "parsing_res_list": [b],
                "overall_ocr_res": {
                    "rec_texts": ["甲"],
                    "rec_boxes": [[0, 0, 50, 20]],
                    "rec_scores": [score],
                },
            }
            r = reconcile(n, 1, rules=c["ocr_structure"])
            self.assertEqual(len(r["low_score_regions"]), count)


if __name__ == "__main__":
    unittest.main()
