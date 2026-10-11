#!/usr/bin/env python3
"""Exercise the isolated workbench using an existing, synthetic PDF-text project.

BASE_URL EVIDENCE_DIR PROJECT_ID. Never run mutation checks on business data.
"""

import hashlib
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright

base, output, pid = sys.argv[1:]
out = Path(output)
out.mkdir(parents=True, exist_ok=True)
checks, errors, metrics = [], [], []
with sync_playwright() as pw:
    browser = pw.chromium.launch(args=["--no-sandbox"])
    context = browser.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    p = context.request.get(base + "/api/projects/" + pid).json()
    assert "合成" in p["name"], "Mutation tests require a synthetic project"
    current = next(a for a in reversed(p["artifacts"]) if a["format"] == "markdown" and not a.get("recycled"))
    review = base + "/p/" + pid + "/review/index.html?right=" + current["artifact_id"]

    def loaded():
        page.wait_for_function(
            "() => [...document.querySelectorAll('#leftContent img')].some(i=>i.complete&&i.naturalWidth>0)&&!!document.querySelector('#rightContent .reading,#rightContent pre')"
        )
        page.wait_for_selector("#textMode:not([disabled])", state="attached")

    page.goto(review)
    loaded()
    assert not page.locator("#auxPanel").is_visible()
    assert not page.locator("#saveRevision").is_visible()
    assert not page.locator(".editbar").count()
    for width, height in [(1366, 768), (1920, 1080), (1024, 768), (768, 900), (390, 844), (320, 640)]:
        page.set_viewport_size({"width": width, "height": height})
        measure = page.evaluate(
            "() => ({width:innerWidth,height:innerHeight,body:document.body.scrollWidth,main:document.querySelector('main').clientHeight,header:document.querySelector('header').clientHeight})"
        )
        assert measure["body"] <= width, measure
        if width >= 1366:
            assert measure["main"] / height >= 0.8, measure
        metrics.append(measure)
        page.screenshot(path=str(out / f"reading-{width}.png"))
        page.click("#toggleAux")
        assert page.locator("#auxPanel").is_visible()
        bounds = page.evaluate(
            "() => {let m=document.querySelector('main').getBoundingClientRect(),a=document.querySelector('#auxPanel').getBoundingClientRect();return {separate:a.left>=m.right-1||a.top>=m.bottom-1,overflow:document.body.scrollWidth>innerWidth}}"
        )
        assert bounds["separate"] and not bounds["overflow"], bounds
        for group in ["source", "versions", "reading", "technical", "comments"]:
            page.click("[data-panel=" + group + "]")
            assert page.locator("[data-section=" + group + "]").is_visible()
        page.screenshot(path=str(out / f"panel-{width}.png"))
        page.click("#closeAux")
    checks.append(
        "six viewport sizes; no horizontal overflow/overlay; desktop body >=80%; all auxiliary groups reachable"
    )
    page.set_viewport_size({"width": 1366, "height": 768})
    page.evaluate(
        "() => {document.querySelector('#leftPane').scrollTop=130;document.querySelector('#rightPane').scrollTop=40}"
    )
    scroll = page.evaluate("() => ['left','right'].map(s=>document.querySelector('#'+s+'Pane').scrollTop)")
    page.click("#toggleAux")
    page.click("#closeAux")
    page.wait_for_timeout(100)
    after = page.evaluate("() => ['left','right'].map(s=>document.querySelector('#'+s+'Pane').scrollTop)")
    assert scroll == after, (scroll, after)
    right = after[1]
    page.locator("#leftPane").hover()
    page.mouse.wheel(0, 200)
    page.wait_for_timeout(150)
    assert page.locator("#rightPane").evaluate("(e)=>e.scrollTop") == right
    checks.append("auxiliary open/close retains both scroll positions; left wheel does not move right")
    page.click("#textMode")
    original = page.input_value("#textEditor")
    draft = original + "\n\nWORKBENCH_DRAFT_SENTINEL"
    page.fill("#textEditor", draft)
    page.click("#toggleAux")
    page.click("[data-panel=reading]")
    page.click("#closeAux")
    assert page.input_value("#textEditor") == draft
    page.fill("#leftPageInput", "7")
    page.press("#leftPageInput", "Enter")
    assert page.input_value("#textEditor") == draft
    for operation in ["page", "file", "filter", "reading", "cancel"]:
        if operation == "page":
            page.fill("#rightPageInput", "2")
            page.press("#rightPageInput", "Enter")
        elif operation == "file":
            aid = page.locator("#rightArtifact option").first.get_attribute("value")
            page.select_option("#rightArtifact", aid)
        elif operation == "filter":
            page.click("#toggleAux")
            page.click("[data-panel=source]")
            page.select_option("#errorFilter", "no")
        elif operation == "reading":
            page.click("#toggleAux")
            page.click("[data-panel=reading]")
            page.select_option("#markdownMode", "source")
        else:
            page.click("#cancelEdit")
        page.get_by_role("dialog").get_by_role("button", name="取消", exact=True).click()
        assert page.input_value("#textEditor") == draft, operation
        assert page.input_value("#rightArtifact") == current["artifact_id"]
        assert page.input_value("#rightPageInput") == "1"
        if operation in {"filter", "reading"}:
            page.click("#closeAux")
    page.screenshot(path=str(out / "editing-draft.png"))
    page.click("#cancelEdit")
    page.get_by_role("dialog").get_by_role("button", name="放弃", exact=True).click()
    assert not page.locator("#textEditor").count()
    checks.append(
        "panel and independent left navigation retain editor; page/file/error filter/cancel mode all protect dirty draft"
    )
    page.click("#toggleAux")
    page.click("[data-panel=source]")
    page.fill("#sourcePageLookup", "7")
    page.click("#findSourcePage")
    page.wait_for_function("() => document.querySelector('#rightPageInput').value==='2'")
    page.fill("#sourcePageLookup", "11")
    page.click("#findSourcePage")
    assert "没有对应" in page.locator("#mapMessage").text_content()
    assert page.input_value("#rightPageInput") == "2"
    page.select_option("#errorFilter", "yes")
    assert page.locator("#rightPosition option").count() == 1
    assert page.input_value("#rightPosition") == "-1"
    page.select_option("#errorFilter", "")
    page.select_option("#quality", "unknown")
    assert page.locator("#sourcePosition option").count() == 169
    page.select_option("#quality", "")
    checks.append("registered source-page navigation, absent source keeps selection, error/quality filters")
    page.click("[data-panel=comments]")
    page.select_option("#reviewer", "developer-agent")
    page.fill("#comment", "WORKBENCH_COMMENT_SENTINEL")
    page.click("#saveServer")
    page.wait_for_function("() => document.querySelector('#status').textContent.includes('评语已保存')")
    with page.expect_download() as download:
        page.click("#export")
    feedback = out / "feedback.json"
    download.value.save_as(str(feedback))
    receipt = json.loads(feedback.read_text())
    assert any(c["text"] == "WORKBENCH_COMMENT_SENTINEL" for c in receipt["comments"])
    page.set_input_files("#import", str(feedback))
    page.wait_for_function("() => document.querySelector('#status').textContent.includes('导入成功')")
    page.select_option("#commentScope", "source_page")
    page.fill("#comment", "SOURCE_COMMENT_SENTINEL")
    page.click("#saveServer")
    page.wait_for_function("() => document.querySelector('#status').textContent.includes('评语已保存')")
    page.select_option("#commentScope", "artifact")
    assert page.input_value("#comment") == "WORKBENCH_COMMENT_SENTINEL"
    page.click("[data-panel=source]")
    page.select_option("#commentFilter", "yes")
    assert page.locator("#rightPosition option").count() == 1
    page.select_option("#commentFilter", "no")
    assert page.locator("#rightPosition option").count() == 4
    page.select_option("#commentFilter", "")
    source = next(a for a in p["artifacts"] if a["artifact_id"] == p["source_artifact_id"])
    with page.expect_download() as download:
        page.locator("#leftContent a[download]").click()
    original_file = out / "downloaded-original.pdf"
    download.value.save_as(str(original_file))
    assert hashlib.sha256(original_file.read_bytes()).hexdigest() == source["sha256"]
    checks.append("artifact/source comments, JSON round trip, comment filters, original download hash")
    page.click("[data-panel=versions]")
    page.wait_for_selector("#revisionHistory")
    history = page.locator("#revisionHistory option").evaluate_all("(items)=>items.map(o=>o.value)")
    historical = next(a for a in history if a != current["artifact_id"])
    page.select_option("#revisionHistory", historical)
    page.click("#viewRevision")
    page.wait_for_selector("#restoreForEdit", state="visible")
    assert page.locator("#historyState").is_visible() and not page.locator("#textMode").is_visible()
    page.screenshot(path=str(out / "history-readonly.png"))
    page.click("#restoreForEdit")
    page.wait_for_selector("#textEditor")
    assert page.input_value("#rightArtifact") != historical
    assert not page.locator("#textEditor").get_attribute("readonly")
    restored = page.input_value("#rightArtifact")
    page.fill("#textEditor", page.input_value("#textEditor") + "\n\nNEW_REVISION_SENTINEL")
    pending_draft = page.input_value("#textEditor")
    page.route(
        "**/text-revisions",
        lambda route: route.fulfill(
            status=503, content_type="application/json", body='{"reason":"synthetic-save-failure"}'
        ),
    )
    page.click("#saveRevision")
    page.wait_for_function("() => document.querySelector('#textState').textContent.includes('保存失败')")
    assert page.input_value("#textEditor") == pending_draft
    page.unroute("**/text-revisions")
    page.click("#saveRevision")
    page.wait_for_selector("#textEditor", state="detached")
    page.wait_for_function('(old)=>document.querySelector("#rightArtifact").value!==old', arg=restored)
    page.click("#closeAux")
    page.reload()
    loaded()
    assert not page.locator("#auxPanel").is_visible() and not page.locator("#textEditor").count()
    checks.append(
        "history read-only -> restore as new -> edit/save immutable revision; each entry defaults reading/panel closed"
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.click("#mobile")
    assert page.locator("#rightPageInput").is_visible()
    page.click("#textMode")
    assert page.locator("#textEditor").is_visible()
    page.click("#toggleAux")
    assert page.evaluate("() => document.body.scrollWidth<=innerWidth")
    page.screenshot(path=str(out / "editing-mobile.png"))
    page.click("#cancelEdit")
    checks.append("failed save retains draft; narrow screen navigation/editor/panel remain usable")
    assert not errors, errors
    (out / "layout-results.json").write_text(
        json.dumps(
            {
                "browser": browser.version,
                "metrics": metrics,
                "checks": checks,
                "errors": errors,
                "paid_model_calls": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    browser.close()
print(json.dumps(checks, ensure_ascii=False, indent=2))
