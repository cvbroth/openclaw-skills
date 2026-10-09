"""Explicit synthetic secondary project: dirty navigation, deletion and comments."""

import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout


def main(args):
    args.out.mkdir(parents=True, exist_ok=True)
    base = args.base + "/api/projects/" + args.project
    with sync_playwright() as w:
        browser = w.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        p = context.request.get(base).json()
        aid = list(p["text_revision_heads"].values())[0]
        page.goto(
            args.base
            + "/p/"
            + args.project
            + "/review/index.html?right="
            + aid
            + "&right_location=%7B%22kind%22%3A%22block%22%2C%22id%22%3A%22p23-text%22%7D"
        )
        page.wait_for_selector("#textMode:not([disabled])")
        page.select_option("#reviewer", "developer-agent")
        page.locator("#textMode").click()
        original = page.input_value("#textEditor")
        page.fill("#textEditor", original + "\n放弃的草稿")
        page.fill("#rightPageInput", "3")
        page.locator("#rightPageInput").press("Enter")
        page.get_by_role("button", name="放弃", exact=True).click()
        page.wait_for_selector("#textMode:not([disabled])")
        assert page.input_value("#rightPosition") == "2"
        page.fill("#rightPageInput", "2")
        page.locator("#rightPageInput").press("Enter")
        page.wait_for_selector("#textMode:not([disabled])")
        page.locator("#textMode").click()
        assert page.input_value("#textEditor") == original
        page.fill("#textEditor", original + "\n通过切页提示保存。")
        page.fill("#rightPageInput", "1")
        page.locator("#rightPageInput").press("Enter")
        page.get_by_role("button", name="保存", exact=True).click()
        for _ in range(100):
            if page.input_value("#rightArtifact") != aid and page.input_value("#rightPosition") == "0":
                break
            page.wait_for_timeout(100)
        saved = page.input_value("#rightArtifact")
        assert saved != aid
        page.fill("#rightPageInput", "2")
        page.locator("#rightPageInput").press("Enter")
        page.wait_for_selector("#textMode:not([disabled])")
        page.locator("#textMode").click()
        assert "通过切页提示保存" in page.input_value("#textEditor")
        # Cancel leaving does not lose draft; actual browser reload shows native warning.
        page.fill("#textEditor", original + "\n留下的草稿。")
        page.locator("#back").click()
        page.get_by_role("button", name="取消", exact=True).click()
        assert "留下的草稿" in page.input_value("#textEditor")
        # A format-completion refresh must not replace a newer unsaved editor.
        completed = next(t["task_id"] for t in p["tasks"] if t.get("operation") == "format-artifact")
        page.evaluate("tid=>watchFormat(tid)", completed)
        page.wait_for_timeout(1500)
        assert "留下的草稿" in page.input_value("#textEditor")
        assert page.evaluate("editDirty")
        dialogs = []

        def dismiss_reload(dialog):
            dialogs.append(dialog.type)
            dialog.dismiss()

        page.on("dialog", dismiss_reload)
        try:
            page.reload(timeout=2000)
        except BrowserTimeout:
            assert dialogs == ["beforeunload"]
        assert dialogs == ["beforeunload"]
        assert "留下的草稿" in page.input_value("#textEditor")
        # Save succeeds even when subsequent formatting request fails.
        page.route(
            "**/format",
            lambda r: r.fulfill(
                status=503, content_type="application/json", body='{"error":"SYNTHETIC_FORMAT_FAILURE"}'
            ),
        )
        page.locator("#saveFormat").click()
        for _ in range(100):
            if "排版启动失败" in page.locator("#formatState").inner_text():
                break
            page.wait_for_timeout(100)
        assert "修订已保存" in page.locator("#formatState").inner_text()
        assert page.input_value("#rightArtifact") != saved
        page.unroute("**/format")
        page.screenshot(path=str(args.out / "format-failure-saved.png"))
        # Source comment stays with physical23 independently of derived revision IDs.
        page.select_option("#commentScope", "source_page")
        page.fill("#comment", "R7 开发测试：原图23页评论独立保存。")
        page.locator("#saveServer").click()
        for _ in range(100):
            data = context.request.get(base + "/feedback").json()
            if "原图23页评论" in json.dumps(data, ensure_ascii=False):
                break
            page.wait_for_timeout(100)
        assert "原图23页评论" in json.dumps(data, ensure_ascii=False)
        page.reload()
        page.wait_for_selector("#textMode:not([disabled])")
        assert "原图23页评论" in page.input_value("#comment")
        (args.out / "edges.json").write_text(
            json.dumps(
                {
                    "dirty_discard": True,
                    "dirty_save_before_page_change": True,
                    "leave_cancel": True,
                    "native_reload_guard": True,
                    "format_completion_preserves_new_unsaved_draft": True,
                    "saved_revision_survives_simulated_format_failure": True,
                    "source_comment_reload": True,
                    "ocr_calls": 0,
                },
                indent=2,
            )
        )
        browser.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:18971")
    p.add_argument("--project", required=True)
    p.add_argument("--out", type=Path, required=True)
    main(p.parse_args())
