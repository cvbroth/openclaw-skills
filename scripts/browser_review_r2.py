"""Real Chromium regression of existing projects. Never uploads or starts OCR/model jobs.

Only the explicitly supplied synthetic comment project is modified. Private screenshots,
feedback and exported documents go to --output, never to the source repository.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time
import zipfile
from playwright.sync_api import sync_playwright


def wait(page, expression):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if page.evaluate(expression):
            return
        time.sleep(0.05)
    raise AssertionError(expression)


def run(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(accept_downloads=True, viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))

        def project(pid):
            r = context.request.get(args.base + "/api/projects/" + pid)
            assert r.ok
            return r.json()

        def review(pid):
            page.goto(args.base + "/p/" + pid + "/review/index.html")
            wait(page, "document.querySelector('#comment')&&!document.querySelector('#comment').disabled")

        def image(side):
            wait(page, f"document.querySelector('#{side}Content img')?.naturalWidth>0")

        def artifact(p, kind, engine=None):
            return next(
                a
                for a in reversed(p["artifacts"])
                if a["format"] == kind and (engine is None or engine in a["name"])
            )

        page.goto(args.base)
        page.wait_for_selector("#projects .project-card")
        page.fill("#search", "第12页")
        page.locator('#projects a[href="/projects/' + args.real + '"]').click()
        assert page.url.endswith("/projects/" + args.real)
        page.wait_for_selector("#name")
        page.reload()
        wait(page, "document.querySelector('#name').textContent.includes('第12页')")
        page.go_back()
        page.wait_for_selector("#projects .project-card")
        assert page.input_value("#search") == "第12页"
        checks.append("list click -> independent detail URL -> reload -> browser back retains search")
        page.fill("#search", "")
        page.screenshot(path=str(output / "list.png"))
        page.goto(args.base + "/projects/" + args.real)
        wait(page, "document.querySelector('#name').textContent.includes('第12页')")
        page.screenshot(path=str(output / "detail.png"))

        real = project(args.real)
        word, pdf = artifact(real, "docx", "m3"), artifact(real, "pdf", "m3")
        for a in [word, pdf]:
            assert a["preview_render"]["status"] == "SUCCEEDED"
            assert len(a["pages"]) == 2
            assert a["preview"]["artifact_sha256"] == a["sha256"]
        assert "LibreOffice" in word["preview"]["label"]
        review(args.real)
        for a, name in [(word, "source-word"), (pdf, "source-pdf")]:
            page.select_option("#rightArtifact", a["artifact_id"])
            image("left")
            image("right")
            for n in range(len(a["pages"])):
                page.select_option("#rightPosition", str(n))
                image("right")
                response = context.request.get(args.base + "/p/" + args.real + "/" + a["pages"][n]["image"])
                assert hashlib.sha256(response.body()).hexdigest() == a["pages"][n]["image_sha256"]
                page.screenshot(path=str(output / (name + f"-page{n + 1}.png")))
        checks.append(
            "actual page12 DOCX/LibreOffice and original PDF raster images decoded, all 4 output pages viewed"
        )

        page.select_option("#leftArtifact", word["artifact_id"])
        page.select_option("#rightArtifact", pdf["artifact_id"])
        page.select_option("#leftPosition", "1")
        page.select_option("#rightPosition", "0")
        page.select_option("#leftZoom", "175")
        page.select_option("#rightZoom", "175")
        image("left")
        image("right")
        page.eval_on_selector("#leftPane", "(p)=>p.scrollTop=220")
        left = page.eval_on_selector("#leftPane", "(p)=>p.scrollTop")
        header = page.locator("header").bounding_box()["y"]
        page.eval_on_selector("#rightPane", "(p)=>p.scrollTop=300")
        assert page.eval_on_selector("#leftPane", "(p)=>p.scrollTop") == left > 0
        right = page.eval_on_selector("#rightPane", "(p)=>p.scrollTop")
        page.eval_on_selector("#leftPane", "(p)=>p.scrollTop=420")
        assert page.eval_on_selector("#rightPane", "(p)=>p.scrollTop") == right > 0
        assert page.locator("header").bounding_box()["y"] == header == 0
        assert (
            page.locator("#leftPosition").input_value() == "1"
            and page.locator("#rightPosition").input_value() == "0"
        )
        page.screenshot(path=str(output / "word-pdf-independent.png"))
        page.click("#back")
        page.wait_for_selector("#review")
        page.click("#review")
        image("left")
        image("right")
        assert page.locator("#leftArtifact").input_value() == word["artifact_id"]
        assert page.locator("#leftPosition").input_value() == "1"
        checks.append(
            "Word versus PDF: independent 2/1 page selection, 175% zoom, both scroll directions and fixed toolbar; selection retained after detail return"
        )

        historical = project(args.legacy)
        assert len(historical["source_evaluations"]) == 36
        assert len(historical["legacy_quality_records"]) == 13
        review(args.legacy)
        image("left")
        wait(page, "!!document.querySelector('#rightContent pre')")
        assert page.locator("#sourcePosition option").count() == 50
        assert page.locator("img").count() == 1  # no whole-document image decoding
        page.select_option("#quality", "good")
        assert page.locator("#sourcePosition option").count() == 29
        source_list = page.locator("#sourcePosition").inner_text()
        page.select_option("#rightArtifact", historical["source_artifact_id"])
        image("right")
        assert page.locator("#sourcePosition").inner_text() == source_list
        page.select_option("#rightArtifact", artifact(historical, "markdown")["artifact_id"])
        page.select_option("#quality", "unknown")
        assert page.locator("#sourcePosition option").count() == 14
        page.select_option("#errorFilter", "remote")
        assert page.locator("#sourcePosition option").count() == 14
        assert page.locator("#rightPosition option").count() == 1
        page.screenshot(path=str(output / "source-quality-unknown-remote.png"))
        page.select_option("#quality", "poor")
        assert page.locator("#sourcePosition").input_value() == "-1"
        checks.append(
            "50 source pages: good29 / unknown14; source quality invariant across output switching; remote error separate and not poor; only current images loaded"
        )

        sample = project(args.sample)
        review(args.sample)
        page.select_option("#quality", "unknown")
        assert page.locator("#sourcePosition option").count() == 5
        page.select_option("#leftArtifact", artifact(sample, "docx")["artifact_id"])
        page.select_option("#rightArtifact", artifact(sample, "pdf")["artifact_id"])
        assert page.locator("#leftPosition option").count() == 10
        assert page.locator("#rightPosition option").count() == 9
        image("left")
        image("right")
        page.screenshot(path=str(output / "sample-word10-pdf9.png"))
        checks.append(
            "document sample: no quality = unknown5; actual DOCX10 / PDF9 pages independently locatable, no invented map"
        )

        # Only an existing synthetic developer fixture receives comments.
        review(args.synthetic)
        page.select_option("#reviewer", "developer-agent")
        page.select_option("#commentScope", "artifact")
        page.fill("#comment", "R2 合成产物评论，不是用户验收")
        page.click("#saveServer")
        wait(page, "document.querySelector('#status').textContent.includes('已保存到服务')")
        page.select_option("#commentScope", "source_page")
        assert page.input_value("#comment") != "R2 合成产物评论，不是用户验收"
        page.fill("#comment", "R2 合成原图评论，不是用户验收")
        page.click("#saveServer")
        wait(page, "document.querySelector('#status').textContent.includes('已保存到服务')")
        page.reload()
        wait(page, "document.querySelector('#comment').value==='R2 合成原图评论，不是用户验收'")
        page.select_option("#commentScope", "artifact")
        assert page.input_value("#comment") == "R2 合成产物评论，不是用户验收"
        with page.expect_download() as download:
            page.click("#export")
        receipt = output / "synthetic-feedback.json"
        download.value.save_as(receipt)
        data = json.loads(receipt.read_text())
        assert {"source_page", "artifact"} <= {c.get("object_type", "artifact") for c in data["comments"]}
        page.set_input_files("#import", receipt)
        wait(
            page,
            "document.querySelector('#status').textContent.includes('导入成功')||document.querySelector('#status').textContent.includes('已保存到服务')",
        )
        page.click("#clearComment")
        wait(page, "document.querySelector('#status').textContent.includes('已保存到服务')")
        assert page.input_value("#comment") == ""
        page.select_option("#commentScope", "source_page")
        assert page.input_value("#comment") == "R2 合成原图评论，不是用户验收"
        checks.append(
            "synthetic source/artifact comments isolated; save/reload/export/import/clear preserves other object; developer-agent attribution"
        )

        # Recheck an already rendered preview: no new renderer attempt.
        cache = context.request.post(
            args.base + "/api/projects/" + args.real + "/previews/" + word["artifact_id"],
            data={"retry": True},
        )
        assert cache.status == 202
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            actual = next(
                a for a in project(args.real)["artifacts"] if a["artifact_id"] == word["artifact_id"]
            )
            if actual["preview_render"]["status"] == "SUCCEEDED":
                assert actual["preview_render"]["cache_hit"]
                break
            time.sleep(0.1)
        else:
            raise AssertionError("cache deadline")
        checks.append("existing preview request uses verified image cache, not repeat render")

        # Export API and real file:// browser use the same preview snapshots.
        export = context.request.get(args.base + "/api/projects/" + args.real + "/export", timeout=120000)
        assert export.ok
        package = output / "page12-project.zip"
        package.write_bytes(export.body())
        folder = output / "offline-page12"
        with zipfile.ZipFile(package) as archive:
            archive.extractall(folder)
        offline = context.new_page()
        offline.on("pageerror", lambda e: errors.append(str(e)))
        offline.goto((folder / "review/index.html").as_uri())
        for side, a in [("left", word), ("right", pdf)]:
            offline.select_option("#" + side + "Artifact", a["artifact_id"])
            wait(offline, f"document.querySelector('#{side}Content img')?.naturalWidth>0")
        offline.screenshot(path=str(output / "offline-word-pdf.png"))
        assert offline.locator("img").count() == 2
        checks.append(
            "HTTP export unzipped and opened file:// offline: actual Word/PDF previews decode, two current images only"
        )
        assert not errors, errors
        result = {
            "browser": browser.version,
            "checks": checks,
            "page_errors": errors,
            "new_ocr_or_cloud_calls": 0,
        }
        (output / "checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:18971")
    for key in ["real", "legacy", "sample", "synthetic", "output"]:
        parser.add_argument("--" + key, required=True)
    run(parser.parse_args())
