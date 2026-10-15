"""Real native Word/PDF, versioned cleanup and editable merged-table acceptance."""

from copy import deepcopy
import json
import time
import uuid
from zipfile import ZipFile
import fitz
import pytest
from lxml import etree
from nas_filetools.artifact_project import digest, page_data, register_artifact, emit_viewer
from nas_filetools.standalone.tasks import Projects
from nas_filetools.standalone.content_marks import clean_rows, detect
from nas_filetools.standalone.table_structure import tables, parse_html, to_html, correct
from nas_filetools.standalone.pandoc_export import generate, reference_path
from nas_filetools.standalone.content_structure import parse_markdown, reading_html
from test_standalone_http import configuration


def wait(m, pid, tid=None):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        p = m.get(pid)
        task = m.task(p, tid) if tid else p.get("analysis", {})
        if task.get("status") not in {"QUEUED", "RUNNING", "CANCELLING"}:
            return p, task
        time.sleep(0.05)
    pytest.fail("task timeout")


@pytest.fixture
def project(tmp_path):
    m = Projects(tmp_path / "store", configuration())
    source = tmp_path / "source.pdf"
    with fitz.open() as pdf:
        for _ in range(20):
            pdf.new_page()
        pdf.save(source)
    pid = m.upload(source, source.name)["project_id"]
    wait(m, pid)
    p = m.get(pid)
    root = m.path(pid)
    views = []
    texts = []
    for n in range(6, 12):
        text = f"合成重复书名\n\n## 第{n}章\n\n正文相同数字 12 与题号 23。\n\n|列一|列二|\n|---|---|\n|合成重复书名|12|\n\n{n - 5}"
        texts.append(text)
        path = f"content/p{n}.js"
        page_data(root, path, {"text": text})
        views.append({"source_page": n, "locator": {"kind": "block", "id": f"p{n}"}, "data": path})
    (root / "content/body.md").write_text("\n\n".join(texts))
    a = register_artifact(root, p, name="合成文字", format="markdown", path="content/body.md", pages=views)
    emit_viewer(root, p)
    m.save(root, p)
    try:
        yield m, pid, a["artifact_id"]
    finally:
        m.close()


def test_marks_preserve_original_decisions_and_revision_review(project):
    m, pid, aid = project
    root = m.path(pid)
    before = digest(root / "content/body.md")
    marks = m.identify_marks(pid, aid)
    assert len(marks["candidates"]) == 12
    assert all("合成重复书名" == x["text"] or x["text"].isdigit() for x in marks["candidates"])
    chosen = [x["id"] for x in marks["candidates"] if x["kind"] == "header"]
    marks = m.decide_marks(pid, aid, {"revision": marks["revision"], "ids": chosen, "decision": "confirmed"})
    assert all(
        x["decision"] == "confirmed" for x in m.identify_marks(pid, aid)["candidates"] if x["id"] in chosen
    )
    info = m.text_artifact(pid, aid)
    page = info["pages"][0]
    result = m.save_text_revision(
        pid,
        {
            "request_id": str(uuid.uuid4()),
            "parent_artifact_id": aid,
            "parent_sha256": info["sha256"],
            "head_id": aid,
            "head_sha256": info["sha256"],
            "locator": page["locator"],
            "text": "修订后\n" + page["text"],
        },
    )
    inherited = m.content_marks(pid, result["artifact_id"])
    assert all(x["decision"] == "needs_review" for x in inherited["candidates"] if x["source_page"] == 6)
    assert all(
        x["decision"] == "confirmed"
        for x in inherited["candidates"]
        if x["source_page"] != 6 and x["id"] in chosen
    )
    assert digest(root / "content/body.md") == before


def test_cleaning_exact_ranges_never_global_or_table():
    row = {
        "view": {"locator": {"kind": "block", "id": "p1"}},
        "text": "书名\n正文书名\n\n|列|\n|---|\n|书名|\n",
    }
    mark = {
        "decision": "confirmed",
        "actor_type": "human-self-declared",
        "kind": "header",
        "locator": row["view"]["locator"],
        "start": 0,
        "end": 2,
        "text": "书名",
    }
    rows, summary = clean_rows([row], {"candidates": [mark]}, {"remove_headers": True})
    assert rows[0]["text"].count("书名") == 2 and row["text"].count("书名") == 3 and len(summary) == 1
    start = row["text"].rfind("书名")
    mark.update(start=start, end=start + 2)
    with pytest.raises(ValueError, match="表格"):
        clean_rows([row], {"candidates": [mark]}, {"remove_headers": True})


@pytest.mark.parametrize("formats", [["docx"], ["pdf"], ["docx", "pdf"]])
def test_actual_export_cleaned_natural_pages_and_immutable(project, formats):
    m, pid, aid = project
    root = m.path(pid)
    before = digest(root / "content/body.md")
    marks = m.identify_marks(pid, aid)
    m.decide_marks(
        pid,
        aid,
        {
            "revision": marks["revision"],
            "ids": [x["id"] for x in marks["candidates"]],
            "decision": "confirmed",
        },
    )
    job = m.export_documents(
        pid,
        {
            "source_artifact_id": aid,
            "formats": formats,
            "remove_headers": True,
            "remove_footers": True,
            "new_header": True,
        },
    )
    p, t = wait(m, pid, job["task_id"])
    assert t["status"] == "SUCCEEDED", t.get("error")
    outputs = [a for a in p["artifacts"] if a.get("task_id") == t["task_id"] and a["role"] == "export"]
    assert {a["format"] for a in outputs} == set(formats)
    with fitz.open(root / "diagnostics/format" / t["task_id"] / "work/document.pdf") as pdf:
        assert len(pdf) < 6 and all(page.get_text().strip() for page in pdf)
        assert sum(page.get_text().count("合成重复书名") for page in pdf) == 6  # Table cells retained.
        assert "23" in "".join(page.get_text() for page in pdf)
    assert len(t["document_export"]["cleaning_summary"]) == 12
    assert all(x["output_pages"] is None for x in outputs[0]["source_output_mapping"])
    assert digest(root / "content/body.md") == before


def merged_model():
    cells = []

    def cell(r, c, text, rs=1, cs=1, head=False):
        cells.append({"row": r, "column": c, "text": text, "rowspan": rs, "colspan": cs, "header": head})

    cell(0, 0, "对象", 2, 1, True)
    for c, label in [(1, "分组甲"), (4, "分组乙"), (7, "分组丙")]:
        cell(0, c, label, 1, 3, True)
    for c in range(1, 10):
        cell(1, c, "C" + str((c - 1) % 3 + 1), head=True)
    for r in range(2, 6):
        cell(r, 0, "S" + str(r - 1))
        for c in range(1, 7):
            cell(r, c, str((r + c) % 4))
    for c, value in enumerate([0, 2, 1], 7):
        cell(2, c, str(value), 4)
    return {"rows": 6, "columns": 10, "cells": cells}


def direct_request(tmp_path, text):
    return {
        "output": str(tmp_path),
        "reference": str(reference_path()),
        "reference_sha256": digest(reference_path()),
        "project_root": str(tmp_path),
        "source_path": "sample.md",
        "source_artifact_id": "synthetic",
        "source_sha256": "synthetic",
        "title": "合成转换",
        "settings": {"new_header": True, "new_page_numbers": True, "cleaning_summary": []},
        "pages": [
            {"text": text, "source_locator": {"kind": "block", "id": "p1"}, "source_pdf_physical_page": 3}
        ],
    }


def test_actual_complex_native_table_and_reader(tmp_path):
    model = merged_model()
    text = to_html(model)
    assert [
        {k: v for k, v in c.items() if k != "runs"}
        for c in sorted(parse_html(text)["cells"], key=lambda c: (c["row"], c["column"]))
    ] == sorted(model["cells"], key=lambda c: (c["row"], c["column"]))
    rendered = reading_html(parse_markdown(text))
    assert "<table>" in rendered and 'rowspan="4"' in rendered
    generate(direct_request(tmp_path, text))
    with ZipFile(tmp_path / "document.docx") as z:
        xml = etree.fromstring(z.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        assert len(xml.xpath("//w:tbl", namespaces=ns)) == 1
        assert len(xml.xpath("//w:tr", namespaces=ns)) == 6
        assert len(xml.xpath("//w:vMerge", namespaces=ns)) == 14
        assert xml.xpath('//w:gridSpan[@w:val="3"]', namespaces=ns)
    with fitz.open(tmp_path / "document.pdf") as pdf:
        assert len(pdf) == 1 and all("S" + str(n) in pdf[0].get_text() for n in range(1, 5))


def test_normal_table_escaped_pipe_html_safety_and_invalid_merges():
    text = "|名称|值|\n|---|---|\n|甲\\|乙|1|\n|空||\n"
    parsed = tables(text)
    assert len(parsed) == 1 and parsed[0]["model"]["columns"] == 2
    assert "甲|乙" in reading_html(parse_markdown(text))
    with pytest.raises(ValueError, match="标签"):
        parse_html("<table><tr><td><script>bad</script></td></tr></table>")
    with pytest.raises(ValueError, match="属性"):
        parse_html('<table onclick="bad"><tr><td>a</td></tr></table>')
    with pytest.raises(ValueError, match="空单元格"):
        parse_html("<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>")
    model = merged_model()
    before = deepcopy(model)
    changed = correct(model, {"edits": [{"row": 2, "column": 1, "text": "新值"}]})
    assert (
        model == before
        and changed["cells"][
            next(i for i, c in enumerate(changed["cells"]) if (c["row"], c["column"]) == (2, 1))
        ]["text"]
        == "新值"
    )
    with pytest.raises(ValueError, match="矩形"):
        correct(model, {"merge": {"row": 1, "column": 0, "rowspan": 2, "colspan": 2}})


def test_generic_formats_images_links_yaml_and_question_numbers(tmp_path):
    from PIL import Image

    Image.new("RGB", (200, 80), "green").save(tmp_path / "sample.png")
    text = "---\n\n普通分隔线后的正文\n\n# 标题\n\n**加粗** *斜体* ①②③\n\n1. 题目原编号\n\nA. 原选项\n\nB. 原选项乙\n\n1. 真正列表\n2. 下一项\n\n- 无序列表\n\n> 引用\n\n```python\nx = 1\n```\n\n[链接](https://example.com)\n\n![图片说明](sample.png)\n\n|甲|乙|\n|---|---|\n|1|2|"
    generate(direct_request(tmp_path, text))
    with ZipFile(tmp_path / "document.docx") as z:
        xml = z.read("word/document.xml").decode()
        assert "题目原编号" in xml and "1." in xml and "<w:numPr>" in xml
        assert "<w:hyperlink" in xml and "<w:drawing>" in xml and "<w:tbl>" in xml
        assert "PAGE" in z.read("word/footer1.xml").decode()
    assert json.loads((tmp_path / "layout-validation.json").read_text())["content_equal"]


@pytest.mark.parametrize("url", ["missing.png", "https://example.com/image.png", "../../outside.png"])
def test_missing_remote_or_outside_images_fail(tmp_path, url):
    with pytest.raises(ValueError, match="图片资源"):
        generate(direct_request(tmp_path, "![原图](" + url + ")"))
    assert not (tmp_path / "document.docx").exists()


def test_old_pagination_settings_rejected_and_history_untouched(project):
    m, pid, aid = project
    with pytest.raises(ValueError, match="迁移"):
        m.export_documents(pid, {"source_artifact_id": aid, "compact": {"enabled": True}})
    with pytest.raises(ValueError, match="来源强制"):
        m.format_artifact(pid, aid, None, pagination={"mode": "source-pages"})
    with pytest.raises(ValueError, match="没有文字记录"):
        m.export_documents(pid, {"source_artifact_id": aid, "pages": "1-6"})


def test_long_editable_table_repeats_headers_without_loss(tmp_path):
    text = "|项目|说明|数字|\n|---|---|---|\n" + "\n".join(
        f"|行{i}|第{i}项长文字，换行仍应保留单元格关系。|{i * 7}|" for i in range(1, 101)
    )
    generate(direct_request(tmp_path, text))
    report = json.loads((tmp_path / "layout-validation.json").read_text())
    assert report["tables"][0]["rows"] == 101 and report["output_pages"] > 1
    assert report["repeated_table_headers"]
    with fitz.open(tmp_path / "document.pdf") as pdf:
        assert "700" in "".join(p.get_text() for p in pdf)
        assert all(p.get_text().strip() for p in pdf)


def test_explicit_numeric_starts_and_options_are_not_rewritten(tmp_path):
    text = "3. 列表原三\n7. 列表原七\n\n23. 题号原二十三\n\nA. 选项甲\n\nB. 选项乙"
    generate(direct_request(tmp_path, text))
    with fitz.open(tmp_path / "document.pdf") as pdf:
        actual = "".join(p.get_text() for p in pdf)
        assert "7." in actual and "23." in actual and "A." in actual and "B." in actual
        assert "4." not in actual


def test_table_alignment_and_rich_cell_formats(tmp_path):
    text = "|列甲|列乙|\n|:---|---:|\n|**加粗** *斜体*|[链接](https://example.com)|"
    data = tables(text)[0]
    assert not data.get("error")
    assert data["model"]["cells"][1]["alignment"] == "right"
    html = reading_html(parse_markdown(text))
    assert "<strong>加粗</strong>" in html and "<em>斜体</em>" in html and 'align="right"' in html
    generate(direct_request(tmp_path, text))
    with ZipFile(tmp_path / "document.docx") as z:
        xml = z.read("word/document.xml").decode()
        assert "<w:hyperlink" in xml and "<w:b" in xml and "<w:i" in xml


def test_extra_or_missing_markdown_columns_never_silently_drop_text(tmp_path):
    text = "|甲|乙|\n|---|---|\n|保留甲|保留乙|不可丢失的第三格|"
    table = tables(text)[0]
    assert "行列数不一致" in table["error"]
    assert "不可丢失的第三格" in reading_html(parse_markdown(text))
    with pytest.raises(ValueError, match="行列数不一致"):
        generate(direct_request(tmp_path, text))
    assert not (tmp_path / "document.docx").exists()


def test_developer_confirmation_is_not_human_cleanup(project):
    m, pid, aid = project
    marks = m.identify_marks(pid, aid)
    marks = m.decide_marks(
        pid,
        aid,
        {
            "revision": marks["revision"],
            "ids": [x["id"] for x in marks["candidates"]],
            "decision": "confirmed",
            "reviewer_type": "developer-agent",
        },
    )
    from nas_filetools.standalone.text_revisions import mapped_text

    a = next(a for a in m.get(pid)["artifacts"] if a["artifact_id"] == aid)
    rows = mapped_text(m.path(pid), a)
    cleaned, summary = clean_rows(rows, marks, {"remove_headers": True, "remove_footers": True})
    assert cleaned == rows and not summary


def test_export_progress_is_atomic_under_concurrent_polling(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from nas_filetools.standalone.tasks import atomic

    target = tmp_path / "progress.json"
    atomic(target, {"phase": "parse", "completed": 0, "total": 500})

    def writer():
        for i in range(500):
            atomic(target, {"phase": "parse", "completed": i, "total": 500})

    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(writer)
        while not future.done():
            value = json.loads(target.read_text())
            assert value["phase"] == "parse" and 0 <= value["completed"] < 500
        future.result()


def test_identical_tables_have_distinct_source_ranged_ids():
    source = "|甲|乙|\n|---|---|\n|1|2|\n"
    found = tables(source + "\n" + source)
    assert len(found) == 2 and found[0]["id"] != found[1]["id"]
    assert found[0]["end"] <= found[1]["start"]


def test_page_edges_are_not_each_fragment_edges():
    rows = []
    for page in range(1, 4):
        for part, text in enumerate(
            ["书名标题\n\n正文开始", "反复出现的中段正文\n其他中段内容", "正文末尾\n\n" + str(page)]
        ):
            rows.append(
                {
                    "view": {"source_page": page, "locator": {"kind": "block", "id": f"{page}-{part}"}},
                    "text": text,
                }
            )
    candidates = detect(rows)
    assert candidates and all("中段" not in m["text"] for m in candidates)


def test_pdf_text_vector_tables_extract_and_reexport_without_ocr(tmp_path):
    from nas_filetools.standalone.pdf_tables import extract

    first = tmp_path / "first"
    first.mkdir()
    generate(direct_request(first, "# 合成复杂表格\n\n" + to_html(merged_model())))
    with fitz.open(first / "document.pdf") as pdf:
        extracted = extract(pdf[0], 1)
    assert not extracted["issues"] and "<table>" in extracted["text"]
    model = extracted["tables"][0]
    assert (model["rows"], model["columns"]) == (6, 10)
    assert len([c for c in model["cells"] if c["rowspan"] == 4]) == 3
    assert all(c["coordinate_system"] == "source-pdf-points" for c in model["cells"])
    second = tmp_path / "second"
    second.mkdir()
    request = direct_request(second, extracted["text"])
    request["settings"]["new_header"] = False
    request["settings"]["new_page_numbers"] = False
    generate(request)
    assert (
        json.loads((second / "layout-validation.json").read_text())["tables"][0]["vertical_merge_cells"] == 14
    )


def test_pdf_text_ordinary_table_is_markdown_and_plain_page_unchanged(tmp_path):
    from nas_filetools.standalone.pdf_tables import extract

    generate(direct_request(tmp_path, "原文在表格外\n\n|甲|乙|\n|---|---|\n|1||\n|2|3|"))
    with fitz.open(tmp_path / "document.pdf") as pdf:
        result = extract(pdf[0], 1)
    assert not result["issues"] and "| --- | --- |" in result["text"] and "<table>" not in result["text"]
    assert "原文在表格外" in result["text"]
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), "Plain source 123")
        assert extract(page, 1)["text"] == page.get_text("text", sort=False)


def test_local_pdf_extraction_publishes_tables_and_reliable_header_boxes(tmp_path):
    first = tmp_path / "first"
    first.mkdir()
    request = direct_request(first, to_html(merged_model()))
    generate(request)
    source = tmp_path / "three-source-pages.pdf"
    with fitz.open(first / "document.pdf") as sample, fitz.open() as pdf:
        for _ in range(3):
            pdf.insert_pdf(sample)
        pdf.save(source)
    before = digest(source)
    m = Projects(tmp_path / "store", configuration())
    try:
        pid = m.upload(source, source.name)["project_id"]
        wait(m, pid)
        job = m.enqueue(pid, "pdf-text", [1, 2, 3])
        p, t = wait(m, pid, job["task_id"])
        assert t["status"] == "SUCCEEDED", t.get("error")
        a = next(
            a for a in p["artifacts"] if a.get("task_id") == job["task_id"] and a["format"] == "markdown"
        )
        text = (m.path(pid) / a["path"]).read_text()
        assert text.count("<table>") == 3
        mark = m.content_marks(pid, a["artifact_id"])
        assert mark["candidates"] and any(c["coordinates"] is not None for c in mark["candidates"])
        assert all(c["decision"] == "pending" for c in mark["candidates"])
        result = json.loads((m.path(pid) / t["pages"]["1"]["latest"]["result"]).read_text())
        assert len([b for b in result["blocks"] if b["type"] == "table"]) == 1
        assert len(result["native"]["tables"][0]["cells"]) == 44
        source_record = next(a for a in p["artifacts"] if a["artifact_id"] == p["source_artifact_id"])
        assert digest(m.path(pid) / source_record["path"]) == before
    finally:
        m.close()


def test_table_revision_uses_markdown_unless_explicit_complex_structure():
    from nas_filetools.standalone.table_structure import serialize

    ordinary = tables("|甲|乙|\n|---|---|\n|**原强调**|2|")[0]["model"]
    result = serialize(correct(ordinary, {"edits": [{"row": 1, "column": 1, "text": "修订值"}]}))
    assert result.startswith("|") and "**原强调**" in result and "修订值" in result
    assert "<table>" in serialize(merged_model())
