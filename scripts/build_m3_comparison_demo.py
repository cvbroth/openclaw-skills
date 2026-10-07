"""Add a private static comparison view to an existing offline review bundle.

Preserves the confirmation ledger unchanged. Model suggestions are displayed as
unconfirmed evidence only. No server, credential, or model call is involved.
"""

import argparse
import json
from pathlib import Path
import shutil
import zipfile


HTML = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>五页OCR与M3对照</title>
<style>body{font:16px system-ui,"Microsoft YaHei",sans-serif;margin:24px;background:#f5f6f8;color:#222}header,article{background:white;padding:18px;margin-bottom:16px;border:1px solid #bbb}header{position:sticky;top:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}img{max-width:100%;max-height:500px}select,button{font:inherit;padding:6px}summary{cursor:pointer;padding:8px}a{color:#1254a3}.warn{color:#8b2600}</style>
<header><strong>五页OCR／M3对照 · 开发实验</strong>
<p class="warn">全部人工状态未确认。模型“保留”和质量分不能代替验收；本轮存在质量漏报和格式失败，程序候选继续保留，尚未证明能安全减少人工范围。</p>
<label>物理页 <select id="page"></select></label>
<a href="index.html">打开既有离线复核界面（筛选、裁片、导出确认JSON）</a>
</header><main id="main"></main>
<script id="data" type="application/json">__PAYLOAD__</script>
<script>
'use strict';const data=JSON.parse(document.getElementById('data').textContent),page=document.getElementById('page'),main=document.getElementById('main');
function el(t,s,p){const n=document.createElement(t);if(s!==undefined)n.textContent=s;if(p)p.append(n);return n}
for(const p of data.pages){const o=el('option',String(p.physical_page),page);o.value=p.physical_page}
function draw(){main.replaceChildren();const p=data.pages.find(x=>String(x.physical_page)===page.value),a=el('article',undefined,main);el('h2',`物理${p.physical_page} · 人工验收：未确认`,a);el('p',`源图SHA-256：${p.image_sha256}`,a);const l=el('a','打开固定整页原图',a);l.href=p.image;l.target='_blank';l.rel='noopener';
for(const [route,r] of Object.entries(p.routes)){const d=el('details',undefined,a);el('summary',`${route} · 质量评价、系统建议与用量`,d);el('pre',JSON.stringify(r,null,2),d)}
for(const [name,text] of Object.entries(p.texts)){const d=el('details',undefined,a);el('summary',name,d);el('pre',text,d)}
for(const r of p.regions){const card=el('article',undefined,main);el('h3',`${r.region_id} · ${r.risks.join(' / ')} · 未确认`,card);const im=el('img',undefined,card);im.src=r.image;im.alt='程序选定原图区域';im.onclick=()=>window.open(r.image,'_blank','noopener');el('p',`原图坐标 ${JSON.stringify(r.bbox)}`,card);for(const item of r.items){const d=el('details',undefined,card);el('summary',item.id,d);el('strong','本地当前文字',d);el('pre',item.current_text,d);el('strong','M3建议（不等于人类确认）',d);el('pre',JSON.stringify(item.model,null,2),d)}}}
page.onchange=draw;draw();
</script></html>'''


def build(args):
    if args.output.exists() or args.zip.exists():
        raise ValueError("OUTPUT_EXISTS")
    shutil.copytree(args.bundle, args.output)
    (args.output / "comparison-assets").mkdir()
    analysis = json.loads(args.analysis.read_text())
    summary = json.loads(args.summary.read_text())
    manifest = json.loads((args.executed / "manifest.json").read_text())
    pages = []
    for p in summary["pages"]:
        page = p["physical_page"]
        source = analysis[str(page)]
        items = {i["id"]: i for i in source["items"]}
        model_items = {i["id"]: i for i in source["review"].get("candidate_results", [])}
        row = next(v for v in manifest["pages"] if v["physical_page"] == page)
        for region in row["regions"]:
            name = f"page-{page}-{region['region_id']}.png"
            shutil.copyfile(args.executed / "assets" / name, args.output / "comparison-assets" / name)
        pages.append({
            "physical_page": page, "image_sha256": p["image_sha256"],
            "image": f"assets/page-{page}-image.png", "routes": p["routes"],
            "texts": {
                "本地原生版面组装": "\n\n".join(b["block_content"] for b in source["native"]["parsing_res_list"]),
                "本地空间恢复后": "\n\n".join(b["block_content"] for b in source["source_review"]["repaired_blocks"]),
                "M3直接转写（含原始误读，不润色）": source["direct"].get("body_text", "不可解析"),
                "本地＋M3未确认修订副本": "\n\n".join(b["block_content"] for b in source["revised_blocks"]),
            },
            "regions": [{
                **region,
                "image": f"comparison-assets/page-{page}-{region['region_id']}.png",
                "items": [{"id": i, "current_text": items[i]["current_text"], "model": model_items.get(i)} for i in region["ids"]],
            } for region in row["regions"]],
        })
    payload = json.dumps({"pages": pages}, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace("&", "\\u0026")
    (args.output / "comparison.html").write_text(HTML.replace("__PAYLOAD__", payload), encoding="utf-8")
    (args.output / "comparison.json").write_text(json.dumps({"pages": pages}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for route in ("direct", "review"):
        target = args.output / "model-responses" / route
        target.mkdir(parents=True)
        for record in summary["pages"]:
            page = record["physical_page"]
            shutil.copyfile(args.executed / "responses" / route / f"page-{page}.response.json", target / f"page-{page}.json")
    (args.output / "README-COMPARISON.txt").write_text(
        "解压完整ZIP，先打开comparison.html；无网络、无需Web服务。\n"
        "对照页显示原图、原生/恢复/M3文字、质量分、用量及程序选定候选区域。\n"
        "进入index.html可按页/风险/状态筛选，导出确认JSON。模型建议没有导入确认账本。\n"
        "本轮三路对照尚未证明可安全减少人工候选：视觉质量存在漏报，模型有改写、漏检及格式失败。\n"
        "原始模型响应及文字仅在本私有包中，不上传Git。高分不等于准确，模型自评不等于独立复核。\n",
        encoding="utf-8",
    )
    with zipfile.ZipFile(args.zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(args.output.rglob("*")):
            if path.is_file():
                archive.write(path, str(Path(args.output.name) / path.relative_to(args.output)))
    print(json.dumps({"pages": len(pages), "regions": sum(len(p["regions"]) for p in pages), "zip_bytes": args.zip.stat().st_size}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("bundle", "analysis", "summary", "executed", "output", "zip"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(parser.parse_args())
