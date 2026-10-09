"""Real browser synthetic upload/analysis/extraction; remote calls are never started."""

import argparse
import json
from pathlib import Path
import time
from playwright.sync_api import sync_playwright


def run(base, fixtures, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result = {}
    errors = []
    states = []
    with sync_playwright() as w:
        browser = w.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1500, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "console", lambda m: states.append(m.text[13:]) if m.text.startswith("UPLOAD_STATE:") else None
        )
        page.add_init_script(
            "document.addEventListener('DOMContentLoaded',()=>{let n=document.querySelector('#uploadState');if(n)new MutationObserver(()=>console.log('UPLOAD_STATE:'+n.textContent)).observe(n,{childList:true});});"
        )

        def wait(predicate, timeout=90):
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                value = predicate()
                if value:
                    return value
                time.sleep(0.15)
            raise AssertionError("browser workflow deadline")

        def project(pid):
            return context.request.get(base + "/api/projects/" + pid).json()

        def upload(filename, name):
            page.goto(base + "/")
            page.click("#toggleUpload")
            assert page.locator("#engine").count() == 0 and page.locator("#pages").count() == 0
            page.fill("#projectName", name)
            page.set_input_files("#file", str(Path(fixtures) / filename))
            page.locator("#upload").screenshot(path=str(output / "upload.png"))
            page.click("#start")
            page.wait_for_url("**/projects/*")
            return page.url.rsplit("/", 1)[1]

        pid = upload("source-types.pdf", "R4 合成来源分析")
        p = wait(
            lambda: (v if (v := project(pid))["analysis"]["status"] not in ["RUNNING", "QUEUED"] else None)
        )
        assert p["tasks"] == [] and p["source_info"]["units"] == 5
        assert [r["category"] for r in p["analysis"]["pages"]] == [
            "text",
            "scan",
            "mixed",
            "text",
            "blank_or_undetermined",
        ]
        assert p["source_info"]["actual_type"] == "PDF"
        page.reload()
        page.wait_for_selector("#analysisStatus")
        wait(lambda: "5 / 5" in page.locator("#analysisStatus").inner_text())
        page.locator("#sourceInfo").screenshot(path=str(output / "source-information.png"))
        result["upload_created_without_recognition"] = True
        result["classification"] = p["analysis"]["summary"]
        result["project_id"] = pid
        result["source_sha256"] = p["artifacts"][0]["sha256"]
        page.locator(".new-task summary").click()
        page.select_option("#newEngine", "pdf-text")
        page.fill("#newPages", "1,3")
        page.click("#newTask")
        p = wait(
            lambda: (
                v
                if (v := project(pid))["tasks"] and v["tasks"][-1]["status"] not in ["QUEUED", "RUNNING"]
                else None
            )
        )
        assert p["tasks"][-1]["status"] == "SUCCEEDED", p["tasks"][-1].get("error")
        result["direct_text_selected_pages"] = list(p["tasks"][-1]["pages"])
        result["direct_text_visual_quality"] = p.get("source_evaluations", [])
        assert result["direct_text_visual_quality"] == []
        p = wait(
            lambda: (
                v
                if (v := project(pid))["artifacts"]
                and not any(
                    a.get("preview_render", {}).get("status") in ["QUEUED", "RUNNING"] for a in v["artifacts"]
                )
                else None
            )
        )
        assert any(a["format"] == "docx" for a in p["artifacts"]) and any(
            a["format"] == "pdf" and a["artifact_id"] != p["source_artifact_id"] for a in p["artifacts"]
        )
        page.reload()
        page.wait_for_selector("#sourceInfo p")
        page.screenshot(path=str(output / "project.png"))
        result["direct_text_word_pdf_artifact_ids"] = [
            a["artifact_id"]
            for a in p["artifacts"]
            if a["format"] in ["docx", "pdf"] and a["artifact_id"] != p["source_artifact_id"]
        ]
        page.goto(base + "/engines")
        page.wait_for_selector("#choose option", state="attached")
        page.select_option("#choose", "compatible")
        page.select_option("#action", "replace")
        page.fill("#key", "synthetic-browser-key-not-real")
        page.click("#save")
        wait(lambda: "已保存" in page.locator("#message").inner_text())
        assert page.input_value("#key") == ""
        payload = context.request.get(base + "/api/engines").text()
        assert "synthetic-browser-key-not-real" not in payload
        page.click("#test")
        wait(lambda: "尚未验证" in page.locator("#message").inner_text())
        page.select_option("#action", "clear")
        page.click("#save")
        wait(lambda: "未配置密钥" in page.locator("#keyState").inner_text())
        page.screenshot(path=str(output / "engines.png"))
        result["settings_write_clear_no_key_readback"] = True
        result["remote_connection_test"] = "no request; unverified"
        # Explicit local recognition of synthetic image, separate from upload.
        local = upload("local-ocr.png", "R4 合成本地识别")
        p = wait(
            lambda: (v if (v := project(local))["analysis"]["status"] not in ["QUEUED", "RUNNING"] else None)
        )
        assert p["tasks"] == []
        page.reload()
        page.wait_for_selector("#sourceInfo p")
        page.locator(".new-task summary").click()
        page.select_option("#newEngine", "local")
        page.fill("#newPages", "1")
        page.click("#newTask")
        p = wait(
            lambda: (
                v
                if (v := project(local))["tasks"] and v["tasks"][-1]["status"] not in ["QUEUED", "RUNNING"]
                else None
            ),
            180,
        )
        result["local_project_id"] = local
        result["local_status"] = p["tasks"][-1]["status"]
        result["local_pages"] = p["tasks"][-1]["pages"]
        assert result["local_status"] == "SUCCEEDED", p["tasks"][-1].get("error")
        page.reload()
        page.wait_for_selector("#sourceInfo p")
        page.screenshot(path=str(output / "local-project.png"))
        invalid = upload("invalid.pdf", "R4 合成异常原件")
        p = wait(
            lambda: (
                v if (v := project(invalid))["analysis"]["status"] not in ["QUEUED", "RUNNING"] else None
            )
        )
        assert p["analysis"]["status"] == "FAILED" and p["tasks"] == []
        page.reload()
        page.wait_for_selector("#retryAnalysis")
        page.click("#retryAnalysis")
        wait(lambda: project(invalid)["analysis"]["analysis_id"] != p["analysis"]["analysis_id"])
        wait(lambda: project(invalid)["analysis"]["status"] == "FAILED")
        result["failed_source_retained_and_retry"] = True
        result["invalid_project_id"] = invalid
        result["upload_states"] = states
        assert any("上传进度" in s for s in states) and any("正在检查文件" in s for s in states)
        result.update(browser=browser.version, js_errors=errors, new_cloud_calls=0)
        assert not errors, errors
        (output / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({k: v for k, v in result.items() if k != "local_pages"}, ensure_ascii=False))
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18971")
    parser.add_argument("--fixtures", required=True)
    parser.add_argument("--output", required=True)
    a = parser.parse_args()
    run(a.base, a.fixtures, a.output)
