#!/usr/bin/env python3
"""Run against an isolated fixture-only service; requires Playwright/Chromium.

Usage: check_template_export_browser.py BASE_URL EVIDENCE_DIR
The evidence directory must contain synthetic169.pdf, never a business original.
"""

import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile
from playwright.sync_api import sync_playwright

base = sys.argv[1].rstrip("/")
out = Path(sys.argv[2]).resolve()
checks = []
errors = []


def record(name):
    checks.append(name)
    print(name, flush=True)


with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))

    def api(path, data=None, method="post"):
        response = (
            context.request.get(base + path)
            if data is None
            else getattr(context.request, method)(base + path, data=data)
        )
        assert response.ok, response.text()
        return response.json()

    def settled(pid):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            p = api("/api/projects/" + pid)
            live = {"QUEUED", "RUNNING", "CANCELLING"}
            if (
                p.get("analysis", {}).get("status") not in live
                and not any(t["status"] in live for t in p["tasks"])
                and not any(a.get("preview_render", {}).get("status") in live for a in p["artifacts"])
            ):
                return p
            time.sleep(0.2)
        raise AssertionError("service did not settle")

    page.goto(base)
    page.click("#toggleUpload")
    page.set_input_files("#file", str(out / "synthetic169.pdf"))
    page.fill("#projectName", "模板导出验证 · 合成169页原件")
    page.click("#start")
    page.wait_for_url("**/projects/*")
    pid = page.url.split("/projects/")[1]
    settled(pid)
    page.locator(".new-task summary").click()
    page.select_option("#newEngine", "pdf-text")
    page.fill("#newPages", "6-10")
    with page.expect_response(lambda r: "/tasks" in r.url and r.request.method == "POST"):
        page.click("#newTask")
    p = settled(pid)
    assert p["tasks"][-1]["status"] == "SUCCEEDED"
    assert not any(
        a["format"] in {"docx", "pdf"} and a["artifact_id"] != p["source_artifact_id"] for a in p["artifacts"]
    )
    old = next(a for a in p["artifacts"] if a["format"] == "markdown")
    source = next(a for a in p["artifacts"] if a["artifact_id"] == p["source_artifact_id"])
    hashes = {a["artifact_id"]: a["sha256"] for a in p["artifacts"] if a.get("path")}
    record("browser upload -> direct PDF text extraction: only pages 6-10, no Office output")
    review = base + "/p/" + pid + "/review/index.html?right=" + old["artifact_id"]
    page.goto(review)
    page.wait_for_selector("#textMode:not([disabled])")
    page.click("#toggleToolbar")
    page.fill("#leftPageInput", "169")
    page.press("#leftPageInput", "Enter")
    assert page.input_value("#leftPageInput") == "169"
    page.fill("#leftPageInput", "170")
    page.press("#leftPageInput", "Enter")
    assert "越界" in page.locator("#status").text_content()
    page.select_option("#quality", "unknown")
    assert page.locator("#sourcePosition option").count() == 169
    page.select_option("#quality", "")
    page.click("#commentPanel summary")
    page.select_option("#reviewer", "developer-agent")
    page.fill("#comment", "COMMENT_SENTINEL_不应写入正文")
    page.click("#saveServer")
    page.wait_for_function("() => document.querySelector('#status').textContent.includes('评语已保存')")
    record("original page input, quality filtering, artifact comment save")
    page.click("#textMode")
    page.fill("#textEditor", "修订第6页完整正文。\n\n浏览器保存验证。")
    page.click("#exportText")
    page.get_by_role("dialog").get_by_role("button", name="取消", exact=True).click()
    assert page.input_value("#textEditor").startswith("修订第6页")
    page.click("#exportText")
    page.get_by_role("dialog").get_by_role("button", name="保存", exact=True).click()
    page.wait_for_url("**/projects/*?export_source=*")
    page.wait_for_selector("#exportDialog[open]")
    new = page.input_value("#formatSource")
    assert new != old["artifact_id"]
    record("unsaved export cancel retains draft; save creates revision and selects it in dialog")
    page.screenshot(path=str(out / "export-dialog-desktop.png"))
    for width, height in [(1366, 768), (1024, 768), (390, 844), (320, 640)]:
        page.set_viewport_size({"width": width, "height": height})
        page.locator("#exportDialog details summary").click() if not page.locator(
            "#exportDialog details"
        ).get_attribute("open") else None
        bounds = page.locator("#exportDialog").evaluate(
            "(d)=>({left:d.getBoundingClientRect().left,right:d.getBoundingClientRect().right,scroll:d.scrollWidth,client:d.clientWidth})"
        )
        assert (
            bounds["left"] >= 0 and bounds["right"] <= width + 1 and bounds["scroll"] <= bounds["client"] + 1
        ), bounds
        if width == 390:
            page.screenshot(path=str(out / "export-dialog-mobile.png"))
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.fill("#exportPages", "11")
    page.click("#formatExisting")
    page.wait_for_function(
        "() => document.querySelector('#exportError').textContent.includes('没有文字记录')"
    )
    page.fill("#exportPages", "全部")
    page.uncheck("#exportPDF")
    page.click("#formatExisting")
    page.wait_for_selector("#exportDialog", state="hidden")
    p = settled(pid)
    assert p["tasks"][-1]["status"] == "SUCCEEDED", p["tasks"][-1].get("error")
    word = next(a for a in p["artifacts"] if a.get("role") == "export" and a["format"] == "docx")
    assert word["export_source"]["artifact_id"] == new and word["export_source"]["source_pages"] == [
        6,
        7,
        8,
        9,
        10,
    ]
    record("desktop/narrow dialog fits; page11 rejected; revised text Word-only real export")
    page.reload()
    page.wait_for_selector("#files-exports .artifact-row")
    # URL deep link reopens the dialog once on a new document; close it for file actions.
    if page.locator("#exportDialog").is_visible():
        page.click("#closeDocumentExport")
    row = page.locator('[data-artifact-id="' + word["artifact_id"] + '"]')
    row.get_by_role("button", name="预览", exact=True).click()
    page.wait_for_selector("#exportPreview img")
    page.screenshot(path=str(out / "word-export-preview.png"))
    with page.expect_download() as downloading:
        page.locator("#exportPreviewBody a").click()
    downloading.value.save_as(str(out / "revised.docx"))
    page.click("#closeExportPreview")
    row.locator("summary").click()
    page.once("dialog", lambda d: d.accept("修订版 Word 导出"))
    row.get_by_role("button", name="改名", exact=True).click()
    page.wait_for_function(
        "() => document.querySelector('#files-exports').textContent.includes('修订版 Word 导出')"
    )
    row = page.locator('[data-artifact-id="' + word["artifact_id"] + '"]')
    if not row.locator("details").get_attribute("open"):
        row.locator("summary").click()
    row.get_by_role("button", name="删除（可恢复）", exact=True).click()
    page.wait_for_selector(
        '#files-recycled [data-artifact-id="' + word["artifact_id"] + '"]', state="attached"
    )
    page.locator("#files-recycled summary").click()
    page.locator("#files-recycled").get_by_role("button", name="恢复", exact=True).click()
    page.wait_for_selector('#files-exports [data-artifact-id="' + word["artifact_id"] + '"]')
    record("independent Word preview/download/rename/recycle/restore")
    # Historical text: discard draft, then carry the viewed historical version.
    page.goto(base + "/p/" + pid + "/review/index.html?right=" + new)
    page.wait_for_selector("#textMode:not([disabled])")
    page.click("#textMode")
    page.fill("#textEditor", "DISCARD_SENTINEL")
    page.click("#exportText")
    page.get_by_role("dialog").get_by_role("button", name="放弃", exact=True).click()
    page.wait_for_selector("#exportDialog[open]")
    assert page.input_value("#formatSource") == new
    page.click("#closeDocumentExport")
    page.goto(base + "/p/" + pid + "/review/index.html?right=" + new)
    page.wait_for_selector("#textHistory:not([disabled])")
    page.click("#textHistory")
    page.select_option("#revisionHistory", old["artifact_id"])
    page.get_by_role("button", name="查看所选版本", exact=True).click()
    page.wait_for_function("() => document.querySelector('#textState').textContent.includes('历史版本只读')")
    page.click("#exportText")
    page.wait_for_selector("#exportDialog[open]")
    assert page.input_value("#formatSource") == old["artifact_id"]
    page.fill("#exportPages", "7-9")
    page.uncheck("#exportWord")
    page.check("#exportPDF")
    page.click("#formatExisting")
    page.wait_for_selector("#exportDialog", state="hidden")
    p = settled(pid)
    assert p["tasks"][-1]["status"] == "SUCCEEDED", p["tasks"][-1].get("error")
    pdf = next(a for a in p["artifacts"] if a.get("role") == "export" and a["format"] == "pdf")
    assert pdf["export_source"]["artifact_id"] == old["artifact_id"] and pdf["export_source"][
        "source_pages"
    ] == [7, 8, 9]
    record("discard preserves saved version; history UI -> exact historical PDF-only pages7-9")
    page.goto(base + "/projects/" + pid)
    page.wait_for_selector("#files-exports .artifact-row")
    page.locator('[data-artifact-id="' + pdf["artifact_id"] + '"]').get_by_role(
        "button", name="预览", exact=True
    ).click()
    page.wait_for_selector("#exportPreview img")
    page.screenshot(path=str(out / "pdf-export-preview.png"))
    with page.expect_download() as downloading:
        page.locator("#exportPreviewBody a").click()
    downloading.value.save_as(str(out / "historical-pages7-9.pdf"))
    page.click("#closeExportPreview")
    page.screenshot(path=str(out / "project-page.png"), full_page=True)
    page.goto(review)
    page.wait_for_selector("#rightArtifact")
    choices = page.locator("#rightArtifact option").evaluate_all("(els)=>els.map(e=>e.value)")
    assert word["artifact_id"] not in choices and pdf["artifact_id"] not in choices
    page.screenshot(path=str(out / "comparison-page.png"))
    p = settled(pid)
    assert hashes.items() <= {a["artifact_id"]: a["sha256"] for a in p["artifacts"] if a.get("path")}.items()
    with page.expect_download() as downloading:
        page.goto(base + "/projects/" + pid)
        page.click("#export")
    downloading.value.save_as(str(out / "synthetic-project-offline.zip"))
    with zipfile.ZipFile(out / "synthetic-project-offline.zip") as z:
        assert b"saveFormat" not in z.read("review/editor.js")
        z.extractall(out / "offline-project")
        project = json.loads(z.read("project.json"))
        for a in project["artifacts"]:
            if a["artifact_id"] in hashes:
                assert hashlib.sha256(z.read(a["path"])).hexdigest() == hashes[a["artifact_id"]]
    offline = context.new_page()
    offline.on("pageerror", lambda e: errors.append(str(e)))
    offline.goto((out / "offline-project/review/index.html").as_uri())
    offline.wait_for_selector("#exportText[disabled]")
    assert not errors, errors
    record(
        "comparison excludes exports; offline package updated, original/text hashes retained, offline export disabled"
    )
    (out / "browser-results.json").write_text(
        json.dumps(
            {
                "browser": browser.version,
                "project_id": pid,
                "checks": checks,
                "page_errors": errors,
                "paid_model_calls": 0,
                "CSP_bypass": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    browser.close()
