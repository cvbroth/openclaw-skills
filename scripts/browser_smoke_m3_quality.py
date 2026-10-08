"""Development-only file:// viewer checks; not transcription/quality validation."""

import argparse
import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def check(root, output, screenshot=None, font=None):
    structure = json.loads((root / "structure.json").read_bytes())
    rows = structure["pages"]
    errors, requests = [], []
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True, args=["--no-sandbox"])
        version = browser.version
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on(
            "request",
            lambda req: requests.append(req.url) if req.url.startswith(("http:", "https:")) else None,
        )
        page.goto((root / "index.html").resolve().as_uri())
        if font:
            import base64

            encoded = base64.b64encode(font.read_bytes()).decode()
            page.add_style_tag(
                content="@font-face{font-family:DevChinese;src:url(data:font/ttf;base64,"
                + encoded
                + ")}body,pre{font-family:DevChinese,sans-serif!important}"
            )
            page.evaluate("document.fonts.ready")
        for row in rows:
            physical = row["physical_page"]
            page.select_option("#page", str(physical))
            page.wait_for_function(
                'document.querySelector("#image").complete && document.querySelector("#image").naturalWidth>0'
            )
            assert page.locator("#image").evaluate("(im)=>[im.naturalWidth,im.naturalHeight]") == [
                row["source"]["width"],
                row["source"]["height"],
            ]
            assert (
                hashlib.sha256((root / row["source"]["image"]).read_bytes()).hexdigest()
                == row["source"]["sha256"]
            )
            if row["text"]:
                assert page.locator("#text").text_content() == row["text"]
            if row["quality"]:
                assert json.loads(page.locator("#assessment").text_content()) == row["quality"]
            assert page.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
            if screenshot and physical == 23:
                page.screenshot(path=str(screenshot))
        for quality in ["good", "usable_with_defects", "poor", "undetermined", "unjudged"]:
            page.select_option("#quality", quality)
            expected = [
                r
                for r in rows
                if (r["quality"]["overall_quality"] if r["quality"] else "unjudged") == quality
            ]
            assert page.locator("#page option").count() == len(expected)
        page.select_option("#quality", "")
        for status in sorted({r["status"] for r in rows}):
            page.select_option("#status", status)
            assert page.locator("#page option").count() == sum(r["status"] == status for r in rows)
        browser.close()
    assert not errors and not requests
    output.write_text(
        json.dumps(
            {
                "browser": version,
                "pages_checked": [r["physical_page"] for r in rows],
                "image_hash_dimensions_text_quality_and_filters": "passed",
                "js_errors": errors,
                "external_requests": requests,
                "scope": "UI mechanics; not human evaluation or accuracy",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    check(args.root, args.output, args.screenshot, args.font)
