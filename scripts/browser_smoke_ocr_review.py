"""Optional DEVELOPMENT-ONLY Playwright smoke; screenshots/receipt are private.

Install Playwright in a separate test environment, not production. Tests actual
file:// rendering, filters and JSON download. Does not import or confirm a page.
"""

import argparse
import base64
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--font", type=Path, help="optional developer-only local CJK font, not copied into bundle")
    p.add_argument("--pages", type=int, nargs="+", default=[127, 131, 23, 114, 11])
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    with sync_playwright() as tool:
        browser = tool.chromium.launch(headless=True)
        context = browser.new_context(
            offline=True, accept_downloads=True, viewport={"width": 1440, "height": 1100}
        )
        page = context.new_page()
        errors = []
        external = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "request", lambda r: external.append(r.url) if r.url.startswith(("http:", "https:")) else None
        )
        page.goto((a.bundle / "index.html").resolve().as_uri())
        if a.font:
            encoded = base64.b64encode(a.font.read_bytes()).decode()
            page.add_style_tag(
                content="@font-face{font-family:DevCJK;src:url(data:font/ttf;base64,"
                + encoded
                + ")}body{font-family:DevCJK,sans-serif}"
            )
        page.wait_for_selector("article")
        counts = []
        for physical in a.pages:
            page.locator("#page").select_option(str(physical))
            page.locator("#risk").select_option("")
            page.locator("#status").select_option("")
            count = page.locator("article").count()
            assert count > 1
            # Inspect actual loaded crop assets rather than only successful navigation.
            page.locator("article img").first.scroll_into_view_if_needed()
            page.wait_for_function('document.querySelector("article img").naturalWidth > 0')
            assert page.locator("article img").first.evaluate("(img)=>img.complete && img.naturalHeight>0")
            page.screenshot(path=str(a.output / f"page-{physical}.png"))
            risks = {127: "recovered", 131: "recovered", 23: "source_damage", 114: "order"}
            if physical in risks:
                page.locator("#risk").select_option(risks[physical])
                assert page.locator("article img").count() > 0
                page.locator("article img").first.scroll_into_view_if_needed()
                page.locator("article details").first.evaluate("e=>e.open=true")
                page.screenshot(path=str(a.output / f"page-{physical}-risk.png"))
                page.locator("#risk").select_option("")
            counts.append({"physical_page": physical, "displayed_cards_including_page_controls": count})
        page.locator("#page").select_option("127" if 127 in a.pages else str(a.pages[0]))
        if 127 in a.pages:
            page.locator("#risk").select_option("recovered")
            assert page.locator("article img").count() > 0
        page.locator("#status").select_option("unconfirmed")
        card = page.locator("article").filter(has=page.locator("textarea")).first
        card.locator("input").last.fill("Development browser smoke only; not a user confirmation")
        card.get_by_role("button", name="加入导出草稿", exact=True).click()
        page.locator("#reviewer").select_option("developer-agent")
        page.locator("#name").fill("development-browser-smoke")
        with page.expect_download() as event:
            page.locator("#export").click()
        event.value.save_as(a.output / "browser-test-confirmation.json")
        receipt = json.loads((a.output / "browser-test-confirmation.json").read_bytes())
        assert receipt["reviewer_type"] == "developer-agent" and len(receipt["operations"]) == 1
        assert receipt["operations"][0]["action"] == "confirm_text"
        assert not errors and not external
        (a.output / "browser-summary.json").write_text(
            json.dumps(
                {
                    "browser": browser.version,
                    "offline": True,
                    "scheme": "file://",
                    "pages": counts,
                    "page_errors": errors,
                    "external_requests": external,
                    "json_export_operations": len(receipt["operations"]),
                    "imported_into_demo": False,
                    "developer_local_cjk_font": bool(a.font),
                    "boundary": "automated browser smoke, not user visual or whole-page content acceptance",
                },
                indent=2,
            )
            + "\n"
        )
        browser.close()


if __name__ == "__main__":
    main()
