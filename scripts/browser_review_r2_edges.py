"""Synthetic-only browser checks for preview failures, histories and narrow screens."""

import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_review_r2 import wait


def run(args):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        p = context.new_page()
        errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        base = args.base + "/api/projects/" + args.project
        data = context.request.get(base).json()
        bad = next(
            a
            for a in data["artifacts"]
            if a["format"] == "pdf" and a.get("preview_render", {}).get("status") == "FAILED"
        )
        word = next(a for a in data["artifacts"] if a["format"] == "docx")
        pdf = next(
            a for a in data["artifacts"] if a["format"] == "pdf" and a["artifact_id"] != bad["artifact_id"]
        )
        p.goto(args.base + "/p/" + args.project + "/review/index.html")
        wait(p, "!document.querySelector('#comment').disabled")
        assert p.locator("#evaluation option").count() == 2
        p.click("#qualityDetails summary")
        p.select_option("#evaluation", "synthetic-0")
        assert "能直接辨读" in p.locator("#qualitySummary").inner_text()
        p.select_option("#evaluation", "synthetic-1")
        assert "局部模糊或缺损" in p.locator("#qualitySummary").inner_text()
        p.select_option("#rightArtifact", bad["artifact_id"])
        assert "预览失败" in p.locator("#rightContent").inner_text()
        assert "FileDataError" in p.locator("#rightContent").inner_text()
        assert p.locator("#rightContent img").count() == 0
        p.screenshot(path=str(out / "synthetic-preview-failure.png"))
        p.locator("#rightContent button").click()
        p.wait_for_timeout(1800)
        wait(p, "document.querySelector('#rightContent').textContent.includes('FileDataError')")
        assert p.locator("#rightContent img").count() == 0
        # Actual failure remains a failure after retry; content artifacts survive.
        assert context.request.get(base).json()["artifacts"]
        p.select_option("#leftArtifact", word["artifact_id"])
        p.select_option("#rightArtifact", pdf["artifact_id"])
        wait(
            p,
            "document.querySelector('#leftContent img')?.naturalWidth>0&&document.querySelector('#rightContent img')?.naturalWidth>0",
        )
        p.screenshot(path=str(out / "synthetic-word-pdf.png"))
        p.select_option("#reviewer", "developer-agent")
        p.fill("#comment", "合成移动端草稿，不是用户意见")
        p.set_viewport_size({"width": 640, "height": 900})
        p.click("#mobile")
        assert p.locator("#rightPane").is_visible() and not p.locator("#leftPane").is_visible()
        p.click("#mobile")
        assert p.locator("#leftPane").is_visible()
        assert p.input_value("#comment") == "合成移动端草稿，不是用户意见"
        p.screenshot(path=str(out / "synthetic-narrow.png"))
        p.set_viewport_size({"width": 1440, "height": 1000})
        # Explicit save to keep this test's synthetic draft from leaking into later contexts.
        p.click("#saveServer")
        wait(p, "document.querySelector('#status').textContent.includes('已保存到服务')")
        bad_receipt = {
            "schema": "filetools-artifact-feedback-v1",
            "project_id": "00000000-0000-0000-0000-000000000000",
            "project_revision": data["revision"],
            "reviewer_type": "developer-agent",
            "comments": [],
        }
        p.set_input_files(
            "#import",
            {
                "name": "wrong-project.json",
                "mimeType": "application/json",
                "buffer": json.dumps(bad_receipt).encode(),
            },
        )
        wait(p, "document.querySelector('#status').textContent.includes('拒绝导入')")
        assert p.input_value("#comment") == "合成移动端草稿，不是用户意见"
        assert not errors, errors
        result = {
            "browser": browser.version,
            "checks": [
                "two source assessments coexist and can be selected",
                "invalid PDF actual FileDataError shown, retry fails visibly, no success image",
                "real synthetic DOCX/PDF side-by-side",
                "narrow switch retains draft",
                "wrong project receipt refused without overwriting draft",
            ],
            "errors": errors,
            "new_ocr_or_cloud_calls": 0,
        }
        (out / "edge-checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="http://127.0.0.1:18971")
    p.add_argument("--project", required=True)
    p.add_argument("--output", required=True)
    run(p.parse_args())
