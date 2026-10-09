"""Synthetic-only final management regression and relocated offline package check."""

import argparse
import json
from pathlib import Path
import shutil
import zipfile
from playwright.sync_api import sync_playwright


def main(args):
    args.out.mkdir(parents=True, exist_ok=True)
    result = {}
    with sync_playwright() as w:
        b = w.chromium.launch(headless=True, args=["--no-sandbox"])
        c = b.new_context(viewport={"width": 1440, "height": 1000})
        p = c.new_page()
        errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        base = args.base.rstrip("/")
        model = c.request.get(base + "/api/projects/" + args.existing).json()
        md = next(
            a for a in reversed(model["artifacts"]) if a["format"] == "markdown" and not a.get("recycled")
        )
        p.goto(base + "/projects/" + args.existing)
        p.wait_for_selector("#artifacts .artifact-row")
        assert not p.locator("#taskHistory").evaluate("(n)=>n.open")
        row = p.locator('[data-artifact-id="' + md["artifact_id"] + '"]')
        row.locator(".artifact-menu>summary").click()
        assert row.get_by_role("button", name="回收", exact=True).is_visible()
        row.get_by_role("button", name="回收", exact=True).click()
        p.wait_for_selector(
            '#artifactRecycle [data-artifact-id="' + md["artifact_id"] + '"]', state="attached"
        )
        p.locator("#artifactRecycle>summary").click()
        p.locator('#artifactRecycle [data-artifact-id="' + md["artifact_id"] + '"] button').click()
        p.wait_for_timeout(400)
        after = c.request.get(base + "/api/projects/" + args.existing).json()
        restored = next(a for a in after["artifacts"] if a["artifact_id"] == md["artifact_id"])
        assert (
            not restored.get("recycled")
            and restored["sha256"] == md["sha256"]
            and restored["parents"] == md["parents"]
        )
        result["more_menu_recycle_restore_preserves_identity"] = True
        result["history_folded"] = True
        assert any(
            "中文" in o["label"]
            for o in p.locator("#formatTemplate option").evaluate_all(
                "(nodes)=>nodes.map(n=>({label:n.textContent}))"
            )
        )
        p.screenshot(path=str(args.out / "project-final.png"), full_page=True)
        if args.large:
            p.goto(base + "/projects/" + args.large)
            p.wait_for_selector("#taskHistory")
            assert not p.locator("#taskHistory").evaluate("(n)=>n.open")
            p.locator("#taskHistory>summary").click()
            d = p.locator(".page-detail").first
            d.locator("summary").click()
            d.locator("tr").first.wait_for()
            assert d.locator("tr").count() == 51
            result["existing_simulated_1000_lazy_rows"] = d.locator("tr").count()
        # Folded narrow toolbar must remain navigable.
        source = c.request.get(base + "/api/projects/" + args.project).json()["source_artifact_id"]
        p.goto(base + "/p/" + args.project + "/review/index.html?left=" + source + "&right=" + source)
        p.wait_for_selector("#leftContent img")
        p.set_viewport_size({"width": 390, "height": 844})
        p.click("#toggleToolbar")
        assert not p.evaluate("document.documentElement.scrollWidth>innerWidth")
        p.screenshot(path=str(args.out / "folded-narrow.png"))
        result["narrow_fold_no_overflow"] = True
        # Move a freshly exported project; uncached page must stay explicit offline.
        p.goto(base + "/projects/" + args.existing)
        p.wait_for_selector("#artifacts .artifact-row")
        for name, pid in [("original169", args.project), ("documents", args.existing)]:
            response = c.request.get(base + "/api/projects/" + pid + "/export", timeout=180000)
            assert response.ok, response.text()
            target = args.out / (name + ".zip")
            target.write_bytes(response.body())
            with zipfile.ZipFile(target) as archive:
                assert archive.testzip() is None
                archive.extractall(args.out / name)
        moved = args.out / "relocated"
        if moved.exists():
            shutil.rmtree(moved)
        shutil.copytree(args.out / "original169", moved)
        p.set_viewport_size({"width": 1440, "height": 1000})
        p.goto((moved / "review/index.html").resolve().as_uri() + "?left=" + source + "&right=" + source)
        p.wait_for_selector("#leftContent img")
        assert p.locator("#sourcePosition option").count() == 169
        p.evaluate('()=>jump("left",23)')
        p.wait_for_selector('#leftContent img[alt="原件物理第23页"]')
        assert p.evaluate('document.querySelector("#leftContent img").naturalWidth>0')
        p.evaluate('()=>jump("left",2)')
        assert "本页未缓存" in p.locator("#leftContent").inner_text()
        assert p.locator("#leftContent img").count() == 0
        assert "未缓存" in p.locator('#sourcePosition option[value="1"]').inner_text()
        p.select_option("#commentScope", "source_page")
        p.fill("#comment", "R6 离线未缓存页2的合成草稿")
        p.reload()
        p.wait_for_selector("#leftPageInput")
        assert p.input_value("#leftPageInput") == "2"
        assert "本页未缓存" in p.locator("#leftContent").inner_text()
        assert "未缓存页2" in p.input_value("#comment")
        p.screenshot(path=str(args.out / "offline-uncached.png"))
        result["relocated_offline_full_index_cached_23_missing_2"] = True
        result["offline_uncached_comment_reload"] = True
        data = json.loads((moved / "project.json").read_text())
        source_row = next(a for a in data["artifacts"] if a["artifact_id"] == source)
        result["offline_cached_pages"] = [x["physical_page"] for x in source_row["pages"] if x.get("image")]
        result["offline_total_pages"] = 169
        result["javascript_errors"] = errors
        assert not errors
        (args.out / "edges.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False))
        b.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18971")
    parser.add_argument("--project", required=True)
    parser.add_argument("--existing", required=True)
    parser.add_argument("--large")
    parser.add_argument("--out", type=Path, required=True)
    main(parser.parse_args())
