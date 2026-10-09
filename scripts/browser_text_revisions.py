"""Actual desktop R7 operations on explicit synthetic project, no model calls."""

import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main(args):
    args.out.mkdir(parents=True, exist_ok=True)
    base = args.base.rstrip("/")
    results = {}
    with sync_playwright() as w:
        browser = w.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors = []
        calls = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: calls.append(r.url) if r.method == "POST" else None)
        project = context.request.get(base + "/api/projects/" + args.project).json()
        original = args.artifact

        def open_page(aid, target=page):
            target.goto(
                base
                + "/p/"
                + args.project
                + "/review/index.html?right="
                + aid
                + "&right_location=%7B%22kind%22%3A%22block%22%2C%22id%22%3A%22p23-text%22%7D"
            )
            target.wait_for_selector("#textMode:not([disabled])")
            target.select_option("#reviewer", "developer-agent")
            target.wait_for_selector('#leftContent img[alt="原件物理第23页"]')

        def wait_state(text):
            for _ in range(100):
                if text in page.locator(".editbar").inner_text():
                    return
                page.wait_for_timeout(100)
            raise AssertionError(page.locator(".editbar").inner_text())

        open_page(original)
        page.locator("#textMode").click()
        page.wait_for_selector("#textEditor")
        before = page.input_value("#textEditor")
        assert "错宇" in before
        corrected = before.replace("错宇", "错字")
        page.fill("#textEditor", corrected)
        page.screenshot(path=str(args.out / "01-edit-unsaved.png"))
        # Left navigation is independent and never discards the edited right page.
        page.evaluate('()=>jump("left",24)')
        page.wait_for_selector('#leftContent img[alt="原件物理第24页"]')
        assert page.input_value("#textEditor") == corrected
        page.fill("#rightPageInput", "3")
        page.locator("#rightPageInput").press("Enter")
        page.get_by_role("button", name="取消", exact=True).click()
        assert page.input_value("#textEditor") == corrected
        assert page.input_value("#rightPosition") == "1"
        results["dirty_cancel_and_left_independence"] = True
        # A transport failure is explicit and preserves the actual textarea draft.
        page.route(
            "**/text-revisions",
            lambda route: route.fulfill(
                status=500, content_type="application/json", body='{"error":"SYNTHETIC_SAVE_FAILURE"}'
            ),
        )
        page.locator("#saveRevision").click()
        wait_state("保存失败")
        assert page.input_value("#textEditor") == corrected
        page.screenshot(path=str(args.out / "02-save-failure-draft.png"))
        page.unroute("**/text-revisions")
        page.locator("#saveFormat").click()
        wait_state("排版成功")
        revised = page.input_value("#rightArtifact")
        assert revised != original
        assert page.input_value("#leftPageInput") == "24"
        assert page.input_value("#rightPosition") == "1"
        page.wait_for_selector("#rightContent .reading")
        assert "错字" in page.locator("#rightContent").inner_text()
        page.screenshot(path=str(args.out / "03-saved-reading.png"))
        # Diff is generated from immutable versions, not model output.
        page.locator("#textHistory").click()
        page.select_option("#revisionHistory", original)
        page.wait_for_timeout(300)
        assert "错宇" in page.locator("#revisionDiff").inner_text()
        assert "错字" in page.locator("#revisionDiff").inner_text()
        page.screenshot(path=str(args.out / "04-version-diff.png"))
        page.get_by_role("button", name="关闭", exact=True).click()
        page.reload()
        page.wait_for_selector("#textMode:not([disabled])")
        page.wait_for_selector("#rightContent .reading")
        assert "错字" in page.locator("#rightContent").inner_text()
        results["save_reload_mapping_and_diff"] = True
        # Two real browser tabs use the same base; the second cannot overwrite.
        tab = context.new_page()
        open_page(revised, tab)
        page.locator("#textMode").click()
        page.fill("#textEditor", corrected + "\n\n连续保存测试。")
        tab.locator("#textMode").click()
        tab.fill("#textEditor", corrected + "\n\n另一标签草稿。")
        page.locator("#saveRevision").click()
        wait_state("已保存")
        for _ in range(100):
            if page.input_value("#rightArtifact") != revised:
                break
            page.wait_for_timeout(100)
        current = page.input_value("#rightArtifact")
        tab.locator("#saveRevision").click()
        for _ in range(100):
            if "冲突" in tab.locator("#textState").inner_text():
                break
            tab.wait_for_timeout(100)
        assert "冲突" in tab.locator("#textState").inner_text()
        assert "另一标签草稿" in tab.input_value("#textEditor")
        tab.screenshot(path=str(args.out / "05-tab-conflict.png"))
        results["two_tab_conflict"] = True
        tab.on("dialog", lambda d: d.accept())
        tab.close()
        # Restore old content creates another version; original never changes.
        page.locator("#textHistory").click()
        page.select_option("#revisionHistory", revised)
        page.locator("#restoreRevision").click()
        wait_state("恢复为新版本")
        restored = page.input_value("#rightArtifact")
        assert restored not in [original, revised, current]
        results["restore_creates_new_version"] = True
        # Wait for actual DOCX/PDF previews produced from the first corrected revision.
        for _ in range(120):
            project = context.request.get(base + "/api/projects/" + args.project).json()
            docs = [
                a
                for a in project["artifacts"]
                if a["format"] in ["docx", "pdf"] and revised in a.get("parents", [])
            ]
            if len(docs) == 2 and all(a.get("preview_render", {}).get("status") == "SUCCEEDED" for a in docs):
                break
            page.wait_for_timeout(500)
        assert len(docs) == 2 and all(a["preview_render"]["status"] == "SUCCEEDED" for a in docs)
        word = next(a for a in docs if a["format"] == "docx")
        pdf = next(a for a in docs if a["format"] == "pdf")
        page.goto(
            base
            + "/p/"
            + args.project
            + "/review/index.html?left="
            + word["artifact_id"]
            + "&right="
            + pdf["artifact_id"]
        )
        page.wait_for_selector("#leftContent img")
        page.wait_for_selector("#rightContent img")
        for _ in range(100):
            if page.evaluate("[...document.querySelectorAll('main img')].every(i=>i.naturalWidth>0)"):
                break
            page.wait_for_timeout(100)
        page.screenshot(path=str(args.out / "06-real-word-pdf.png"))
        assert not errors, errors
        assert not any("/tasks" in url for url in calls), calls
        results.update(
            browser=browser.version,
            real_word_pdf_previews=True,
            original_artifact_id=original,
            corrected_artifact_id=revised,
            restored_artifact_id=restored,
            word_artifact_id=word["artifact_id"],
            pdf_artifact_id=pdf["artifact_id"],
            post_urls=calls,
            page_errors=errors,
            recognition_requests=0,
        )
        (args.out / "browser.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:18971")
    p.add_argument("--project", required=True)
    p.add_argument("--artifact", required=True)
    p.add_argument("--out", type=Path, required=True)
    main(p.parse_args())
