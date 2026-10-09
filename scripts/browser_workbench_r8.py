"""Real Chromium exercise on an explicitly synthetic R8 project."""

import argparse
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright


def main(args):
    args.out.mkdir(parents=True, exist_ok=True)
    evidence = {"synthetic": True, "screens": []}
    with sync_playwright() as w:
        browser = w.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        url = args.base + "/p/" + args.project + "/review/index.html?right=" + args.artifact
        page.goto(url)
        page.wait_for_selector("#textMode:not([disabled])")
        assert page.evaluate('document.body.classList.contains("toolbar-collapsed")')
        assert not page.locator("#commentPanel").evaluate("(n)=>n.open")
        assert page.locator("#leftPageInput").is_visible() and page.locator("#rightPageInput").is_visible()
        page.fill("#leftPageInput", "169")
        page.locator("#leftPageInput").press("Enter")
        page.wait_for_selector('#leftContent img[alt="原件物理第169页"]')
        page.fill("#sourcePageLookup", "23")
        page.click("#findSourcePage")
        assert page.input_value("#rightPosition") == "17"
        page.wait_for_selector("#rightContent .reading")
        assert "片段18" in page.locator("#rightContent").inner_text()
        before = page.locator("main").evaluate("(n)=>n.clientHeight")
        page.screenshot(path=str(args.out / "01-collapsed-1440.png"))
        page.click("#toggleToolbar")
        after = page.locator("main").evaluate("(n)=>n.clientHeight")
        assert before > after
        page.locator("#qualityDetails").evaluate("(n)=>n.open=true")
        assert page.locator("#qualityDetails").evaluate("(n)=>getComputedStyle(n).position") == "static"
        page.click("#closeQuality")
        page.screenshot(path=str(args.out / "02-expanded-1440.png"))
        page.click("#toggleToolbar")
        # Source location uses the existing R7 save/discard/cancel handler.
        page.click("#textMode")
        page.wait_for_selector("#textEditor")
        text = page.input_value("#textEditor") + "\n\nR8未保存草稿。"
        page.fill("#textEditor", text)
        page.fill("#sourcePageLookup", "24")
        page.click("#findSourcePage")
        page.get_by_role("button", name="取消", exact=True).click()
        assert page.input_value("#textEditor") == text and page.input_value("#rightPosition") == "17"
        page.click("#toggleToolbar")
        page.click("#toggleToolbar")
        assert page.input_value("#textEditor") == text
        page.fill("#sourcePageLookup", "24")
        page.click("#findSourcePage")
        page.get_by_role("button", name="放弃", exact=True).click()
        assert page.input_value("#rightPosition") == "18"
        page.fill("#sourcePageLookup", "22")
        page.click("#findSourcePage")
        assert "没有对应结果" in page.locator("#mapMessage").inner_text()
        page.select_option("#rightArtifact", args.multiple)
        page.fill("#sourcePageLookup", "23")
        page.click("#findSourcePage")
        assert page.locator("#sourceCandidates").is_visible()
        assert page.locator("#sourceCandidates option").count() == 3
        page.select_option("#sourceCandidates", "1")
        assert page.input_value("#rightPosition") == "1"
        page.select_option("#rightArtifact", args.unmapped)
        page.click("#findSourcePage")
        assert "没有已登记" in page.locator("#mapMessage").inner_text()
        page.select_option("#rightArtifact", args.artifact)
        page.fill("#sourcePageLookup", "23")
        page.click("#findSourcePage")
        # Verify no horizontal viewport overflow at the required widths.
        for width, height in [(1920, 1080), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_timeout(150)
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            assert (
                page.locator("#leftPageInput").is_visible() and page.locator("#rightPageInput").is_visible()
            )
            page.screenshot(path=str(args.out / f"03-workbench-{width}.png"))
        evidence["collapsed_main_height"] = before
        evidence["expanded_main_height"] = after
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(args.base + "/templates")
        page.wait_for_selector("#fields input")
        page.screenshot(path=str(args.out / "04-template-layout.png"))
        original = context.request.get(args.base + "/api/templates/questions-zh-cn/1.0.0").json()
        original.update(id="r8-browser-" + str(int(time.time())), version="1.0.0", name="R8 浏览器合成模板")
        imported = args.out / "import.json"
        imported.write_text(json.dumps(original))
        page.set_input_files("#import", str(imported))
        for _ in range(30):
            if "JSON已载入" in page.locator("#message").inner_text():
                break
            page.wait_for_timeout(100)
        assert page.locator("#preview").is_disabled() and page.locator("#publish").is_disabled()
        page.click("#save")
        for _ in range(50):
            if "草稿已保存" in page.locator("#message").inner_text():
                break
            page.wait_for_timeout(100)
        assert json.loads(page.input_value("#library")) == [original["id"], "1.0.0"]
        assert not page.locator("#preview").is_disabled()
        evidence["saved_template"] = {"id": original["id"], "version": "1.0.0"}
        for name in ["style.docx", "style.dotx", "multisection.docx"]:
            page.set_input_files("#wordImport", str(args.samples / name))
            for _ in range(40):
                if (
                    page.locator("#wordReport").is_visible()
                    and "尚未保存" in page.locator("#message").inner_text()
                ):
                    break
                page.wait_for_timeout(100)
            assert page.locator("#preview").is_disabled()
            page.select_option("#wordSection", "1" if name == "multisection.docx" else "0")
            page.select_option("#wordFont", "Droid Sans Fallback")
            page.click("#applyWord")
            for _ in range(40):
                if "已应用选定" in page.locator("#message").inner_text():
                    break
                page.wait_for_timeout(100)
            doc = json.loads(page.input_value("#config"))
            assert doc["word_styles"]["paragraphs"]["Normal"]["line_mode"] == "exact"
            page.click("#save")
            for _ in range(50):
                if "草稿已保存" in page.locator("#message").inner_text():
                    break
                page.wait_for_timeout(100)
            assert not page.locator("#preview").is_disabled(), page.locator("#message").inner_text()
            page.screenshot(path=str(args.out / ("05-import-" + name + ".png")))
            evidence[name] = {
                "id": doc["id"],
                "version": doc["version"],
                "section": doc["import_source"]["section_index"],
            }
        page.click("#preview")
        page.wait_for_selector("#previewLink:not([hidden])")
        evidence["preview_project_url"] = page.locator("#previewLink").get_attribute("href")
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(args.out / "06-templates-narrow.png"))
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        evidence["browser"] = browser.version
        evidence["page_errors"] = errors
        assert not errors, errors
        (args.out / "browser.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:18971")
    p.add_argument("--project", required=True)
    p.add_argument("--artifact", required=True)
    p.add_argument("--multiple", required=True)
    p.add_argument("--unmapped", required=True)
    p.add_argument("--samples", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    main(p.parse_args())
