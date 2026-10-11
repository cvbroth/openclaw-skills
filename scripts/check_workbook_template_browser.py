#!/usr/bin/env python3
"""Synthetic-only template import/preview/publish, symbols and native exports.

BASE_URL TEMPLATE_JSON OUTPUT_DIR (contains synthetic.pdf).
"""

import json
from pathlib import Path
import sys
import time
from playwright.sync_api import sync_playwright

base, template_file, output = sys.argv[1:]
root = Path(output)
root.mkdir(parents=True, exist_ok=True)
template = json.loads(Path(template_file).read_text())
with sync_playwright() as pw:
    b = pw.chromium.launch(args=["--no-sandbox"])
    c = b.new_context(viewport={"width": 1366, "height": 900})
    page = c.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def api(path, data=None):
        r = c.request.get(base + path) if data is None else c.request.post(base + path, data=data)
        assert r.ok, r.text()
        return r.json()

    def settled(pid):
        until = time.monotonic() + 180
        while time.monotonic() < until:
            p = api("/api/projects/" + pid)
            if (
                p.get("analysis", {}).get("status") not in ["RUNNING", "QUEUED"]
                and not any(t["status"] in ["RUNNING", "QUEUED", "CANCELLING"] for t in p["tasks"])
                and not any(
                    a.get("preview_render", {}).get("status") in ["RUNNING", "QUEUED"] for a in p["artifacts"]
                )
            ):
                return p
            time.sleep(0.2)
        raise AssertionError("timed out")

    catalog = api("/api/templates")["catalog"]["templates"]
    if not any(t["id"] == template["id"] and t["version"] == template["version"] for t in catalog):
        api("/api/templates", template)
    prefix = "/api/templates/" + template["id"] + "/" + template["version"]
    preview = api(prefix + "/preview", {})
    p = settled(preview["project_id"])
    assert p["tasks"][-1]["status"] == "SUCCEEDED", p["tasks"][-1].get("error")
    api(prefix + "/publish", {})
    page.goto(base + "/templates")
    page.select_option("#library", json.dumps([template["id"], template["version"]], separators=(",", ":")))
    page.click("#load")
    page.wait_for_function(
        "() => document.querySelector('[data-field=\"parameters.option_columns\"] input')?.value==='2'"
    )
    page.screenshot(path=str(root / "synthetic-template.png"))
    page.goto(base)
    page.click("#toggleUpload")
    page.set_input_files("#file", str(root / "synthetic.pdf"))
    page.fill("#projectName", "合成 · 字体与紧凑模板验收")
    page.click("#start")
    page.wait_for_url("**/projects/*")
    pid = page.url.split("/projects/")[1]
    settled(pid)
    page.locator(".new-task summary").click()
    page.select_option("#newEngine", "pdf-text")
    page.fill("#newPages", "1")
    page.click("#newTask")
    p = settled(pid)
    assert p["tasks"][-1]["status"] == "SUCCEEDED"
    a = next(a for a in p["artifacts"] if a["format"] == "markdown")
    page.goto(base + "/p/" + pid + "/review/index.html?right=" + a["artifact_id"])
    page.wait_for_selector("#textMode:not([disabled])")
    page.click("#textMode")
    page.fill(
        "#textEditor", "合成题干：⸺ 和 📖 必须完整保留。\nA. 短选项甲\nB. 短选项乙\nC. 短选项丙\nD. 短选项丁"
    )
    page.click("#saveRevision")
    page.wait_for_function(
        "() => !document.querySelector('#textEditor') || document.querySelector('#textEditor').hidden"
    )
    page.click("#exportText")
    page.wait_for_url("**/projects/*?export_source=*")
    page.wait_for_selector("#exportDialog[open]")
    aid = page.input_value("#formatSource")
    page.select_option(
        "#formatTemplate",
        json.dumps({"id": template["id"], "version": template["version"]}, separators=(",", ":")),
    )
    page.select_option("#paginationMode", "source-pages")
    page.locator("#exportDialog details summary").click()
    page.locator("#paginationFontFit").check()
    page.locator("#paginationMinimum").fill("10")
    page.locator("#paginationContinue").uncheck()
    page.screenshot(path=str(root / "synthetic-export-settings.png"))
    page.click("#formatExisting")
    p = settled(pid)
    task = p["tasks"][-1]
    assert task["status"] == "SUCCEEDED", task.get("error")
    assert task["template_data"]["font_fallbacks"] and task["document_export"]["source_artifact_id"] == aid
    exports = [a for a in p["artifacts"] if a.get("task_id") == task["task_id"] and a.get("role") == "export"]
    assert {a["format"] for a in exports} == {"docx", "pdf"}
    page.goto(base + "/projects/" + pid)
    page.wait_for_selector("#files-exports")
    for a in exports:
        r = c.request.get(base + "/api/projects/" + pid + "/download/" + a["artifact_id"])
        assert r.ok
        (root / ("synthetic." + a["format"])).write_bytes(r.body())
        row = page.locator("#files-exports .artifact-row").filter(has_text=a.get("display_name") or a["name"])
        row.get_by_role("button", name="预览", exact=True).click()
        page.wait_for_function(
            "() => [...document.querySelectorAll('#exportPreviewBody img')].some(i=>i.complete&&i.naturalWidth>0)"
        )
        page.screenshot(path=str(root / ("synthetic-preview-" + a["format"] + ".png")))
        page.click("#closeExportPreview")
    # Historical errors remain intact; presentation explains actual Unicode/remedy.
    message = page.evaluate(
        "() => exportFailureMessage({error:{message:'FONT_MISSING_GLYPHS: ⸺📖'},template_data:{font:{name:'Droid Sans Fallback'}}})"
    )
    assert "U+2E3A" in message and "U+1F4D6" in message and "重新导出" in message
    assert not errors, errors
    (root / "browser-result.json").write_text(
        json.dumps(
            {
                "project_id": pid,
                "template_preview_project_id": preview["project_id"],
                "task_id": task["task_id"],
                "template": task["template"],
                "source_artifact_id": aid,
                "font_fallbacks": task["template_data"]["font_fallbacks"],
                "formats": [a["format"] for a in exports],
                "old_error_message": message,
                "page_errors": errors,
                "OCR_calls": 0,
                "paid_model_calls": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    b.close()
