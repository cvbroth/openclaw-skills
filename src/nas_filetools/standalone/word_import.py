"""Bounded non-executing DOCX/DOTX style extraction, not document conversion."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import uuid
import zipfile
from lxml import etree

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{" + NS["w"] + "}"
LIMIT = 20 * 1024 * 1024


def xml(z, name):
    raw = z.read(name)
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("XML: 不允许DTD或实体")
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    if root.getroottree().docinfo.doctype:
        raise ValueError("XML: 不允许DTD")
    return root


def val(node, path, attr="val"):
    item = node.find(path, NS) if node is not None else None
    return item.get(W + attr) if item is not None else None


def extract(path, name):
    try:
        return _extract(path, name)
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
        raise ValueError("Word样本无效：压缩包或必需XML不完整") from exc


def _extract(path, name):
    if Path(name).suffix.lower() not in {".docx", ".dotx"}:
        raise ValueError("仅支持无宏.docx和.dotx；PDF只能作为参考")
    if path.stat().st_size > LIMIT:
        raise ValueError("Word模板导入最多20MiB")
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        names = [x.filename for x in entries]
        if (
            len(entries) > 2000
            or len(set(names)) != len(names)
            or sum(x.file_size for x in entries) > 64 * 1024 * 1024
        ):
            raise ValueError("Word包展开量/条目数超过限制")
        for item in entries:
            p = PurePosixPath(item.filename)
            if p.is_absolute() or ".." in p.parts or "\\" in item.filename or item.flag_bits & 1:
                raise ValueError("Word包路径或加密条目不允许")
            if item.file_size > 16 * 1024 * 1024 or item.file_size > max(
                1024 * 1024, item.compress_size * 200
            ):
                raise ValueError("Word包单项或压缩比超过限制")
            if "vba" in item.filename.lower() or "activex" in item.filename.lower():
                raise ValueError("不接受宏或ActiveX")
        ct = xml(z, "[Content_Types].xml")
        types = " ".join(ct.xpath("//@ContentType"))
        if "macroEnabled" in types or not any(
            s in types for s in ["wordprocessingml.document.main+xml", "wordprocessingml.template.main+xml"]
        ):
            raise ValueError("不是受支持的无宏Word包")
        document = xml(z, "word/document.xml")
        styles = xml(z, "word/styles.xml")
        defaults = styles.find("w:docDefaults", NS)
        rdefault = defaults.find("w:rPrDefault/w:rPr", NS) if defaults is not None else None
        pdefault = defaults.find("w:pPrDefault/w:pPr", NS) if defaults is not None else None
        byid = {s.get(W + "styleId"): s for s in styles.findall("w:style", NS)}
        default_id = next(
            (k for k, s in byid.items() if s.get(W + "type") == "paragraph" and s.get(W + "default") == "1"),
            "Normal",
        )

        def props(nodes):
            out = {}
            fonts = {}
            for rp, pp in nodes:
                for prop, target, div in [("sz", "size_pt", 2)]:
                    v = val(rp, "w:" + prop)
                    if v is not None:
                        out[target] = float(v) / div
                for prop in ["b", "i"]:
                    if rp is not None and rp.find("w:" + prop, NS) is not None:
                        out["bold" if prop == "b" else "italic"] = val(rp, "w:" + prop) not in {
                            "0",
                            "false",
                            "off",
                        }
                rf = rp.find("w:rFonts", NS) if rp is not None else None
                if rf is not None:
                    fonts.update({k[len(W) :]: v for k, v in rf.attrib.items()})
                sp = pp.find("w:spacing", NS) if pp is not None else None
                if sp is not None:
                    for k, target in [("before", "space_before_pt"), ("after", "space_after_pt")]:
                        if sp.get(W + k) is not None:
                            out[target] = float(sp.get(W + k)) / 20
                    if sp.get(W + "line") is not None:
                        mode = {"auto": "multiple", "exact": "exact", "atLeast": "at_least"}.get(
                            sp.get(W + "lineRule", "auto")
                        )
                        if mode is None:
                            raise ValueError("不支持的Word行距规则")
                        out.update(
                            line_mode=mode,
                            line_value=float(sp.get(W + "line")) / (240 if mode == "multiple" else 20),
                        )
                ind = pp.find("w:ind", NS) if pp is not None else None
                if ind is not None:
                    for k, target in [
                        ("left", "left_cm"),
                        ("right", "right_cm"),
                        ("firstLine", "first_line_cm"),
                    ]:
                        if ind.get(W + k) is not None:
                            out[target] = float(ind.get(W + k)) * 2.54 / 1440
                    if ind.get(W + "hanging") is not None:
                        out["first_line_cm"] = -float(ind.get(W + "hanging")) * 2.54 / 1440
            return out, fonts

        def inherited(sid):
            chain = []
            seen = set()
            while sid in byid:
                if sid in seen:
                    raise ValueError("样式继承循环")
                seen.add(sid)
                s = byid[sid]
                chain.append((s.find("w:rPr", NS), s.find("w:pPr", NS)))
                sid = val(s, "w:basedOn")
            return props([(rdefault, pdefault)] + list(reversed(chain)))

        selected = {}
        font_records = {}
        for target, sid in [
            ("Normal", default_id),
            ("Title", "Title"),
            ("Heading 1", "Heading1"),
            ("Heading 2", "Heading2"),
            ("Heading 3", "Heading3"),
            ("Footer", "Footer"),
        ]:
            if sid not in byid:
                sid = next(
                    (k for k, s in byid.items() if (val(s, "w:name") or "").lower() == target.lower()), None
                )
            if sid:
                selected[target], font_records[target] = inherited(sid)
        sections = []
        for index, section in enumerate(document.findall(".//w:sectPr", NS)):
            settings = {}
            size = section.find("w:pgSz", NS)
            marg = section.find("w:pgMar", NS)
            if size is not None:
                for k, target in [("w", "width_cm"), ("h", "height_cm")]:
                    if size.get(W + k):
                        settings[target] = float(size.get(W + k)) * 2.54 / 1440
            if marg is not None:
                for k, target in [
                    ("top", "top_cm"),
                    ("bottom", "bottom_cm"),
                    ("left", "left_cm"),
                    ("right", "right_cm"),
                    ("header", "header_distance_cm"),
                    ("footer", "footer_distance_cm"),
                ]:
                    if marg.get(W + k) is not None:
                        settings[target] = float(marg.get(W + k)) * 2.54 / 1440
            sections.append(
                {
                    "index": index,
                    "settings": settings,
                    "orientation": "landscape"
                    if settings.get("width_cm", 0) > settings.get("height_cm", 1)
                    else "portrait",
                }
            )
        unsupported = []
        for label, xpath in [
            ("分栏", './/w:cols[@w:num and @w:num!="1"]'),
            ("复杂表格（不提取表格样式）", ".//w:tbl"),
            ("绘图/浮动对象", ".//w:drawing | .//w:pict"),
            ("列表编号样式", ".//w:numPr"),
        ]:
            if document.xpath(xpath, namespaces=NS):
                unsupported.append(label)
        if any(n.startswith(("word/header", "word/footer")) and n.endswith(".xml") for n in names):
            unsupported.append("页眉页脚内容不复制；仅提取距离和页码样式")
        if any("embeddings/" in n for n in names):
            unsupported.append("嵌入内容不执行、不导入")
        external = 0
        for n in names:
            if n.endswith(".rels"):
                external += len(
                    xml(z, n).xpath('//*[local-name()="Relationship" and @TargetMode="External"]')
                )
        if external:
            unsupported.append("外部关系仅记录，不访问（" + str(external) + "项）")
        if document.xpath('.//w:pgMar[@w:gutter and @w:gutter!="0"]', namespaces=NS):
            unsupported.append("装订线距离未导入")
        if (
            "word/settings.xml" in names
            and xml(z, "word/settings.xml").find("w:mirrorMargins", NS) is not None
        ):
            unsupported.append("对称页边距未导入")
        unsupported.extend(
            [
                "正文直接格式、主题颜色、制表位、边框及任意自定义样式未完整还原",
                "中西字体信息单独记录；本版须选择统一服务器字体",
            ]
        )
        return {
            "schema": "word-style-extraction-v1",
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "filename": Path(name).name,
            "sections": sections,
            "section_selection_required": len({json.dumps(s["settings"], sort_keys=True) for s in sections})
            > 1,
            "paragraphs": selected,
            "fonts": font_records,
            "unsupported": unsupported,
            "status": "loaded-not-saved",
            "user_review": "required; extraction is not faithful full template reconstruction",
        }


def suggestion(library, record, section_index=None, font_family=None):
    sections = record["sections"]
    if not sections:
        raise ValueError("未发现可用节设置")
    if record["section_selection_required"] and section_index is None:
        return None
    index = 0 if section_index is None else section_index
    if type(index) is not int or not 0 <= index < len(sections):
        raise ValueError("section_index: 请选择有效节")
    doc = deepcopy(library.load("questions-zh-cn", "1.0.0")["document"])
    doc.update(
        schema_version=3,
        id="word-style-" + record["import_id"][:8],
        version="1.0.0",
        name="Word样式导入草稿",
        description="仅导入明确支持的样式；复杂内容见提取报告",
    )
    doc["word_styles"] = {"section": sections[index]["settings"], "paragraphs": record["paragraphs"]}
    if font_family is not None:
        if font_family not in library.fonts:
            raise ValueError("font_family: 请选择已安装字体")
        doc["parameters"]["font_family"] = font_family
    doc["import_source"] = {
        "import_id": record["import_id"],
        "sha256": record["file_sha256"],
        "section_index": index,
        "font_selection_confirmed": font_family is not None,
    }
    return doc


class WordImports:
    def import_word(self, file, name):
        record = extract(file, name)
        iid = str(uuid.uuid4())
        record["import_id"] = iid
        record["missing_fonts"] = sorted(
            {
                v
                for props in record["fonts"].values()
                for k, v in props.items()
                if k in {"ascii", "hAnsi", "eastAsia", "cs"} and v not in self.fonts
            }
        )
        record["needs_selection"] = ["统一的已安装字体（不静默替换）"] + (
            ["适用节"] if record["section_selection_required"] else []
        )
        root = self.root / "imports" / iid
        root.mkdir(parents=True)
        import shutil

        shutil.copyfile(file, root / ("original" + Path(name).suffix.lower()))
        (root / "report.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
        return {"report": record, "document": suggestion(self, record)}

    def select_word_import(self, iid, section_index=None, font_family=None):
        iid = str(uuid.UUID(iid))
        record = json.loads((self.root / "imports" / iid / "report.json").read_text())
        return {"report": record, "document": suggestion(self, record, section_index, font_family)}
