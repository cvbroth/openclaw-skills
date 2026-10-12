"""All operations through the UI; API GETs only observe final immutable files."""

from pathlib import Path
import json
import time
import sys
from playwright.sync_api import sync_playwright

base, manifest, output = sys.argv[1:]
f = json.loads(Path(manifest).read_text())
out = Path(output)
out.mkdir(parents=True, exist_ok=True)
pid = f["project_id"]
results = []
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    c = b.new_context(viewport={"width": 1366, "height": 900})
    page = c.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def project():
        return c.request.get(base + "/api/projects/" + pid).json()

    def open_dialog(aid=None):
        if page.locator("#exportDialog").evaluate("e=>e.open"):
            page.locator("#closeDocumentExport").click()
        page.locator("#openDocumentExport").click()
        page.locator("#formatSource").select_option(aid or f["artifact_id"])

    def settings(pages, blank=False, word=False, pdf=True):
        page.locator("#exportWord").set_checked(word)
        page.locator("#exportPDF").set_checked(pdf)
        page.locator("#exportPages").fill(pages)
        page.wait_for_function("()=>!document.querySelector('#directBlankMissing').disabled")
        page.locator("#directBlankMissing").set_checked(blank)
        page.wait_for_function("()=>!document.querySelector('#directBlankMissing').disabled")

    def inspect(pages, blank=False):
        before = {t["task_id"] for t in project()["tasks"]}
        page.locator("#checkDirectRange").click()
        end = time.monotonic() + 900
        while time.monotonic() < end:
            tasks = [
                t
                for t in project()["tasks"]
                if t["task_id"] not in before and t.get("document_export", {}).get("purpose") == "check"
            ]
            if tasks and tasks[-1]["status"] not in ["QUEUED", "RUNNING", "CANCELLING"]:
                t = tasks[-1]
                if t["status"] == "CANCELLED":
                    time.sleep(0.2)
                    continue
                page.wait_for_function(
                    "()=>document.querySelector('#paperStatus').textContent.includes('检查完成')||document.querySelector('#paperStatus').textContent.includes('检查通过')"
                )
                results.append(
                    {
                        "pages": pages,
                        "blank": blank,
                        "task_id": t["task_id"],
                        "status": t["status"],
                        "ready": t.get("direct_report", {}).get("ready"),
                        "issues": t.get("direct_report", {}).get("issues"),
                    }
                )
                return t
            time.sleep(0.3)
        raise AssertionError(page.locator("#paperStatus").inner_text())

    def generate(label):
        before = {t["task_id"] for t in project()["tasks"]}
        page.locator("#formatExisting").click()
        end = time.monotonic() + 900
        while time.monotonic() < end:
            p = project()
            tasks = [
                t
                for t in p["tasks"]
                if t["task_id"] not in before and t.get("document_export", {}).get("purpose") == "export"
            ]
            if tasks and tasks[-1]["status"] not in ["QUEUED", "RUNNING", "CANCELLING"]:
                t = tasks[-1]
                assert t["status"] == "SUCCEEDED", t.get("error")
                artifacts = [
                    a
                    for a in p["artifacts"]
                    if a.get("task_id") == t["task_id"] and a.get("role") == "export"
                ]
                for a in artifacts:
                    r = c.request.get(base + "/api/projects/" + pid + "/download/" + a["artifact_id"])
                    assert r.ok
                    (out / (label + "." + a["format"])).write_bytes(r.body())
                    (out / (label + "-" + a["format"] + "-mapping.json")).write_text(
                        json.dumps(a["source_output_mapping"], ensure_ascii=False, indent=2)
                    )
                results.append(
                    {
                        "export": label,
                        "task_id": t["task_id"],
                        "formats": [a["format"] for a in artifacts],
                        "mapping": t["direct_report"]["groups"],
                    }
                )
                return t
            if page.locator("#exportError").inner_text():
                raise AssertionError(page.locator("#exportError").inner_text())
            time.sleep(0.3)
        raise AssertionError("UI export timeout")

    page.goto(base + "/projects/" + pid)
    page.wait_for_selector("#openDocumentExport")
    open_dialog()
    settings("1-60")
    assert all("来源物理页 " + str(n) in page.locator("#directMissingList").inner_text() for n in range(1, 6))
    t = inspect("1-60")
    assert not t["direct_report"]["ready"] and {i["source_page"] for i in t["direct_report"]["issues"]} == {
        1,
        2,
        3,
        4,
        5,
    }
    page.locator("#directMissingList").scroll_into_view_if_needed()
    page.screenshot(path=str(out / "range1-60-off.png"))
    page.locator("#directBlankMissing").check()
    page.wait_for_function("()=>!document.querySelector('#directBlankMissing').disabled")
    t = inspect("1-60", True)
    assert t["direct_report"]["ready"] and len(t["direct_report"]["placeholders"]) == 5
    page.locator("#paperResult").scroll_into_view_if_needed()
    page.screenshot(path=str(out / "range1-60-on.png"))
    generate("range1-60-placeholder-pdf")
    open_dialog()
    settings("6-60")
    t = inspect("6-60")
    assert t["direct_report"]["ready"] and not t["direct_report"]["placeholders"]
    assert all(g["source_page"] != 145 for g in t["direct_report"]["groups"])
    page.screenshot(path=str(out / "range6-60.png"))
    # Real input events immediately invalidate the old result, even while requests are pending.
    page.locator("#exportPages").fill("1-60")
    page.locator("#exportPages").fill("144-146")
    page.locator("#exportPages").fill("8")
    assert page.locator("#paperResult").inner_text() == "" and page.locator("#exportError").inner_text() == ""
    page.wait_for_function("()=>!document.querySelector('#directBlankMissing').disabled")
    t = inspect("8")
    assert [g["source_page"] for g in t["direct_report"]["groups"]] == [8]
    time.sleep(1)
    assert (
        "来源 145" not in page.locator("#paperResult").inner_text()
        and "本次来源范围：8" in page.locator("#paperResult").inner_text()
    )
    page.screenshot(path=str(out / "rapid-range8.png"))
    page.locator("#paperSourcePage").fill("8")
    page.locator("#updatePaper").click()
    page.wait_for_function(
        "()=>document.querySelector('#paperStatus').textContent.includes('PDF纸张检查完成')"
    )
    page.wait_for_function(
        "()=>[...document.querySelectorAll('#paperResult img')].some(i=>i.complete&&i.naturalWidth>0)"
    )
    page.locator("#paperResult").scroll_into_view_if_needed()
    page.screenshot(path=str(out / "basic-formats-paper.png"))
    page.locator("#exportPreviewPage").click()
    assert page.locator("#exportPages").input_value() == "8"
    page.wait_for_function("()=>!document.querySelector('#directBlankMissing').disabled")
    page.locator("#exportWord").check()
    page.wait_for_function("()=>!document.querySelector('#directBlankMissing').disabled")
    generate("preview8-both")
    open_dialog()
    settings("1-6", True, True, False)
    t = inspect("1-6", True)
    assert t["direct_report"]["ready"]
    generate("range1-6-placeholder-word")
    for word, pdf, label in [(False, True, "pdf"), (True, False, "word")]:
        open_dialog()
        settings("144-146", True, word, pdf)
        t = inspect("144-146", True)
        assert t["direct_report"]["ready"] and [g["status"] for g in t["direct_report"]["groups"]] == [
            "READY",
            "PLACEHOLDER",
            "READY",
        ]
        page.locator("#paperResult").scroll_into_view_if_needed()
        page.screenshot(path=str(out / ("range145-" + label + ".png")))
        generate("range144-146-" + label)
    for source, reason in [("61", "溢出"), ("62", "真实表格")]:
        open_dialog()
        settings(source, True)
        t = inspect(source, True)
        assert not t["direct_report"]["ready"] and not t["direct_report"]["placeholders"]
        assert reason in page.locator("#paperResult").inner_text()
        page.screenshot(path=str(out / ("blocked-" + source + ".png")))
    open_dialog(f["broken_artifact_id"])
    settings("63", True)
    t = inspect("63", True)
    assert not t["direct_report"]["ready"] and not t["direct_report"]["placeholders"]
    assert "资源" in page.locator("#paperResult").inner_text()
    page.screenshot(path=str(out / "resource-blocked.png"))
    for width, height in [(1920, 1080), (1024, 768), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        assert page.locator("#exportDialog").evaluate("e=>e.scrollWidth<=e.clientWidth+1")
        page.screenshot(path=str(out / f"controls-{width}.png"))
    assert not errors, errors
    (out / "browser-results.json").write_text(
        json.dumps(
            {
                "results": results,
                "page_errors": errors,
                "UI_operations": True,
                "OCR_calls": 0,
                "paid_model_calls": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    b.close()
