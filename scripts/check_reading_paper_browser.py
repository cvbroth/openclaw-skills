#!/usr/bin/env python3
"""Synthetic UI evidence: actual paper PDF, parameter updates and explicit partial range."""

import hashlib
import json
from pathlib import Path
import sys
import time
import uuid
from playwright.sync_api import sync_playwright

base, manifest_path, output = sys.argv[1:]
manifest = json.loads(Path(manifest_path).read_text())
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

    def settled():
        end = time.monotonic() + 180
        while time.monotonic() < end:
            p = api("/api/projects/" + pid)
            if not any(t["status"] in ["QUEUED", "RUNNING", "CANCELLING"] for t in p["tasks"]) and not any(
                a.get("preview_render", {}).get("status") in ["QUEUED", "RUNNING"] for a in p["artifacts"]
            ):
                return p
            time.sleep(0.2)
        raise AssertionError("Timeout")

    def inspection(n, enabled=None):
        end = time.monotonic() + 180
        while time.monotonic() < end:
            p = api("/api/projects/" + pid)
            t = p["tasks"][-1]
            r = t.get("direct_report", {})
            if (
                t.get("document_export", {}).get("purpose") == "preview"
                and t["status"] == "SUCCEEDED"
                and r.get("groups", [{}])[0].get("source_page") == n
                and (enabled is None or r["policy"]["enabled"] == enabled)
            ):
                if (
                    not any(t["status"] in ["QUEUED", "RUNNING", "CANCELLING"] for t in p["tasks"])
                    and "完成" in page.locator("#paperStatus").inner_text()
                ):
                    page.wait_for_function(
                        "()=>[...document.querySelectorAll('#paperResult img')].length>0&&[...document.querySelectorAll('#paperResult img')].every(i=>i.complete&&i.naturalWidth>0)"
                    )
                    return t, api("/api/projects/" + pid + "/direct-results/" + t["task_id"])
            time.sleep(0.2)
        raise AssertionError(page.locator("#paperStatus").inner_text())

    def save_image(data, name):
        r = context.request.get(base + data["images"][0])
        assert r.ok
        (out / name).write_bytes(r.body())

    page.goto(base + "/projects/" + pid)
    page.wait_for_selector("#openDocumentExport")
    page.locator("#openDocumentExport").click()
    page.locator("#formatSource").select_option(manifest["revised_artifact_id"])
    page.locator("#paperSourcePage").fill("6")
    page.locator("#updatePaper").click()
    normal, normal_data = inspection(6, False)
    assert normal_data["report"]["ready"]
    save_image(normal_data, "paper-source6.png")
    page.locator("#paperStatus").scroll_into_view_if_needed()
    page.screenshot(path=str(out / "paper-source6-ui.png"))
    for width, height in [(1024, 768), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        assert page.locator("#exportDialog").evaluate("e=>e.scrollWidth<=e.clientWidth+1")
        page.locator("#paperStatus").scroll_into_view_if_needed()
        page.screenshot(path=str(out / f"paper-ui-{width}.png"))
    page.set_viewport_size({"width": 1366, "height": 900})
    page.locator("#closeDocumentExport").click()
    # Only a local revision, preserving all other locators and source relations.
    info = api("/api/projects/" + pid + "/text/" + manifest["revised_artifact_id"])
    info = api("/api/projects/" + pid + "/text/" + info["head_id"])
    loc = next(p["locator"] for p in info["pages"] if p["source_page"] == 8)
    revised = api(
        "/api/projects/" + pid + "/text-revisions",
        {
            "request_id": str(uuid.uuid4()),
            "parent_artifact_id": info["artifact_id"],
            "parent_sha256": info["sha256"],
            "head_id": info["head_id"],
            "head_sha256": info["head_sha256"],
            "locator": loc,
            "text": "# 紧凑边界验证\n\n" + "\n\n".join("正常长段落。" * 16 for _ in range(20)),
        },
    )
    page.reload()
    page.wait_for_selector("#openDocumentExport")
    page.locator("#openDocumentExport").click()
    page.locator("#formatSource").select_option(revised["artifact_id"])
    page.locator("#paperSourcePage").fill("8")
    page.locator("#updatePaper").click()
    overflow, overflow_data = inspection(8, False)
    assert not overflow_data["report"]["ready"]
    assert overflow_data["report"]["preview_parameters"]["pdf"]["overflow"]
    page.locator("#paperStatus").scroll_into_view_if_needed()
    page.screenshot(path=str(out / "paper-overflow-ui.png"))
    page.locator("#directLine").fill("1.2")
    page.locator("#directGap").fill("0")
    page.locator("#directCompact").check()
    compact, compact_data = inspection(8, True)
    assert compact_data["report"]["ready"]
    save_image(compact_data, "paper-compact-source8.png")
    page.locator("#paperStatus").scroll_into_view_if_needed()
    page.screenshot(path=str(out / "paper-compact-ui.png"))
    page.locator("#exportPages").fill("8")
    page.locator("#exportWord").uncheck()
    page.locator("#formatExisting").click()
    page.wait_for_selector("#exportDialog", state="hidden")
    p = settled()
    t = p["tasks"][-1]
    assert t["status"] == "SUCCEEDED", t.get("error")
    final = next(a for a in p["artifacts"] if a.get("task_id") == t["task_id"] and a.get("role") == "export")
    r = context.request.get(base + "/api/projects/" + pid + "/download/" + final["artifact_id"])
    assert r.ok and hashlib.sha256(r.body()).hexdigest() == final["sha256"]
    (out / "dense-final.pdf").write_bytes(r.body())
    # Existing source10 deliberately overflows. A complete check must list it, without exporting.
    page.locator("#openDocumentExport").click()
    page.locator("#exportPages").fill("6-10")
    page.locator("#checkDirectRange").click()
    page.wait_for_function("()=>document.querySelector('#paperStatus').textContent.includes('已检查')")
    page.screenshot(path=str(out / "page-progress-ui.png"))
    p = settled()
    page.wait_for_function("()=>document.querySelector('#paperStatus').textContent.includes('检查完成')")
    checked = p["tasks"][-1]
    assert checked["document_export"]["purpose"] == "check"
    assert not checked["direct_report"]["ready"]
    assert any(i["source_page"] == 10 for i in checked["direct_report"]["issues"])
    assert not any(a.get("task_id") == checked["task_id"] for a in p["artifacts"])
    page.locator("#paperStatus").scroll_into_view_if_needed()
    page.screenshot(path=str(out / "range-blockers-ui.png"))
    page.locator("#closeDocumentExport").click()
    page.reload()
    page.wait_for_selector("#openDocumentExport")
    page.locator("#openDocumentExport").click()
    page.locator("#formatSource").select_option(revised["artifact_id"])
    page.locator("#exportPages").fill("6-9")
    page.locator("#exportWord").uncheck()
    page.locator("#directLine").fill("1.2")
    page.locator("#directGap").fill("0")
    page.locator("#directCompact").check()
    page.locator("#formatExisting").click()
    page.wait_for_selector("#exportDialog", state="hidden")
    p = settled()
    partial = p["tasks"][-1]
    assert partial["status"] == "SUCCEEDED", partial.get("error")
    partial_file = next(
        a for a in p["artifacts"] if a.get("task_id") == partial["task_id"] and a.get("role") == "export"
    )
    assert partial_file["export_source"]["source_pages"] == [6, 7, 8, 9] and partial_file["export_source"][
        "excluded_source_pages"
    ] == [10]
    page.reload()
    page.wait_for_selector('[data-artifact-id="' + partial_file["artifact_id"] + '"]')
    row = page.locator('[data-artifact-id="' + partial_file["artifact_id"] + '"]')
    assert "明确未包含：10" in row.inner_text()
    row.screenshot(path=str(out / "explicit-partial-range.png"))
    assert not errors, errors
    (out / "paper-browser-result.json").write_text(
        json.dumps(
            {
                "normal_preview": normal["task_id"],
                "overflow_preview": overflow["task_id"],
                "compact_preview": compact["task_id"],
                "final_pdf": final,
                "blocked_check": checked["task_id"],
                "explicit_partial": partial_file,
                "page_errors": errors,
                "OCR_calls": 0,
                "paid_model_calls": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    browser.close()
