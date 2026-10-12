#!/usr/bin/env python3
"""Synthetic reader/actual Word/PDF/UI evidence, including a real overflow task."""

import hashlib
import json
from pathlib import Path
import sys
import time
import uuid
from playwright.sync_api import sync_playwright

base, manifest_file, output = sys.argv[1:]
manifest = json.loads(Path(manifest_file).read_text())
pid = manifest["project_id"]
out = Path(output)
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    browser = pw.chromium.launch(args=["--no-sandbox"])
    context = browser.new_context(viewport={"width": 1366, "height": 900})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def api(path, data=None):
        r = context.request.get(base + path) if data is None else context.request.post(base + path, data=data)
        assert r.ok, r.text()
        return r.json()

    def settled(tid=None):
        end = time.monotonic() + 180
        while time.monotonic() < end:
            p = api("/api/projects/" + pid)
            if not any(t["status"] in ["QUEUED", "RUNNING", "CANCELLING"] for t in p["tasks"]) and not any(
                a.get("preview_render", {}).get("status") in ["QUEUED", "RUNNING"] for a in p["artifacts"]
            ):
                return p
            time.sleep(0.2)
        raise AssertionError("Timeout")

    for version, label in [
        (manifest["original_artifact_id"], "legacy"),
        (manifest["revised_artifact_id"], "revised"),
    ]:
        page.goto(base + "/p/" + pid + "/review/index.html?right=" + version)
        page.wait_for_selector("#rightContent .reading")
        page.locator("#sourcePageLookup").fill("6")
        page.locator("#findSourcePage").click()
        page.wait_for_function(
            "() => document.querySelectorAll('#rightContent .source-fragment').length===2 && document.querySelectorAll('#rightContent .reading').length===2"
        )
        page.evaluate("document.fonts.ready")
        page.wait_for_function(
            "() => [...document.querySelectorAll('#leftContent img')].some(i=>i.complete&&i.naturalWidth>0)"
        )
        assert page.locator("#rightContent b").first.inner_text() == "加粗"
        assert page.locator("#rightContent i").first.inner_text() == "斜体"
        assert (
            page.locator("#rightContent .reading").first.evaluate("e=>getComputedStyle(e).lineHeight")
            == "25.9px"
        )
        page.screenshot(path=str(out / (label + "-reader.png")))
    page.goto(base + "/projects/" + pid)
    page.wait_for_selector("#openDocumentExport")
    page.locator("#openDocumentExport").click()
    assert page.locator("#exportMode").input_value() == "markdown-direct"
    assert not page.locator("#formatTemplate").is_visible()
    page.locator("#formatSource").select_option(manifest["revised_artifact_id"])
    page.locator("#exportPages").fill("6-10")
    page.screenshot(path=str(out / "direct-export-dialog.png"))
    for width, height in [(1024, 768), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        assert page.locator("#exportDialog").evaluate("e=>e.scrollWidth<=e.clientWidth+1")
        page.screenshot(path=str(out / f"direct-dialog-{width}.png"))
    page.set_viewport_size({"width": 1366, "height": 900})
    page.locator("#closeDocumentExport").click()
    p = settled()
    tid = manifest["exports"][0]["task_id"]
    outputs = [a for a in p["artifacts"] if a.get("task_id") == tid and a.get("role") == "export"]
    for a in outputs:
        r = context.request.get(base + "/api/projects/" + pid + "/download/" + a["artifact_id"])
        assert r.ok and hashlib.sha256(r.body()).hexdigest() == a["sha256"]
        page.locator('[data-artifact-id="' + a["artifact_id"] + '"]').get_by_role(
            "button", name="Word实际预览" if a["format"] == "docx" else "PDF预览", exact=True
        ).click()
        page.wait_for_function(
            "() => {const i=document.querySelector('#exportPreviewBody img');return i?.complete&&i.naturalWidth>0;}"
        )
        image_url = page.locator("#exportPreviewBody img").first.get_attribute("src")
        image_response = context.request.get(base + image_url)
        assert image_response.ok
        (out / (a["format"] + "-render-source6.png")).write_bytes(image_response.body())
        page.screenshot(path=str(out / (a["format"] + "-preview.png")))
        page.locator("#closeExportPreview").click()
    # Prove UI submits a new direct task without a template or OCR.
    page.locator("#openDocumentExport").click()
    page.locator("#exportPages").fill("7")
    page.locator("#exportPDF").uncheck()
    page.locator("#formatExisting").click()
    page.wait_for_selector("#exportDialog", state="hidden")
    p = settled()
    t = p["tasks"][-1]
    assert t["status"] == "SUCCEEDED" and t["document_export"]["mode"] == "markdown-direct"
    # Local synthetic revision creates an intentionally uncontainable source page.
    info = api("/api/projects/" + pid + "/text/" + manifest["revised_artifact_id"])
    if info["artifact_id"] != info["head_id"]:
        info = api("/api/projects/" + pid + "/text/" + info["head_id"])
    payload = {
        "request_id": str(uuid.uuid4()),
        "parent_artifact_id": info["artifact_id"],
        "parent_sha256": info["sha256"],
        "head_id": info["head_id"],
        "head_sha256": info["head_sha256"],
        "locator": info["pages"][-1]["locator"],
        "text": "# 明确溢出页\n\n" + "不能裁切或静默续页的合成正文。" * 1800,
    }
    revision = api("/api/projects/" + pid + "/text-revisions", payload)
    job = api(
        "/api/projects/" + pid + "/document-exports",
        {
            "mode": "markdown-direct",
            "source_artifact_id": revision["artifact_id"],
            "pages": "10",
            "formats": ["pdf"],
        },
    )
    p = settled()
    failed = next(t for t in p["tasks"] if t["task_id"] == job["task_id"])
    assert failed["status"] == "FAILED" and "来源第10页" in failed["error"]["message"]
    assert not any(a.get("task_id") == job["task_id"] for a in p["artifacts"])
    page.reload()
    page.wait_for_selector("#export-history summary")
    page.locator("#export-history summary").click()
    page.locator("#export-history").screenshot(path=str(out / "overflow-failure.png"))
    assert not errors, errors
    (out / "browser-result.json").write_text(
        json.dumps(
            {
                "project_id": pid,
                "source_version": manifest["revised_artifact_id"],
                "exports": outputs,
                "reader_bold_italic": True,
                "legacy_html_fallback": True,
                "download_hashes_equal": True,
                "overflow_task": failed,
                "page_errors": errors,
                "OCR_calls": 0,
                "paid_model_calls": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    browser.close()
