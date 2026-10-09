"""Real browser checks; only explicit synthetic project comments are modified."""

import argparse
import json
from pathlib import Path
import time
from playwright.sync_api import sync_playwright


def wait(p, expression):
    end = time.monotonic() + 30
    while time.monotonic() < end:
        if p.evaluate(expression):
            return
        time.sleep(0.05)
    raise AssertionError(expression)


def run(a):
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    errors = []
    evidence = {}
    with sync_playwright() as w:
        browser = w.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1600, "height": 1000}, accept_downloads=True)
        p = ctx.new_page()
        p.on("pageerror", lambda x: errors.append(str(x)))

        def project(pid):
            return ctx.request.get(a.base + "/api/projects/" + pid).json()

        def review(pid):
            p.goto(a.base + "/p/" + pid + "/review/index.html")
            wait(p, "document.querySelector('#comment')&&!document.querySelector('#comment').disabled")

        def select(side, aid):
            p.select_option("#" + side + "Artifact", aid)

        def image(side):
            wait(p, f"document.querySelector('#{side}Content img')?.naturalWidth>0")

        real = project(a.real)
        syn = project(a.synthetic)

        def latest(model, fmt):
            return next(x for x in reversed(model["artifacts"]) if x["format"] == fmt)

        p.goto(a.base + "/projects/" + a.real)
        wait(p, "document.querySelector('#formatSource').options.length>0")
        assert p.locator("#artifacts").inner_text().find("Markdown排版稿") >= 0
        p.screenshot(path=str(out / "detail.png"))
        review(a.real)
        select("right", latest(real, "docx")["artifact_id"])
        image("left")
        image("right")
        expanded = p.locator("main").bounding_box()["height"]
        p.screenshot(path=str(out / "expanded.png"))
        p.evaluate(
            "document.querySelector('#leftPane').scrollTop=160;document.querySelector('#rightPane').scrollTop=220"
        )
        before = p.evaluate(
            "['left','right'].map(s=>({top:document.querySelector('#'+s+'Pane').scrollTop,artifact:document.querySelector('#'+s+'Artifact').value,page:document.querySelector('#'+s+'Position').value,zoom:document.querySelector('#'+s+'Zoom').value}))"
        )
        p.click("#toggleToolbar")
        time.sleep(0.15)
        collapsed = p.locator("main").bounding_box()["height"]
        after = p.evaluate(
            "['left','right'].map(s=>({top:document.querySelector('#'+s+'Pane').scrollTop,artifact:document.querySelector('#'+s+'Artifact').value,page:document.querySelector('#'+s+'Position').value,zoom:document.querySelector('#'+s+'Zoom').value}))"
        )
        assert collapsed - expanded > 100, (expanded, collapsed)
        assert before == after, (before, after)
        evidence["toolbar"] = {
            "expanded_height": expanded,
            "collapsed_height": collapsed,
            "gain": collapsed - expanded,
            "state_preserved": True,
        }
        p.screenshot(path=str(out / "collapsed.png"))
        p.click("#focusLeft")
        time.sleep(0.1)
        assert p.locator("#rightPane").is_hidden()
        p.click("#focusLeft")
        time.sleep(0.1)
        assert p.locator("#rightPane").is_visible()
        assert p.locator("#leftPane").evaluate("(n)=>n.scrollTop") == before[0]["top"]
        p.reload()
        wait(p, "document.body.classList.contains('toolbar-collapsed')")
        p.click("#toggleToolbar")
        select("left", latest(real, "docx")["artifact_id"])
        select("right", latest(real, "pdf")["artifact_id"])
        image("left")
        image("right")
        p.evaluate(
            "document.querySelector('#leftPane').scrollTop=100;document.querySelector('#rightPane').scrollTop=0"
        )
        p.locator("#rightPane").hover()
        p.mouse.wheel(0, 250)
        time.sleep(0.2)
        assert p.locator("#leftPane").evaluate("(n)=>n.scrollTop") == 100
        p.screenshot(path=str(out / "word-pdf.png"))
        evidence["independent_scroll"] = True
        review(a.synthetic)
        select("right", latest(syn, "markdown")["artifact_id"])
        wait(p, "document.querySelector('#rightContent .reading b')")
        assert "**加粗**" not in p.locator("#rightContent .reading").inner_text()
        p.select_option("#markdownMode", "source")
        wait(p, "document.querySelector('#rightContent pre')")
        assert "**加粗**" in p.locator("#rightContent pre").inner_text()
        p.select_option("#markdownMode", "reading")
        wait(p, "document.querySelector('#rightContent .reading b')")
        p.select_option("#reviewer", "developer-agent")
        p.fill("#comment", "R3 合成草稿：折叠保持；不是用户确认。")
        p.click("#toggleToolbar")
        assert p.input_value("#comment").startswith("R3 合成草稿")
        p.click("#toggleToolbar")
        p.click("#saveServer")
        time.sleep(0.8)
        p.reload()
        wait(p, "document.querySelector('#comment').value.startsWith('R3 合成草稿')")
        evidence["synthetic_markdown_and_draft"] = True
        with p.expect_download() as d:
            p.click("#export")
        d.value.save_as(str(out / "synthetic-feedback.json"))
        # Mobile navigation and comment draft stay accessible.
        p.click("#focusLeft")
        p.set_viewport_size({"width": 390, "height": 844})
        p.click("#toggleToolbar")
        assert p.locator("#toggleToolbar").is_visible() and p.locator("#back").is_visible()
        assert p.locator("header").evaluate("n=>n.scrollWidth") <= 392
        p.click("#mobile")
        assert p.locator("#rightPane").is_visible() and p.locator("#leftPane").is_hidden()
        assert p.input_value("#comment").startswith("R3 合成草稿")
        p.screenshot(path=str(out / "mobile.png"))
        evidence["mobile"] = True
        p.set_viewport_size({"width": 1600, "height": 1000})
        p.click("#focusLeft")
        p.goto(a.base + "/templates")
        p.wait_for_selector("#parameters input")
        p.screenshot(path=str(out / "templates.png"))
        # Browser import path, field validation, no new production or model task.
        td = ctx.request.get(a.base + "/api/templates/markdown-readable/1.0.0").json()
        td["parameters"]["script"] = "forbidden"
        bad = out / "invalid-template.json"
        bad.write_text(json.dumps(td))
        p.set_input_files("#import", str(bad))
        time.sleep(0.1)
        p.click("#save")
        wait(p, "document.querySelector('#message').textContent.includes('script')")
        evidence["template_browser_import_rejected"] = True

        td.pop("unused", None)
        td["parameters"].pop("script")
        td["id"] = "browser-copy-r3"
        catalog = ctx.request.get(a.base + "/api/templates").json()["catalog"]["templates"]
        td["version"] = "1.0." + str(sum(t["id"] == td["id"] for t in catalog))
        valid = out / "valid-template.json"
        valid.write_text(json.dumps(td))
        p.set_input_files("#import", str(valid))
        time.sleep(0.1)
        p.click("#save")
        wait(p, "document.querySelector('#message').textContent.includes('草稿已保存')")
        with p.expect_download() as download:
            p.click("#export")
        exported = out / "exported-template.json"
        download.value.save_as(str(exported))
        assert json.loads(exported.read_text()) == td
        evidence["template_browser_copy_export"] = True
        # Rename only the synthetic project: IDs, original bytes and preview keys stay intact.
        before = project(a.synthetic)
        renamed = ctx.request.patch(a.base + "/api/projects/" + a.synthetic, data={"name": "合成排版演示 R3"})
        assert renamed.ok
        changed = project(a.synthetic)
        assert [
            (x["artifact_id"], x["sha256"], x.get("preview_render", {}).get("key"))
            for x in before["artifacts"]
        ] == [
            (x["artifact_id"], x["sha256"], x.get("preview_render", {}).get("key"))
            for x in changed["artifacts"]
        ]
        word = latest(changed, "docx")
        response = ctx.request.get(
            a.base + "/api/projects/" + a.synthetic + "/download/" + word["artifact_id"]
        )
        from urllib.parse import unquote

        assert "合成排版演示 R3_" in unquote(response.headers["content-disposition"])
        assert project(a.synthetic)["artifacts"] == changed["artifacts"]
        evidence["rename_hash_cache_and_download"] = True
        # Existing 50-page quality stays bound to source when the target changes.
        review(a.history)
        p.select_option("#quality", "usable_with_defects")
        count = p.locator("#sourcePosition option").count()
        assert count == 7
        ids = p.locator("#rightArtifact option").evaluate_all("(ns)=>ns.map(n=>n.value)")
        for aid in ids[:2]:
            p.select_option("#rightArtifact", aid)
            assert p.locator("#sourcePosition option").count() == count
        evidence["history50_quality_stable"] = True
        # Actual historical document sample previews remain available.
        sample = project(a.sample)
        review(a.sample)
        select("left", latest(sample, "docx")["artifact_id"])
        select("right", latest(sample, "pdf")["artifact_id"])
        image("left")
        image("right")
        assert len(latest(sample, "docx")["pages"]) == 10 and len(latest(sample, "pdf")["pages"]) == 9
        p.screenshot(path=str(out / "document-sample.png"))
        evidence["existing_document_previews"] = True

        if a.offline:
            p.goto(Path(a.offline).resolve().as_uri())
            wait(p, "document.querySelector('#comment')&&!document.querySelector('#comment').disabled")
            assert p.input_value("#comment").startswith("R3 合成草稿")
            for side, fmt in [("left", "docx"), ("right", "pdf")]:
                select(side, latest(syn, fmt)["artifact_id"])
                image(side)
            assert p.input_value("#comment") == ""
            with p.expect_download() as offline_download:
                p.locator("#leftContent a[download]").click()
            assert "合成排版演示 R3_" in offline_download.value.suggested_filename
            offline_download.value.save_as(str(out / "offline-word.docx"))
            p.screenshot(path=str(out / "offline-word-pdf.png"))
            evidence["offline_word_pdf"] = True
        evidence["browser"] = browser.version
        evidence["js_errors"] = errors
        browser.close()
    (out / "browser-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    assert not errors, errors
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:18971")
    ap.add_argument("--real", required=True)
    ap.add_argument("--synthetic", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--offline")
    ap.add_argument("--history", default="656ff0c6-00f0-4a47-9e87-9615ef827461")
    ap.add_argument("--sample", default="4880ebb4-9194-48b5-ab7c-f39c3c58aad1")
    run(ap.parse_args())
