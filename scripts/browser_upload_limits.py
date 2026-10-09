"""Check real upload UI without recognition calls; oversized descriptor is UI-only."""

import argparse
import json
from pathlib import Path
import time
from playwright.sync_api import sync_playwright


def run(base, output):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as w:
        browser = w.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        errors, calls = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request", lambda request: calls.append(request.url) if "/api/uploads" in request.url else None
        )
        page.goto(base)
        page.wait_for_selector("#toggleUpload")
        page.click("#toggleUpload")
        deadline = time.monotonic() + 10
        while "512 MiB" not in page.locator("#uploadLimits").inner_text():
            assert time.monotonic() < deadline
            time.sleep(0.05)
        limits = page.request.get(base + "/api/limits").json()
        text = page.locator("#uploadLimits").inner_text()
        assert limits == {"upload_bytes": 536870912, "max_pdf_pages": 1000, "max_selected_pages": 5}
        assert "1000 页" in text and "5 页" in text
        page.evaluate(
            "Object.defineProperty(document.querySelector('#file'),'files',{value:[{name:'oversize.png',size:536870913}]})"
        )
        page.click("#start")
        assert "512 MiB" in page.locator("#message").inner_text()
        assert not calls and not errors
        page.locator("#upload").screenshot(path=str(out / "upload-ui.png"))
        result = {
            "browser": browser.version,
            "actual_development_limits": limits,
            "upload_limit_text": text,
            "frontend_oversize_descriptor_rejected": True,
            "upload_requests": len(calls),
            "js_errors": errors,
        }
        (out / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18971")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    run(arguments.base, arguments.output)
