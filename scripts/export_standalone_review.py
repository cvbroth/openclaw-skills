"""Export explicitly selected terminal HTTP projects into a portable review bundle.

No conversion/recognition requests. Private bundles must remain outside the repository.
"""

import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
import urllib.request
from urllib.parse import urlsplit
import uuid
import zipfile


def export(base, projects, target):
    url = urlsplit(base)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "localhost"}
        or url.path not in {"", "/"}
        or url.query
        or url.username is not None
        or url.password is not None
    ):
        raise ValueError("trusted loopback HTTP service required")
    target.mkdir(parents=True, exist_ok=False)
    records = []
    for slug, pid, name in projects:
        uuid.UUID(pid)
        if not slug.isascii() or not slug.replace("-", "").isalnum():
            raise ValueError("invalid project directory")
        project = target / slug
        with urllib.request.urlopen(
            base.rstrip("/") + "/api/projects/" + pid + "/export", timeout=180
        ) as response:
            archive = target / (slug + ".zip")
            with archive.open("xb") as stream:
                shutil.copyfileobj(response, stream, 1024 * 1024)
        with zipfile.ZipFile(archive) as zipped:
            for info in zipped.infolist():
                path = Path(info.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or (info.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError("unsafe export path")
            zipped.extractall(project)
        archive.unlink()
        p = json.loads((project / "project.json").read_text())
        assert p["project_id"] == pid
        records.append(
            {
                "directory": slug,
                "project_id": pid,
                "name": name,
                "project_json_sha256": hashlib.sha256((project / "project.json").read_bytes()).hexdigest(),
            }
        )
    (target / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>FileTools 对照交付</title><link rel="stylesheet" href="bundle.css"><main><h1>FileTools · 对照评审</h1><p>解压后离线打开。原图评价来自历史模型自评，不代表准确率；评论与正文独立。</p>'
        + "".join(
            '<a class="card" href="'
            + r["directory"]
            + '/review/index.html"><strong>'
            + html.escape(r["name"])
            + "</strong><span>打开项目 →</span></a>"
            for r in records
        )
        + "<p>两侧可独立选择原件、Markdown、Word、PDF及页码；Word预览来自实际DOCX渲染。评论先存本机，请导出JSON备份。</p><p>完整使用说明见 README.md，真实截图见 screenshots/。</p></main>",
        encoding="utf-8",
    )
    (target / "bundle.css").write_text(
        'body{font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif;color:#26364d;background:#f4f6fa;margin:0}main{max-width:900px;margin:55px auto;padding:20px}h1{font-size:30px}.card{display:flex;justify-content:space-between;gap:15px;padding:22px;margin:14px 0;border:1px solid #e0e6ef;border-radius:10px;background:white;color:#285ee8;text-decoration:none}.card span{font-size:14px}p{color:#637389}'
    )
    (target / "bundle-manifest.json").write_text(
        json.dumps(
            {"schema": "standalone-review-bundle-v1", "projects": records}, ensure_ascii=False, indent=2
        )
    )
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:18971")
    parser.add_argument(
        "--project", nargs=3, action="append", metavar=("DIRECTORY", "PROJECT_ID", "NAME"), required=True
    )
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.base, args.project, args.target), ensure_ascii=False, indent=2))
