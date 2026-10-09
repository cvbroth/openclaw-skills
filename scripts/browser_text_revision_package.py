"""Export actual project; verify portable paths, relocation and offline previews."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from playwright.sync_api import sync_playwright


def main(args):
    args.out.mkdir(parents=True, exist_ok=True)
    result = json.loads(args.receipt.read_text())
    with sync_playwright() as w:
        browser = w.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        response = context.request.get(args.base + "/api/projects/" + args.project + "/export")
        assert response.ok, response.text()
        package = args.out / "project.zip"
        package.write_bytes(response.body())
        root = args.out / "relocated" / "任意目录 R7演示"
        root.mkdir(parents=True)
        with zipfile.ZipFile(package) as archive:
            assert archive.testzip() is None
            for name in archive.namelist():
                path = Path(name)
                assert not path.is_absolute() and ".." not in path.parts
                assert not any(c in name for c in ':\\<>"|?*')
                assert not any(
                    part.startswith(".") or part in ["lo-profile", "tmp", "temp"] for part in path.parts
                )
            archive.extractall(root)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(
            (root / "review/index.html").resolve().as_uri()
            + "?right="
            + result["restored_artifact_id"]
            + "&right_location=%7B%22kind%22%3A%22block%22%2C%22id%22%3A%22p23-text%22%7D"
        )
        page.wait_for_selector("#rightContent .reading")
        assert "错字" in page.locator("#rightContent").inner_text()
        assert page.locator("#textMode").is_disabled()
        assert "离线包仅供阅读" in page.locator("#textState").inner_text()
        page.screenshot(path=str(args.out / "offline-reading.png"))
        page.goto(
            (root / "review/index.html").resolve().as_uri()
            + "?left="
            + result["word_artifact_id"]
            + "&right="
            + result["pdf_artifact_id"]
        )
        page.wait_for_selector("#leftContent img")
        page.wait_for_selector("#rightContent img")
        for _ in range(100):
            if page.evaluate("[...document.querySelectorAll('main img')].every(i=>i.naturalWidth>0)"):
                break
            page.wait_for_timeout(100)
        assert page.evaluate("[...document.querySelectorAll('main img')].every(i=>i.naturalWidth>0)")
        page.screenshot(path=str(args.out / "offline-word-pdf.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(args.out / "narrow.png"))
        assert not errors, errors
        record = {
            "zip_bytes": package.stat().st_size,
            "zip_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
            "portable_paths_crc": True,
            "relocated_file_protocol_reading": True,
            "offline_edit_disabled": True,
            "actual_word_pdf_images_decode": True,
            "page_errors": errors,
            "windows_actual_unzip": "not available; portable path and CRC checks only",
        }
        (args.out / "package-browser.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:18971")
    p.add_argument("--project", required=True)
    p.add_argument("--receipt", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    main(p.parse_args())
