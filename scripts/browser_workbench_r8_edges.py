"""Source quality, independent scroll, real document preview and offline R8 checks."""

import argparse
import json
from pathlib import Path
import zipfile
from playwright.sync_api import sync_playwright


def main(args):
    args.out.mkdir(parents=True, exist_ok=True)
    receipt = json.loads(args.receipt.read_text())
    pid = receipt["project_id"]
    outputs = receipt["outputs"]
    word = next(a["artifact_id"] for a in outputs if a["format"] == "docx")
    pdf = next(a["artifact_id"] for a in outputs if a["format"] == "pdf")
    result = {"synthetic": True}
    with sync_playwright() as w:
        b = w.chromium.launch(args=["--no-sandbox"])
        c = b.new_context(viewport={"width": 1440, "height": 900})
        p = c.new_page()
        errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        base = args.base + "/p/" + pid + "/review/index.html"
        p.goto(base + "?right=" + args.artifact)
        p.wait_for_selector("#textMode:not([disabled])")
        p.click("#toggleToolbar")
        p.select_option("#quality", "poor")
        assert p.locator("#sourcePosition option").count() == 1
        assert p.input_value("#sourcePosition") == "22"
        p.locator("#qualityDetails").evaluate(
            '(n)=>{n.open=true;document.querySelector("#qualityEvidence").textContent="合成长评价，用于验证面板内部滚动。".repeat(180)}'
        )
        assert p.locator("#qualityDetails").evaluate(
            "(n)=>n.scrollHeight>n.clientHeight && n.clientHeight<=180"
        )
        assert (
            p.locator("#qualityDetails").bounding_box()["y"]
            + p.locator("#qualityDetails").bounding_box()["height"]
            <= p.locator("main").bounding_box()["y"] + 1
        )
        p.screenshot(path=str(args.out / "quality-panel-bounded.png"))
        p.locator("#closeQuality").click()
        result["synthetic_long_quality_panel"] = True
        p.click("#locateSelectedSource")
        assert p.input_value("#rightPosition") == "17"
        p.select_option("#rightArtifact", word)
        assert p.locator("#sourcePosition option").count() == 1
        p.click("#locateSelectedSource")
        assert p.input_value("#rightPosition") == "0"
        assert "输出页" in p.locator("#rightPageTotal").inner_text()
        p.select_option("#rightArtifact", args.artifact)
        p.select_option("#commentFilter", "yes")
        p.fill("#sourcePageLookup", "23")
        p.click("#findSourcePage")
        assert "筛选排除" in p.locator("#mapMessage").inner_text()
        p.select_option("#commentFilter", "")
        p.select_option("#quality", "")
        p.select_option("#leftArtifact", word)
        p.select_option("#rightArtifact", pdf)
        p.wait_for_selector("#leftContent img")
        p.wait_for_selector("#rightContent img")
        for _ in range(50):
            if p.evaluate('[...document.querySelectorAll("main img")].every(i=>i.naturalWidth>0)'):
                break
            p.wait_for_timeout(100)
        p.click("#toggleToolbar")
        p.select_option("#leftZoom", "175")
        p.select_option("#rightZoom", "175")
        p.locator("#leftPane").evaluate("(n)=>n.scrollTop=190")
        left = p.locator("#leftPane").evaluate("(n)=>n.scrollTop")
        p.locator("#rightPane").evaluate("(n)=>n.scrollTop=250")
        assert p.locator("#leftPane").evaluate("(n)=>n.scrollTop") == left
        right = p.locator("#rightPane").evaluate("(n)=>n.scrollTop")
        p.click("#toggleToolbar")
        p.click("#toggleToolbar")
        assert p.locator("#leftPane").evaluate("(n)=>n.scrollTop") == left
        assert p.locator("#rightPane").evaluate("(n)=>n.scrollTop") == right
        p.screenshot(path=str(args.out / "word-pdf-independent.png"))
        result["quality_source_only"] = True
        result["filtered_mapping_explicit"] = True
        result["scroll_preserved"] = {"left": left, "right": right}
        # Real export, relocated file://, no active server for internal resource links.
        package = args.out / "project.zip"
        r = c.request.get(args.base + "/api/projects/" + pid + "/export")
        assert r.ok
        package.write_bytes(r.body())
        root = args.out / "relocated" / "Windows下载 R8项目"
        root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(package) as z:
            assert z.testzip() is None
            assert all(
                not any(x in n for x in ["\\", ":", "<", ">", '"', "|", "?", "*"])
                and ".." not in Path(n).parts
                for n in z.namelist()
            )
            assert not any("lo-profile" in n or "/tmp/" in n or n.endswith(".lock") for n in z.namelist())
            z.extractall(root)
        p.goto((root / "review/index.html").resolve().as_uri() + "?left=" + word + "&right=" + pdf)
        p.wait_for_selector("#leftContent img")
        p.wait_for_selector("#rightContent img")
        for _ in range(50):
            if p.evaluate('[...document.querySelectorAll("main img")].every(i=>i.naturalWidth>0)'):
                break
            p.wait_for_timeout(100)
        assert p.evaluate('[...document.querySelectorAll("main img")].every(i=>i.naturalWidth>0)')
        p.screenshot(path=str(args.out / "offline-word-pdf.png"))
        assert p.locator("#leftPageInput").is_visible() and p.locator("#rightPageInput").is_visible()
        assert not errors, errors
        result["offline_previews"] = True
        result["page_errors"] = errors
        (args.out / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        b.close()


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--base", default="http://127.0.0.1:18971")
    a.add_argument("--artifact", required=True)
    a.add_argument("--receipt", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    main(a.parse_args())
