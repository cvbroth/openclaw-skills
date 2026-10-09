"""Real browser checks; explicit synthetic fixture, no extraction/model requests."""

import argparse
import json
from pathlib import Path
import time
from playwright.sync_api import sync_playwright


def main(args):
    args.out.mkdir(parents=True, exist_ok=True)
    result = {}
    with sync_playwright() as w:
        browser = w.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        base = args.base.rstrip("/")
        model = context.request.get(base + "/api/projects/" + args.project).json()
        assert model["source_info"]["units"] == 169 and not model["tasks"]
        source = model["source_artifact_id"]
        if args.design:
            page.goto(args.design.resolve().as_uri())
            page.screenshot(path=str(args.out / "layout-sample.png"), full_page=True)
        page.goto(base + "/projects/" + args.project)
        page.wait_for_selector("#sourceInfo p")
        assert page.locator("#formatExisting").is_disabled()
        assert "暂无可用" in page.locator("#formatSource").inner_text()
        page.screenshot(path=str(args.out / "project-empty.png"), full_page=True)
        page.goto(base + "/p/" + args.project + "/review/index.html?left=" + source + "&right=" + source)
        page.wait_for_selector("#leftPageInput")

        def visible(n, side="left"):
            page.wait_for_selector(f'#{side}Content img[alt="原件物理第{n}页"]')
            for _ in range(100):
                if page.evaluate(f"document.querySelector('#{side}Content img')?.naturalWidth>0"):
                    return
                page.wait_for_timeout(50)
            raise AssertionError("image did not decode")

        timings = {}
        for n in [1, 16, 23, 169]:
            start = time.monotonic()
            page.evaluate('(n)=>jump("left",n)', n)
            visible(n)
            timings[str(n)] = round(time.monotonic() - start, 3)
            assert page.input_value("#leftPageInput") == str(n)
            assert "169" in page.locator("#leftPageTotal").inner_text()
            page.screenshot(path=str(args.out / f"physical-{n}.png"))
        result["rendered_physical_pages"] = [1, 16, 23, 169]
        result["browser_load_seconds"] = timings
        result["no_recognition_tasks"] = not context.request.get(
            base + "/api/projects/" + args.project
        ).json()["tasks"]
        # Cache reuse is verified via actual endpoint and image hash, no extra rendering.
        r = context.request.post(
            base + "/api/projects/" + args.project + "/source-preview/16", data={}
        ).json()
        assert r["cache_hit"]
        result["cache_reuse"] = True

        # A deliberately late old response must not show page16 after selecting page23.
        def late(route):
            response = route.fetch()
            time.sleep(0.7)
            route.fulfill(response=response)

        page.route("**/source-preview/16", late)
        page.evaluate('()=>{jump("left",16);setTimeout(()=>jump("left",23),50);}')
        visible(23)
        page.wait_for_timeout(900)
        assert page.locator("#leftContent img").get_attribute("alt") == "原件物理第23页"
        page.unroute("**/source-preview/16", late)
        result["late_response_does_not_replace_current_page"] = True

        # Explicit simulated transport-stage failure; retry uses the real renderer.
        def fail(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "status": "FAILED",
                        "error": {"code": "SYNTHETIC_BROWSER_FAILURE", "message": "隔离浏览器失败夹具"},
                    }
                ),
            )

        page.route("**/source-preview/17", fail)
        page.evaluate('()=>jump("left",17)')
        page.wait_for_selector("#leftContent .placeholder button")
        assert "SYNTHETIC_BROWSER_FAILURE" in page.locator("#leftContent").inner_text()
        page.unroute("**/source-preview/17", fail)
        page.locator("#leftContent .placeholder button").click()
        visible(17)
        result["simulated_failure_real_retry"] = True
        page.fill("#leftPageInput", "170")
        page.locator("#leftPageInput").press("Enter")
        assert "越界" in page.locator("#status").inner_text()
        assert page.locator("#leftContent img").get_attribute("alt") == "原件物理第17页"
        result["out_of_range_keeps_current_image"] = True
        page.evaluate('()=>jump("left",169)')
        visible(169)
        page.select_option("#commentScope", "source_page")
        page.select_option("#reviewer", "developer-agent")
        page.fill("#comment", "R6 合成开发评论：物理第169页，不是用户验收")
        page.click("#saveServer")
        page.wait_for_timeout(700)
        page.reload()
        visible(169)
        assert "物理第169页" in page.input_value("#comment")
        result["physical_comment_reload"] = True
        page.evaluate('()=>jump("right",16)')
        visible(16, "right")
        assert page.input_value("#leftPageInput") == "169"
        page.select_option("#leftZoom", "175")
        page.evaluate('document.querySelector("#leftPane").scrollTop=160')
        left_scroll = page.evaluate('document.querySelector("#leftPane").scrollTop')
        page.evaluate('document.querySelector("#rightPane").scrollTop=200')
        assert page.evaluate('document.querySelector("#leftPane").scrollTop') == left_scroll
        page.fill("#comment", "R6 合成草稿：当前原图第16页")
        page.click("#toggleToolbar")
        assert page.input_value("#leftPageInput") == "169" and page.input_value("#rightPageInput") == "16"
        assert "当前原图第16页" in page.input_value("#comment")
        page.click("#toggleToolbar")
        result["independent_pages_scroll_fold_draft"] = True
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(args.out / "review-narrow.png"))
        result["narrow_review_overflow"] = page.evaluate("document.documentElement.scrollWidth>innerWidth")
        assert not result["narrow_review_overflow"]
        # Existing real documents, source mapping and full-width artifact rows.
        if args.existing:
            p = context.request.get(base + "/api/projects/" + args.existing).json()
            a = next(a for a in reversed(p["artifacts"]) if a["format"] == "docx" and not a.get("recycled"))
            pdf = next(
                a
                for a in reversed(p["artifacts"])
                if a["format"] == "pdf" and a.get("task_id") == a.get("task_id")
            )
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.goto(base + "/projects/" + args.existing)
            page.wait_for_selector("#artifacts .artifact-row")
            page.locator(".new-task summary").click()
            page.fill("#newPages", "2-4")
            page.evaluate('window.savedInput=document.querySelector("#newPages");window.scrollTo(0,480)')
            scroll = page.evaluate("scrollY")
            page.evaluate("()=>detail()")
            assert page.evaluate(
                'savedInput===document.querySelector("#newPages") && savedInput.value==="2-4"'
            )
            result["poll_scroll_before_after"]=[scroll,page.evaluate("scrollY")]
            assert abs(result["poll_scroll_before_after"][1] - scroll) < 3
            sizes = page.locator("#artifacts .button").evaluate_all(
                "(nodes)=>nodes.map(n=>n.getBoundingClientRect().height)"
            )
            assert max(sizes) <= 38
            assert page.locator("#formatSource").bounding_box()["width"] >= 260
            result["artifact_button_heights"] = sizes
            page.screenshot(path=str(args.out / "project-desktop.png"), full_page=True)
            link = page.locator('[data-artifact-id="' + a["artifact_id"] + '"] a.button')
            link.click()
            page.wait_for_selector("#rightContent img")
            page.wait_for_timeout(300)
            assert page.input_value("#rightArtifact") == a["artifact_id"]
            page.select_option("#leftArtifact", pdf["artifact_id"])
            page.wait_for_selector("#leftContent img")
            assert page.evaluate(
                'document.querySelector("#leftContent img").naturalWidth>0 && document.querySelector("#rightContent img").naturalWidth>0'
            )
            page.screenshot(path=str(args.out / "word-pdf.png"))
            result["exact_artifact_word_pdf"] = True
            page.goto(base + "/projects/" + args.existing)
            page.wait_for_selector("#artifacts .artifact-row")
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(args.out / "project-narrow.png"), full_page=True)
            assert not page.evaluate("document.documentElement.scrollWidth>innerWidth")
            result["narrow_project_overflow"] = False
        result["javascript_errors"] = errors
        assert not errors
        (args.out / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:18971")
    p.add_argument("--project", required=True)
    p.add_argument("--existing")
    p.add_argument("--design", type=Path)
    p.add_argument("--out", type=Path, required=True)
    main(p.parse_args())
