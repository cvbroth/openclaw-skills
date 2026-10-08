"""Real Chromium offline UI mechanics; synthetic comments, NOT user acceptance."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
from playwright.sync_api import sync_playwright


def check(root, output):
    errors = []
    remote = []
    requests = []
    checks = []
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        page.on(
            "request",
            lambda request: remote.append(request.url)
            if request.url.startswith(("https:", "http:"))
            else None,
        )

        def open_project(folder):
            page.goto((folder / "review/index.html").resolve().as_uri())
            page.wait_for_function(
                'window.PROJECT && document.querySelector("#leftContent img").naturalWidth>0'
            )

        m3 = root / "m3-50"
        doc = root / "document-sample"
        open_project(m3)
        page.wait_for_selector("#rightContent pre")
        assert len([u for u in requests if "/sources/previews/" in u]) == 1
        assert page.locator("#leftContent img").count() == 1
        checks.append("initial load: exactly one source preview requested, no all-page decoding")
        # Genuine long transcription scroll independently of original.
        header = page.locator("header").bounding_box()
        page.locator("#leftPane").evaluate("(e)=>e.scrollTop=350")
        page.locator("#rightPane").evaluate("(e)=>e.scrollTop=220")
        assert page.locator("#leftPane").evaluate("(e)=>e.scrollTop") == 350
        assert page.locator("#rightPane").evaluate("(e)=>e.scrollTop") > 0
        assert page.locator("header").bounding_box() == header
        assert page.locator("#comment").bounding_box()["y"] < 1000
        assert page.evaluate("document.documentElement.scrollHeight<=innerHeight")
        checks.append("independent pane scroll, fixed toolbar, visible comment footer")
        page.locator("#comment").fill("SYNTHETIC TEST p7")
        page.select_option("#rightPosition", "1")
        page.wait_for_selector("#rightContent pre")
        assert page.locator("#comment").input_value() == ""
        page.select_option("#rightPosition", "0")
        assert page.locator("#comment").input_value() == "SYNTHETIC TEST p7"
        assert page.locator("#leftPane").evaluate("(e)=>e.scrollTop") == 350
        # Exactly original text across all 50 records; HTML remains literal inert text.
        structure = json.loads((m3 / "content/structure.json").read_text())
        for i, row in enumerate(structure["pages"]):
            page.select_option("#rightPosition", str(i))
            page.wait_for_function(
                '(text)=>document.querySelector("#rightContent pre")?.textContent===text',
                arg=row["text"] or "没有正文输出。",
            )
        checks.append("50 page texts match historical output; per-page lazy scripts")
        page.select_option("#quality", "good")
        assert page.locator("#rightPosition option").count() == 29
        page.select_option("#quality", "unknown")
        assert page.locator("#rightPosition option").count() == 14
        page.select_option("#quality", "")
        page.select_option("#errorFilter", "yes")
        assert page.locator("#rightPosition option").count() == 14
        page.select_option("#errorFilter", "")
        page.select_option("#commentFilter", "yes")
        assert page.locator("#rightPosition option").count() == 1
        page.select_option("#commentFilter", "")
        checks.append("quality/comments/errors filters combine; unprovided quality is distinct")
        page.select_option("#rightPosition", "0")
        page.select_option("#leftPosition", "0")
        with page.expect_download() as event:
            page.click("#export")
        download = event.value
        with tempfile.TemporaryDirectory() as temp:
            receipt = Path(temp) / "feedback.json"
            download.save_as(receipt)
            data = json.loads(receipt.read_text())
            assert data["comments"][0]["text"] == "SYNTHETIC TEST p7"
            open_project(doc)
            page.set_input_files("#import", str(receipt))
            page.wait_for_function('document.querySelector("#status").textContent.includes("拒绝导入")')
        checks.append("export receipt and cross-project import rejected")
        project = json.loads((doc / "project.json").read_text())
        formats = {a["format"]: a for a in project["artifacts"]}
        page.select_option("#rightArtifact", formats["docx"]["artifact_id"])
        page.wait_for_function('document.querySelector("#rightContent img")?.naturalWidth>0')
        assert "不是浏览器原生Word" in page.locator("#rightNotice").inner_text()
        assert page.locator("#rightPosition option").count() == 10
        page.locator("#comment").fill("SYNTHETIC Word comment")
        page.select_option("#rightArtifact", formats["pdf"]["artifact_id"])
        assert page.locator("#comment").input_value() == ""
        assert page.locator("#rightPosition option").count() == 9
        page.select_option("#leftPosition", "4")
        page.select_option("#rightPosition", "8")
        assert (
            page.locator("#leftPosition").input_value() == "4"
            and page.locator("#rightPosition").input_value() == "8"
        )
        page.locator("#comment").fill("SYNTHETIC PDF end comment")
        page.select_option("#rightArtifact", formats["docx"]["artifact_id"])
        # Reference also forms part of a comparison, so restore it before matching draft.
        page.select_option("#leftPosition", "0")
        assert page.locator("#comment").input_value() == "SYNTHETIC Word comment"
        checks.append("real Word/PDF artifact isolation; 10 vs 9 output pages, independent source positions")
        page.select_option("#rightArtifact", formats["json"]["artifact_id"])
        assert "没有可用预览" in page.locator("#rightNotice").inner_text()
        assert "外部原件仅引用" in page.locator("#leftNotice").inner_text()
        checks.append("missing preview and external reference explicitly explained")
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#comment").fill("SYNTHETIC mobile draft")
        page.click("#mobile")
        assert page.locator("#rightPane").is_visible() and not page.locator("#leftPane").is_visible()
        page.click("#mobile")
        assert page.locator("#comment").input_value() == "SYNTHETIC mobile draft"
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        checks.append("narrow-screen pane toggle preserves draft")
        # Copy a tiny real project to prove links survive relocation, without modifying delivery.
        with tempfile.TemporaryDirectory() as temp:
            moved = Path(temp) / "moved"
            shutil.copytree(doc, moved)
            page.set_viewport_size({"width": 1440, "height": 1000})
            open_project(moved)
            assert page.locator("#leftContent img").evaluate("(e)=>e.naturalWidth") > 0
            page.select_option("#rightArtifact", formats["pdf"]["artifact_id"])
            page.wait_for_function('document.querySelector("#rightContent img")?.naturalWidth>0')
            checks.append("relocated directory loads source and PDF preview by relative links")
            # Missing previews are simulated only in this disposable test copy.
            mutated = json.loads((moved / "project.json").read_text())
            for art in mutated["artifacts"]:
                if art["format"] in {"docx", "pdf"}:
                    art["pages"] = []
                    art["preview"] = None
            (moved / "review/project.js").write_text("window.PROJECT=" + json.dumps(mutated) + ";")
            page.reload()
            page.select_option("#rightArtifact", formats["docx"]["artifact_id"])
            assert "没有可用预览" in page.locator("#rightNotice").inner_text()
            assert page.locator("#rightPosition option").inner_text() == "整份文档"
            page.select_option("#rightArtifact", formats["pdf"]["artifact_id"])
            assert page.locator("#rightContent object").count() == 1
            assert page.locator("#rightContent a").first.get_attribute("href").endswith("sample.pdf")
            checks.append("synthetic missing Word preview: document comment; PDF object plus file fallback")
        browser_version = browser.version
        browser.close()
    assert not errors and not remote, (errors, remote)
    output.write_text(
        json.dumps(
            {
                "browser": browser_version,
                "checks": checks,
                "js_errors": errors,
                "external_requests": remote,
                "scope": "real browser mechanics with synthetic comments; not human validation of content or Word fonts",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    check(a.root, a.output)
