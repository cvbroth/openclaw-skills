"""Offline UI/assets/export check; this does not verify transcription accuracy."""
import argparse
import base64
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True)
        context = browser.new_context(offline=True, accept_downloads=True, viewport={"width": 1500, "height": 1100})
        page = context.new_page()
        errors, external, records = [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: external.append(request.url) if request.url.startswith(("http:", "https:")) else None)
        page.goto((args.bundle / "index.html").resolve().as_uri())
        if args.font:
            encoded = base64.b64encode(args.font.read_bytes()).decode()
            page.add_style_tag(content="@font-face{font-family:DevCJK;src:url(data:font/ttf;base64," + encoded + ")}body,textarea{font-family:DevCJK,sans-serif}")
        pages = page.locator("#page option").evaluate_all("nodes=>nodes.map(n=>n.value)")
        for number in pages:
            page.locator("#page").select_option(number)
            page.wait_for_function("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
            assert page.locator("#main select").input_value() == ""
            assert page.locator("#notes").input_value() == ""
            bounds = page.locator("textarea[readonly]").bounding_box()
            assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 1500
            record = page.evaluate("()=>{const p=data.pages.find(x=>String(x.physical_page)===document.getElementById('page').value);return {physical_page:p.physical_page,image_sha256:p.source.sha256,width:document.images[0].naturalWidth,height:document.images[0].naturalHeight,text_equal:document.querySelector('textarea[readonly]').value===p.text}}")
            assert record["text_equal"]
            records.append(record)
            if int(number) in (12, 23, 168):
                page.screenshot(path=str(args.output / f"page-{number}.png"))
        with page.expect_download() as download:
            page.locator("#export").click()
        target = args.output / "empty-review-ui-test.json"
        download.value.save_as(target)
        exported = json.loads(target.read_text())
        assert len(exported["pages"]) == len(pages)
        assert all(row["rating"] == row["notes"] == "" for row in exported["pages"])
        # Isolated browser-memory test only. This is never a human confirmation or an imported ledger.
        page.locator("#main select").select_option("有少量错误")
        page.locator("#notes").fill("合成UI测试；不是用户审核")
        page.locator("#page").select_option(pages[0])
        page.locator("#page").select_option(pages[-1])
        assert page.locator("#main select").input_value() == "有少量错误"
        assert page.locator("#notes").input_value() == "合成UI测试；不是用户审核"
        assert not errors and not external
        (args.output / "browser-summary.json").write_text(json.dumps({"browser": browser.version, "offline": True,
            "pages": records, "page_errors": errors, "external_requests": external,
            "empty_export_rows": len(exported["pages"]), "synthetic_memory_edit_persists_across_page_navigation": True,
            "human_reviews": 0, "boundary": "UI, assets and export only; no correctness assessment"}, indent=2) + "\n")
        browser.close()


if __name__ == "__main__":
    main()
