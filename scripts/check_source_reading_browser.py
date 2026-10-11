#!/usr/bin/env python3
"""Verify source-page evidence and single-fragment writes on a synthetic project.

Usage: BASE_URL FIXTURE_MANIFEST EVIDENCE_DIR
"""

import json
from pathlib import Path
import sys
import zipfile
from playwright.sync_api import sync_playwright

base, fixture, output = sys.argv[1:]
f = json.loads(Path(fixture).read_text())
out = Path(output)
out.mkdir(parents=True, exist_ok=True)
pid = f["project_id"]
aid = f["artifact_id"]
checks = []
errors = []
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    c = b.new_context(viewport={"width": 1366, "height": 768})
    page = c.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))

    def get(aid):
        response = c.request.get(base + "/api/projects/" + pid + "/text/" + aid)
        assert response.ok, response.text()
        return response.json()

    p = c.request.get(base + "/api/projects/" + pid).json()
    assert "合成" in p["name"]
    before = get(aid)

    def source(n, count):
        page.fill("#sourcePageLookup", str(n))
        page.press("#sourcePageLookup", "Enter")
        page.wait_for_function(
            '(n)=>document.querySelector("#rightNotice").textContent.includes("原件物理第"+n+"页")', arg=n
        )
        assert page.locator(".source-fragment").count() == count
        page.wait_for_function(
            "() => ![...document.querySelectorAll('.fragment-body')].some(e=>e.textContent.includes('正在加载'))"
        )

    def loaded():
        page.wait_for_selector("#textMode:not([disabled])", state="attached")
        page.wait_for_function(
            "() => [...document.querySelectorAll('#leftContent img')].some(i=>i.complete&&i.naturalWidth>0)"
        )

    page.goto(base + "/p/" + pid + "/review/index.html?right=" + aid)
    loaded()
    assert not page.locator("#auxPanel").is_visible()
    source(22, 1)
    assert "ONE_P22" in page.locator("#rightContent").text_content()
    source(23, 3)
    assert page.locator(".source-fragment").evaluate_all("(rows)=>rows.map(r=>Number(r.dataset.index))") == [
        1,
        2,
        3,
    ]
    text = page.locator("#rightContent").text_content()
    assert text.index("FIRST_P23") < text.index("SECOND_P23") < text.index("CROSS_23_24")
    assert (
        "跨页片段" in text
        and "23、24" in text
        and "印刷页码未登记" in page.locator("#rightNotice").text_content()
    )
    assert "1个片段来源未知" in page.locator("#rightNotice").text_content()
    assert not page.locator("#textMode").is_visible()
    page.fill("#leftPageInput", "23")
    page.press("#leftPageInput", "Enter")
    page.wait_for_function(
        "() => document.querySelector('#leftContent img')?.complete&&document.querySelector('#leftContent img')?.naturalWidth>0"
    )
    page.screenshot(path=str(out / "source23-three-fragments-1366.png"))
    page.click("#locateSelectedSource")
    page.wait_for_selector(".source-fragment")
    assert page.locator(".source-fragment").count() == 3
    page.fill("#leftPageInput", "24")
    page.press("#leftPageInput", "Enter")
    assert page.input_value("#sourcePageLookup") == "23"
    source(24, 1)
    assert "CROSS_23_24" in page.locator("#rightContent").text_content()
    page.wait_for_function(
        "() => document.querySelector('#leftContent img')?.complete&&document.querySelector('#leftContent img')?.naturalWidth>0"
    )
    page.screenshot(path=str(out / "source24-complete-cross-fragment.png"))
    source(26, 0)
    assert (
        "没有登记" in page.locator("#rightContent").text_content()
        and "CROSS_23_24" not in page.locator("#rightContent").text_content()
    )
    source(25, 1)
    assert "SYNTHETIC_FAILURE" in page.locator("#rightContent").text_content()
    checks.append(
        "30 original pages / 6 fragments: one, three ordered same-page fragments, cross-page whole text, failure, absent-page clears old text; independent left navigation"
    )
    page.click("#toggleAux")
    page.click("[data-panel=source]")
    page.select_option("#errorFilter", "yes")
    page.select_option("#commentFilter", "yes")
    page.select_option("#quality", "good")
    source(23, 3)
    assert "忽略错误/评论筛选" in page.locator("#rightNotice").text_content()
    page.click("#closeAux")
    assert not page.locator("#auxPanel").is_visible()
    source(23, 3)
    page.fill("#rightPageInput", "2")
    page.press("#rightPageInput", "Enter")
    assert "被当前筛选排除" in page.locator("#pageNavigationStatus").text_content()
    assert page.locator(".source-fragment").count() == 3
    page.click("#toggleAux")
    page.click("[data-panel=source]")
    page.select_option("#errorFilter", "")
    page.select_option("#commentFilter", "")
    page.select_option("#quality", "")
    page.click("#closeAux")
    checks.append(
        "explicit source lookup includes all fragments under quality/error/comment filters; normal position remains filtered"
    )
    page.route("**/content/fixture-2.js", lambda route: route.abort())
    source(23, 3)
    assert "文字加载失败" in page.locator('.source-fragment[data-index="2"]').text_content()
    assert (
        "FIRST_P23" in page.locator("#rightContent").text_content()
        and "CROSS_23_24" in page.locator("#rightContent").text_content()
    )
    page.unroute("**/content/fixture-2.js")
    source(23, 3)
    # Comments bind stable original locator, not the card ordinal within the source page.
    page.locator('.source-fragment[data-index="2"] button').click()
    page.wait_for_selector("#textMode:not([hidden]):not([disabled])")
    page.click("#toggleAux")
    page.click("[data-panel=comments]")
    page.select_option("#reviewer", "developer-agent")
    page.fill("#comment", "COMMENT_FOR_STABLE_FRAGMENT_2")
    page.click("#saveServer")
    page.wait_for_function("() => document.querySelector('#status').textContent.includes('评语已保存')")
    page.click("#closeAux")
    page.click("#textMode")
    page.fill("#textEditor", "EDIT_ONLY_SECOND_P23 · 仅修改第二片段。")
    page.screenshot(path=str(out / "source23-edit-second-fragment.png"))
    draft = page.input_value("#textEditor")
    page.click("#toggleAux")
    page.click("#closeAux")
    assert page.input_value("#textEditor") == draft
    for action in ["source", "position", "file"]:
        if action == "source":
            page.fill("#sourcePageLookup", "24")
            page.press("#sourcePageLookup", "Enter")
        elif action == "position":
            page.fill("#rightPageInput", "1")
            page.press("#rightPageInput", "Enter")
        else:
            page.select_option("#rightArtifact", f["unmapped_id"])
        page.get_by_role("dialog").get_by_role("button", name="取消", exact=True).click()
        assert page.input_value("#textEditor") == draft
        assert page.input_value("#rightArtifact") == aid and page.input_value("#rightPageInput") == "3"
    page.route(
        "**/text-revisions",
        lambda route: route.fulfill(
            status=503, content_type="application/json", body='{"reason":"synthetic-failure"}'
        ),
    )
    page.click("#saveRevision")
    page.wait_for_function("() => document.querySelector('#textState').textContent.includes('保存失败')")
    assert page.input_value("#textEditor") == draft
    page.unroute("**/text-revisions")
    page.click("#saveRevision")
    page.wait_for_selector("#textEditor", state="detached")
    page.wait_for_function('(old)=>document.querySelector("#rightArtifact").value!==old', arg=aid)
    new = page.input_value("#rightArtifact")
    after = get(new)
    for i, (old, current) in enumerate(zip(before["pages"], after["pages"])):
        if i == 2:
            assert (
                current["text"] == draft
                and current["locator"] == old["locator"]
                and current["source_page"] == 23
            )
        else:
            assert current == old, (i, current, old)
    assert after["pages"][3]["source_pages"] == [23, 24]
    source(23, 3)
    assert "EDIT_ONLY_SECOND_P23" in page.locator("#rightContent").text_content()
    feedback = c.request.get(base + "/api/projects/" + pid + "/feedback").json()["receipt"]["comments"]
    assert any(
        x["locator"] == before["pages"][2]["locator"]
        and x["text"] == "COMMENT_FOR_STABLE_FRAGMENT_2"
        and x["artifact_id"] == aid
        for x in feedback
    )
    checks.append(
        "selected fragment 3 saved under its stable locator only; five neighbors unchanged; cross-page mapping retained; failed-save/source/position/file cancellation retains draft; comment locator preserved"
    )
    # Historical aggregate, then explicit restore to a new editable version.
    page.select_option("#rightArtifact", aid)
    page.wait_for_selector("#historyState", state="visible")
    source(23, 3)
    assert (
        "SECOND_P23" in page.locator("#rightContent").text_content()
        and "EDIT_ONLY_SECOND_P23" not in page.locator("#rightContent").text_content()
    )
    page.locator('.source-fragment[data-index="2"] button').click()
    page.wait_for_selector("#restoreForEdit", state="visible")
    assert not page.locator("#textMode").is_visible()
    page.screenshot(path=str(out / "history-source23.png"))
    page.click("#restoreForEdit")
    page.wait_for_selector("#textEditor")
    restored = page.input_value("#rightArtifact")
    assert restored not in {aid, new}
    assert get(restored)["pages"] == before["pages"]
    page.click("#cancelEdit")
    page.wait_for_selector(".source-fragment")
    assert page.locator(".source-fragment").count() == 3
    page.click("#exportText")
    page.wait_for_selector("#exportDialog[open]")
    assert page.input_value("#formatSource") == restored
    checks.append(
        "history preserves same page aggregation; read-only -> explicit restore/new version retains all source relationships; export selects restored version"
    )
    # Unmapped legacy data must stay useful via its independent stable fragment positions.
    page.goto(base + "/p/" + pid + "/review/index.html?right=" + f["unmapped_id"])
    loaded()
    source(23, 0)
    assert "缺少可靠来源页映射" in page.locator("#rightContent").text_content()
    page.fill("#rightPageInput", "3")
    page.press("#rightPageInput", "Enter")
    page.wait_for_selector("#textMode:not([hidden]):not([disabled])")
    page.click("#textMode")
    assert page.input_value("#textEditor") == before["pages"][2]["text"]
    page.click("#cancelEdit")
    checks.append(
        "missing mappings do not infer fragment index as physical page; stable unmapped fragments still independently editable"
    )
    page.goto(base + "/p/" + pid + "/review/index.html?right=" + f["whole_id"])
    loaded()
    source(23, 0)
    page.fill("#rightPageInput", "1")
    page.press("#rightPageInput", "Enter")
    page.wait_for_selector("#textMode:not([hidden]):not([disabled])")
    page.click("#textMode")
    whole_text = page.input_value("#textEditor")
    assert "FIRST_P23" in whole_text and "CROSS_23_24" in whole_text
    page.fill("#textEditor", "WHOLE_DOC_REVISION\n" + whole_text)
    page.click("#saveRevision")
    page.wait_for_selector("#textEditor", state="detached")
    whole_revised = get(page.input_value("#rightArtifact"))
    assert len(whole_revised["pages"]) == 1 and whole_revised["pages"][0]["locator"] == {"kind": "document"}
    assert whole_revised["pages"][0]["source_page"] is None
    checks.append(
        "verified whole-document legacy text can independently edit/save, without synthesizing page or fragment mapping"
    )
    page.goto(base + "/p/" + pid + "/review/index.html?right=" + restored)
    loaded()
    metrics = []
    for width, height in [(1920, 1080), (1366, 768), (1024, 768), (768, 900), (390, 844), (320, 640)]:
        page.set_viewport_size({"width": width, "height": height})
        if width <= 600 and not page.locator("#sourcePageLookup").is_visible():
            page.click("#mobile")
        assert page.locator("#sourcePageLookup").is_visible() and not page.locator("#auxPanel").is_visible()
        source(23, 3)
        bounds = page.evaluate(
            "() => ({width:innerWidth,height:innerHeight,scroll:document.body.scrollWidth,main:document.querySelector('main').clientHeight})"
        )
        assert bounds["scroll"] <= width, bounds
        metrics.append(bounds)
        page.screenshot(path=str(out / f"source23-{width}.png"))
        page.click("#toggleAux")
        assert page.evaluate(
            "() => {let a=document.querySelector('#auxPanel').getBoundingClientRect(),m=document.querySelector('main').getBoundingClientRect();return a.left>=m.right-1||a.top>=m.bottom-1}"
        )
        page.click("#closeAux")
    page.goto(base + "/projects/" + pid)
    page.wait_for_selector("#files-original .artifact-row")
    with page.expect_download() as download:
        page.click("#export")
    package = out / "source-reading-offline.zip"
    download.value.save_as(str(package))
    with zipfile.ZipFile(package) as archive:
        assert "review/source-reader.js" in archive.namelist()
        archive.extractall(out / "offline")
    offline = c.new_page()
    offline.on("pageerror", lambda e: errors.append(str(e)))
    offline.goto((out / "offline/review/index.html").resolve().as_uri())
    offline.select_option("#rightArtifact", restored)
    offline.fill("#sourcePageLookup", "23")
    offline.press("#sourcePageLookup", "Enter")
    offline.wait_for_function(
        "() => document.querySelectorAll('.source-fragment').length===3&&!document.querySelector('#rightContent').textContent.includes('正在加载')"
    )
    assert "CROSS_23_24" in offline.locator("#rightContent").text_content()
    assert offline.locator("#exportText").is_disabled()
    checks.append(
        "failed fragment asset is explicit and keeps neighbors; offline package includes source reader and aggregates page23 without server writes"
    )
    assert not errors, errors
    (out / "source-reading-results.json").write_text(
        json.dumps(
            {
                "browser": b.version,
                "checks": checks,
                "metrics": metrics,
                "page_errors": errors,
                "paid_model_calls": 0,
                "OCR_calls": 0,
                "original_fragments": before["pages"],
                "revised_fragments": after["pages"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    b.close()
print(json.dumps(checks, ensure_ascii=False, indent=2))
