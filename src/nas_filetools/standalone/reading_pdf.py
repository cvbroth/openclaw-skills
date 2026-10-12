"""Searchable PDF and paper preview from the same local reader HTML/CSS."""

import asyncio
import json
from pathlib import Path
import fitz
from ..reading_style import emit_reading_assets
from ..artifact_project import digest
from .content_structure import reading_html


class ReaderPDF:
    def __init__(self, out, style):
        from playwright.async_api import async_playwright

        self.out, self.style = Path(out), style
        self.assets = self.out / "reading-assets"
        self.assets.mkdir(exist_ok=True)
        emit_reading_assets(self.assets)
        self.loop = asyncio.new_event_loop()
        self.pw = self.loop.run_until_complete(async_playwright().start())
        self.browser = None
        self.calls = 0
        self.version = None

    def close(self):
        async def shutdown():
            if self.browser:
                await self.browser.close()
            await self.pw.stop()

        try:
            self.loop.run_until_complete(asyncio.wait_for(shutdown(), 10))
        finally:
            self.loop.close()

    def render(self, models, folder, size, line, gap, preview=False):
        return self.loop.run_until_complete(
            asyncio.wait_for(self._render(models, folder, size, line, gap, preview), 60)
        )

    async def _render(self, models, folder, size, line, gap, preview):
        folder = Path(folder)
        if self.browser is None or self.calls % 25 == 0:
            if self.browser:
                await self.browser.close()
            self.browser = await self.pw.chromium.launch(
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking"]
            )
            self.version = self.browser.version
        self.calls += 1
        content = "".join(reading_html(m) for m in models)
        width, height = self.style["paper_mm"]
        margin = self.style["margin_mm"]
        html = (
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            f'<link rel="stylesheet" href="{(self.assets / "reading.css").as_uri()}">'
            "<style>"
            f"@page{{size:{width}mm {height}mm;margin:{margin}mm}}"
            "html,body{margin:0;padding:0;background:white}*{box-sizing:border-box}"
            f".reading{{display:flow-root;width:{width - 2 * margin}mm;padding:0;border:0;margin:0;"
            f"font-size:{size}pt;line-height:{line};overflow-wrap:anywhere;"
            "-webkit-print-color-adjust:exact;print-color-adjust:exact}"
            f".reading p{{margin:{gap}em 0}}"
            '</style><main class="reading">' + content + "</main></html>"
        )
        path = folder / "reading.html"
        path.write_text(html)
        context = await self.browser.new_context(
            viewport={"width": 794, "height": 1123}, java_script_enabled=True
        )
        try:
            page = await context.new_page()
            page.set_default_timeout(30_000)
            await page.route(
                "**/*",
                lambda route: route.continue_() if route.request.url.startswith("file:") else route.abort(),
            )
            await page.emulate_media(media="print")
            await page.goto(path.as_uri(), wait_until="load")
            metrics = await page.evaluate("""async () => {
                await Promise.all([...document.fonts].map(f => f.load()));
                await document.fonts.ready;
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                const root = document.querySelector('.reading');
                const box = root.getBoundingClientRect();
                const fonts = [...document.fonts].map(f => ({family:f.family,status:f.status}));
                return {height_px:box.height,width_px:box.width,fonts,
                    font_family:getComputedStyle(root).fontFamily,
                    font_size:getComputedStyle(root).fontSize,line_height:getComputedStyle(root).lineHeight};
            }""")
            if not metrics["fonts"] or any(f["status"] != "loaded" for f in metrics["fonts"]):
                # Unused fallback faces may remain unloaded: explicitly load every local face.
                await page.evaluate(
                    "async()=>{await Promise.all([...document.fonts].map(f=>f.load()));await document.fonts.ready}"
                )
                metrics["fonts"] = await page.evaluate(
                    "()=>[...document.fonts].map(f=>({family:f.family,status:f.status}))"
                )
            if any(f["status"] != "loaded" for f in metrics["fonts"]):
                raise ValueError("本地阅读字体未完整加载，停止生成PDF")
            metrics["available_height_px"] = (height - 2 * margin) * 96 / 25.4
            metrics["overflow"] = metrics["height_px"] > metrics["available_height_px"] + 0.5
            pdf = folder / "reading.pdf"
            await asyncio.wait_for(
                page.pdf(path=str(pdf), prefer_css_page_size=True, print_background=True, tagged=True), 30
            )
            with fitz.open(pdf) as doc:
                metrics["actual_output_pages"] = len(doc)
                metrics["overflow"] |= len(doc) != 1
                if preview:
                    for i, p in enumerate(doc):
                        # Preview is rasterized from this actual candidate PDF, never used as final PDF.
                        if i >= 10:
                            break
                        p.get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False).save(
                            folder / f"preview-{i + 1}.png"
                        )
            metrics["renderer"] = {
                "name": "Chromium",
                "version": self.version,
                "playwright": "1.55.0",
                "mode": "local HTML/CSS; print media; searchable tagged PDF",
                "batch_limit": 25,
                "algorithm": "reader-print-v1",
                "html_sha256": digest(path),
                "css_sha256": digest(self.assets / "reading.css"),
            }
            (folder / "measurement.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
            return pdf, metrics
        finally:
            await context.close()
