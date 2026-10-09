"""Real Chromium checks on explicit synthetic projects; never starts OCR/cloud.

Only a representative two-page PDF text extraction is created. Other results
are reused. Large project must be the explicitly simulated scheduler fixture.
"""

import argparse
import json
from pathlib import Path
import time
from playwright.sync_api import sync_playwright


def main(args):
    args.out.mkdir(parents=True, exist_ok=True)
    evidence = {}
    with sync_playwright() as w:
        browser = w.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1600, "height": 1050}, accept_downloads=True)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        base = args.base.rstrip("/")

        def get(pid):
            return context.request.get(base + "/api/projects/" + pid).json()

        def post(path, data):
            r = context.request.post(base + path, data=data)
            assert r.ok, r.text()
            return r.json()

        def terminal(pid, tid):
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                p = get(pid)
                t = next(t for t in p["tasks"] if t["task_id"] == tid)
                if t["status"] not in ["QUEUED", "RUNNING", "CANCELLING"] and not any(
                    a.get("preview_render", {}).get("status") in ["QUEUED", "RUNNING"] for a in p["artifacts"]
                ):
                    return p, t
                time.sleep(0.2)
            raise AssertionError("small test did not terminate")

        page.goto(base + "/projects/" + args.project)
        page.wait_for_selector("#sourceInfo p")
        page.locator(".new-task summary").click()
        for selection, count in [("1，3, 3", 2), ("1 - 3", 3), ("全部", 5)]:
            page.fill("#newPages", selection)
            assert f"实际选择 {count} 页" in page.locator("#selectionCount").inner_text()
        page.fill("#newPages", "3-1")
        assert "倒序" in page.locator("#selectionCount").inner_text()
        page.fill("#newPages", "1,3")
        page.select_option("#newEngine", "pdf-text")
        before = get(args.project)
        before_tasks = {t["task_id"] for t in before["tasks"]}
        page.click("#newTask")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            p = get(args.project)
            new = [t for t in p["tasks"] if t["task_id"] not in before_tasks]
            if new:
                break
            time.sleep(0.1)
        assert new
        tid = new[0]["task_id"]
        page.fill("#newPages", "2-4")
        page.evaluate(
            "window.retainedInput=document.querySelector('#newPages');window.retainedForm=document.querySelector('.new-task')"
        )
        page.evaluate("()=>detail()")
        assert page.input_value("#newPages") == "2-4"
        assert page.evaluate(
            "retainedInput===document.querySelector('#newPages') && retainedForm===document.querySelector('.new-task') && retainedForm.open"
        )
        p, t = terminal(args.project, tid)
        assert t["status"] == "SUCCEEDED"
        page.evaluate("()=>detail()")
        page.screenshot(path=str(args.out / "project.png"))
        assert not page.locator("#taskHistory").evaluate("(e)=>e.open")
        assert "MiB" in page.locator("#sourceInfo").inner_text()
        evidence.update(
            real_direct_text_pages=[1, 3],
            task_id=tid,
            form_identity_and_input_preserved=True,
            history_default_collapsed=True,
        )
        docx = next(a for a in p["artifacts"] if a.get("task_id") == tid and a["format"] == "docx")
        pdf = next(a for a in p["artifacts"] if a.get("task_id") == tid and a["format"] == "pdf")
        aid = docx["artifact_id"]
        route = f"/api/projects/{args.project}/artifacts/{aid}"
        row = page.locator(f'.artifact-row[data-artifact-id="{aid}"]')
        page.once("dialog", lambda d: d.accept("我的Word排版稿"))
        row.get_by_role("button", name="改名", exact=True).click()
        page.wait_for_timeout(300)
        updated = get(args.project)
        renamed = next(a for a in updated["artifacts"] if a["artifact_id"] == aid)
        assert renamed["sha256"] == docx["sha256"] and renamed["path"] == docx["path"]
        assert "我的Word排版稿" in renamed["download_name"]
        page.locator(f'.artifact-row[data-artifact-id="{aid}"]').get_by_role(
            "link", name="查看 / 对照"
        ).click()
        page.wait_for_selector("#rightArtifact")
        assert page.input_value("#rightArtifact") == aid
        assert page.input_value("#leftArtifact") == p["source_artifact_id"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if page.evaluate("document.querySelector('#rightContent img')?.naturalWidth>0"):
                break
            time.sleep(0.1)
        assert page.evaluate("document.querySelector('#rightContent img')?.naturalWidth>0")
        page.select_option("#leftArtifact", pdf["artifact_id"])
        page.select_option("#reviewer", "developer-agent")
        page.fill("#comment", "合成开发评论：产物版本隔离检查")
        page.click("#saveServer")
        page.wait_for_timeout(800)
        page.reload()
        page.wait_for_selector("#rightArtifact")
        page.wait_for_timeout(600)
        assert page.input_value("#rightArtifact") == aid
        assert page.input_value("#leftArtifact") == pdf["artifact_id"]
        assert "合成开发评论" in page.input_value("#comment")
        assert page.evaluate(
            "document.querySelector('#leftContent img')?.naturalWidth>0 && document.querySelector('#rightContent img')?.naturalWidth>0"
        )
        page.screenshot(path=str(args.out / "word-pdf.png"))
        with page.expect_download() as download:
            page.click("#export")
        downloaded = download.value
        downloaded.save_as(args.out / "synthetic-feedback.json")
        page.set_input_files("#import", str(args.out / "synthetic-feedback.json"))
        page.wait_for_timeout(200)
        evidence.update(
            exact_artifact_deep_link=True,
            refresh_two_artifacts=True,
            actual_word_pdf_preview=True,
            comment_reload_import_export=True,
        )
        r = context.request.patch(base + route, data={"recycled": True})
        assert r.ok, r.text()
        page.goto(base + f"/p/{args.project}/review/index.html?right=" + aid)
        page.wait_for_selector("[role=alert]")
        assert "已回收" in page.locator("[role=alert]").inner_text()
        assert not page.locator(f'#rightArtifact option[value="{aid}"]').count()
        r = context.request.patch(base + route, data={"recycled": False})
        assert r.ok
        page.goto(base + f"/p/{args.project}/review/index.html?right=" + aid)
        page.wait_for_selector("#rightArtifact")
        page.wait_for_timeout(500)
        assert page.input_value("#rightArtifact") == aid
        assert "合成开发评论" in page.input_value("#comment")
        restored = next(a for a in get(args.project)["artifacts"] if a["artifact_id"] == aid)
        assert restored["sha256"] == docx["sha256"] and restored["parents"] == docx["parents"]
        archive = f"/api/projects/{args.project}/tasks/{tid}/archive"
        post(archive, {"archived": True})
        page.goto(base + "/projects/" + args.project)
        page.wait_for_selector("#taskArchived")
        assert not page.locator("#taskArchived").evaluate("(e)=>e.open")
        post(archive, {"archived": False})
        evidence.update(
            recycle_hidden_and_invalid_link_reported=True,
            restore_comments_and_dependencies=True,
            archive_independent=True,
        )
        if args.large_project:
            started = time.monotonic()
            page.goto(base + "/projects/" + args.large_project)
            page.wait_for_selector("#taskHistory")
            page.wait_for_timeout(200)
            evidence["large_detail_seconds"] = time.monotonic() - started
            assert page.locator(".page-rows tr").count() == 0
            page.locator("#taskHistory > summary").click()
            page.locator(".page-detail summary").first.click()
            assert page.locator(".page-rows tr").count() <= 51
            evidence["large_page_detail_rows"] = page.locator(".page-rows tr").count()
            page.locator(".new-task summary").click()
            page.fill("#newPages", "5-150")
            assert "实际选择 146 页" in page.locator("#selectionCount").inner_text()
            page.fill("#newPages", "全部")
            assert "实际选择 1000 页" in page.locator("#selectionCount").inner_text()
            evidence["large_task_cards_initial"] = page.locator(".task").count()
            page.locator("#taskHistory .more-tasks").click()
            assert page.locator(".task").count() > evidence["large_task_cards_initial"]
            page.screenshot(path=str(args.out / "simulated-1000.png"))
            evidence["large_details_loaded_on_demand"] = True
        evidence["javascript_errors"] = errors
        assert not errors
        (args.out / "browser.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:18971")
    parser.add_argument("--project", required=True)
    parser.add_argument("--large-project")
    parser.add_argument("--out", type=Path, required=True)
    main(parser.parse_args())
