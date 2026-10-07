"""Optional offline development browser check of comparison views; no imports."""

import argparse
import base64
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True)
        context = browser.new_context(offline=True, viewport={"width": 1440, "height": 1100})
        page = context.new_page()
        errors, external, counts = [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: external.append(request.url) if request.url.startswith(("http:", "https:")) else None)
        page.goto((args.bundle / "comparison.html").resolve().as_uri())
        if args.font:
            encoded = base64.b64encode(args.font.read_bytes()).decode()
            page.add_style_tag(content="@font-face{font-family:DevCJK;src:url(data:font/ttf;base64," + encoded + ")}body{font-family:DevCJK,sans-serif}")
        pages = page.locator("#page option").evaluate_all("nodes=>nodes.map(n=>n.value)")
        for number in pages:
            page.locator("#page").select_option(number)
            page.wait_for_function("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
            count = page.locator("article img").count()
            assert count > 0
            page.locator("article details").first.evaluate("node=>node.open=true")
            page.screenshot(path=str(args.output / f"page-{number}.png"))
            counts.append({"physical_page": int(number), "loaded_region_images": count})
        assert not errors and not external
        (args.output / "browser-summary.json").write_text(json.dumps({
            "browser": browser.version, "offline": True, "pages": counts,
            "page_errors": errors, "external_requests": external,
            "confirmed_or_imported": False,
            "boundary": "browser interaction/asset checks; source-image inspection separately recorded",
        }, indent=2) + "\n")
        browser.close()


if __name__ == "__main__":
    main()
