"""Optional development-only Playwright check for the file:// comparison bundle."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def check(root, output, screenshot=None, font=None):
    manifest = json.loads((root / 'manifest.json').read_bytes())
    errors, external, checked = [], [], []
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: external.append(request.url) if request.url.startswith(('http:', 'https:')) else None)
        page.goto((root / 'index.html').resolve().as_uri())
        if font:
            encoded = base64.b64encode(font.read_bytes()).decode()
            page.add_style_tag(content='@font-face{font-family:DevChinese;src:url(data:font/ttf;base64,' + encoded + ')}body,pre{font-family:DevChinese,sans-serif!important}')
            page.evaluate('document.fonts.ready')
        for image in manifest['images']:
            physical = image['physical_page']
            page.select_option('#page', str(physical))
            page.wait_for_function('document.querySelector("#image").complete && document.querySelector("#image").naturalWidth > 0')
            assert page.locator('#image').evaluate('(im)=>[im.naturalWidth,im.naturalHeight]') == [image['width'], image['height']]
            assert page.locator('article').count() == 4
            for article in page.locator('article').all():
                method = article.locator('h2').inner_text()
                raw = root / method / f'page-{physical}' / 'raw.md'
                if raw.exists():
                    shown = article.locator('pre').nth(1).text_content()
                    assert hashlib.sha256(shown.encode()).hexdigest() == hashlib.sha256(raw.read_bytes()).hexdigest()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            checked.append(physical)
            if screenshot and physical == 23:
                page.screenshot(path=str(screenshot))
        browser.close()
    assert not errors and not external
    result = {'engine': 'Playwright Chromium', 'version': browser.version, 'development_screenshot_font_injected': bool(font), 'physical_pages_checked': checked,
              'raw_text_dom_byte_equality': 'passed for every available output',
              'original_image_dimensions': 'passed', 'js_errors': errors,
              'external_requests': external, 'horizontal_overflow': False,
              'scope': 'UI mechanics only; no transcription accuracy or human visual acceptance'}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('--font', type=Path, help='optional local development screenshot font, not added to delivery')
    args = parser.parse_args()
    check(args.root, args.output, args.screenshot, args.font)
