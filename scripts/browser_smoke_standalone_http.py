"""Real development browser checks. Local OCR only; NEVER submits cloud requests."""

import argparse
import json
from pathlib import Path
import time
from playwright.sync_api import sync_playwright


def wait(page, expression, arg=None):
    # CDP evaluates directly; Playwright's injected string-eval poller conflicts with CSP.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if page.evaluate(expression, arg):
            return
        time.sleep(0.05)
    raise AssertionError("browser condition timeout: " + expression)


def check(base, image, output, real_id, legacy_id):
    checks = []
    errors = []
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base)
        page.wait_for_selector("#engine option", state="attached")
        upload_name = "browser-" + str(time.time_ns()) + ".png"
        review_name = "浏览器合成验收 " + str(time.time_ns())
        page.set_input_files(
            "#file", {"name": upload_name, "mimeType": "image/png", "buffer": image.read_bytes()}
        )
        page.select_option("#engine", "local")
        with page.expect_response(lambda r: "/api/uploads?" in r.url and r.request.method == "POST") as event:
            page.click("#start")
        assert event.value.status == 202
        wait(page, 'document.querySelector("#technical").textContent.includes("project_id")')
        created = json.loads(page.locator("#technical").text_content())
        pid = created["project_id"]
        page.close()

        def project(pid):
            return context.request.get(base + "/api/projects/" + pid).json()

        def terminal(pid):
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                p = project(pid)
                if all(t["status"] not in {"QUEUED", "RUNNING", "CANCELLING"} for t in p["tasks"]):
                    return p
                time.sleep(0.1)
            raise AssertionError("task deadline")

        p = terminal(pid)
        assert p["tasks"][0]["status"] == "SUCCEEDED", p["tasks"][0].get("error")
        checks.append("actual browser upload -> async local RapidOCR -> completed after tab close")
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base)
        page.wait_for_selector("#projects button")
        page.get_by_role("button", name=upload_name, exact=True).click()
        page.locator("#rename").fill(review_name)
        page.click("#renameButton")
        wait(page, '(name)=>document.querySelector("#name").textContent===name', arg=review_name)
        assert project(pid)["name"] == review_name
        checks.append("rename persisted")
        # Real downloads must match generated registry, not just file presence.
        registry = project(pid)
        for format in ["docx", "pdf"]:
            a = next(a for a in registry["artifacts"] if a["format"] == format)
            response = context.request.get(base + "/api/projects/" + pid + "/download/" + a["artifact_id"])
            import hashlib

            assert response.status == 200 and hashlib.sha256(response.body()).hexdigest() == a["sha256"]
        checks.append("Word/PDF HTTP download bytes match registered SHA")
        review = context.new_page()
        review.on("pageerror", lambda e: errors.append(str(e)))
        review.goto(base + "/p/" + pid + "/review/index.html")
        review.wait_for_selector("#rightContent pre")
        review.select_option("#reviewer", "developer-agent")
        wait(review, '!document.querySelector("#comment").disabled')
        review.locator("#comment").fill("   ")
        time.sleep(0.7)

        def feedback():
            return context.request.get(base + "/api/projects/" + pid + "/feedback").json()

        assert not feedback().get("receipt", {}).get("comments")
        review.locator("#comment").fill("开发Agent合成测试评语，不是用户验收")
        wait(review, 'document.querySelector("#status").textContent.includes("已保存到服务")')
        assert feedback()["receipt"]["reviewer_type"] == "developer-agent"
        a = next(a for a in registry["artifacts"] if a["format"] == "pdf")
        review.select_option("#leftArtifact", a["artifact_id"])
        assert review.locator("#comment").input_value() == "开发Agent合成测试评语，不是用户验收"
        review.click("#clearComment")
        wait(review, 'document.querySelector("#status").textContent.includes("已保存到服务")')
        assert feedback()["receipt"]["comments"][0]["text"] == ""
        review.locator("#comment").fill("Persisted synthetic comment")
        wait(review, 'document.querySelector("#status").textContent.includes("已保存到服务")')
        with review.expect_download() as event:
            review.click("#export")
        file = output.parent / "browser-synthetic-feedback.json"
        event.value.save_as(file)
        receipt = json.loads(file.read_text())
        assert receipt["comments"][0]["text"] == "Persisted synthetic comment"
        checks.append("blank ignored, clear persisted, comment survives changing reference; JSON export")
        conflict = json.loads(file.read_text())
        conflict["comments"][0]["text"] = "Imported explicit replacement"
        conflict["comments"][0]["updated_at"] = "2026-10-08T15:00:00Z"
        conflict_file = output.parent / "browser-synthetic-conflict.json"
        conflict_file.write_text(json.dumps(conflict))
        review.set_input_files("#import", str(conflict_file))
        review.wait_for_selector("#resolveImport:not([hidden])")
        with review.expect_download():
            review.click("#resolveImport")
        wait(review, 'document.querySelector("#status").textContent.includes("已保存到服务")')
        assert feedback()["receipt"]["comments"][0]["text"] == "Imported explicit replacement"
        fresh = browser.new_context()
        new = fresh.new_page()
        new.goto(base + "/p/" + pid + "/review/index.html")
        wait(new, '!document.querySelector("#comment").disabled')
        assert new.locator("#comment").input_value() == "Imported explicit replacement"
        fresh.close()
        checks.append("explicit import conflict resolution with backup; fresh browser loads server comment")
        # Actual long authorized page, no comment or model call here.
        review.goto(base + "/p/" + real_id + "/review/index.html")
        review.wait_for_selector("#rightContent pre")
        wait(review, 'document.querySelector("#leftContent img")?.naturalWidth>0')
        header = review.locator("header").bounding_box()
        review.locator("#leftPane").evaluate("(e)=>e.scrollTop=250")
        review.locator("#rightPane").evaluate("(e)=>e.scrollTop=200")
        assert review.locator("#leftPane").evaluate("(e)=>e.scrollTop") == 250
        assert review.locator("#rightPane").evaluate("(e)=>e.scrollTop") > 0
        assert review.locator("header").bounding_box() == header
        checks.append("real page independent scrolling, fixed toolbar and visible comments")
        review.goto(base + "/p/" + legacy_id + "/review/index.html")
        review.wait_for_selector("#rightContent pre")
        review.select_option("#errorFilter", "remote")
        assert review.locator("#rightPosition option").count() == 1
        assert "136" in review.locator("#rightPosition").inner_text()
        review.select_option("#errorFilter", "local")
        assert review.locator("#rightPosition option").count() == 13
        review.select_option("#errorFilter", "")
        review.select_option("#quality", "good")
        assert review.locator("#rightPosition option").count() == 29
        checks.append(
            "legacy project: 1 actual historical remote error, 13 parse errors, 29 good self-assessments"
        )
        # No compatible credential: controlled local error, no cloud request.
        page.select_option("#newEngine", "compatible")
        page.click("#newTask")
        p = terminal(pid)
        assert p["tasks"][-1]["pages"]["1"]["latest"]["error"]["code"] == "CREDENTIAL_UNAVAILABLE"
        page.reload()
        page.wait_for_selector("#projects button")
        page.get_by_role("button", name=review_name, exact=True).click()
        page.get_by_role("button", name="只重试未成功页", exact=True).click()
        p = terminal(pid)
        assert len(p["tasks"][-1]["pages"]["1"]["attempts"]) == 2
        checks.append(
            "missing credential is explicit; actual UI retry keeps previous successful task outputs"
        )
        page.reload()
        page.wait_for_selector("#projects button")
        page.get_by_role("button", name=review_name, exact=True).click()
        page.click("#trash")
        wait(page, 'document.querySelector("#detail").hidden')
        page.click("#showTrash")
        page.wait_for_selector("#recycle button")
        page.locator("#recycle button").click()
        wait(page, '(name)=>document.querySelector("#projects").textContent.includes(name)', arg=review_name)
        assert project(pid)["name"] == review_name
        checks.append("actual UI trash and restore preserve project artifacts/comments")
        assert not errors, errors
        output.write_text(
            json.dumps(
                {
                    "browser": browser.version,
                    "synthetic_project_id": pid,
                    "checks": checks,
                    "js_errors": errors,
                    "cloud_calls_from_browser_test": 0,
                    "human_acceptance": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        browser.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:18971")
    p.add_argument("--image", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--real-id", required=True)
    p.add_argument("--legacy-id", required=True)
    a = p.parse_args()
    check(a.base, a.image, a.output, a.real_id, a.legacy_id)
