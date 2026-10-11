"""Deterministic supplementary fonts, explicit runs, OOXML embedding and audit."""

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import struct
import uuid
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as ET
import fitz
from docx.oxml.ns import qn

ROOT = Path(__file__).with_name("fonts")


def fallback_records():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    records = []
    for entry in manifest["fonts"]:
        path = ROOT / entry["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("补充字体文件校验失败，请重新部署官方字体包：" + entry["name"])
        records.append({**entry, "path": str(path)})
    return records


@lru_cache(maxsize=16)
def font_chain(primary_path):
    records = fallback_records()
    return [fitz.Font(fontfile=str(primary_path))] + [fitz.Font(fontfile=r["path"]) for r in records]


def font_runs(text, primary_path):
    fonts = font_chain(str(primary_path))
    records = fallback_records()
    result = []
    for c in text:
        index = next((i for i, f in enumerate(fonts) if c.isspace() or f.has_glyph(ord(c))), None)
        if index is None:
            raise ValueError(
                f"FONT_MISSING_GLYPHS: 字体缺少字符“{c}”(U+{ord(c):04X})；主字体及补充字体均未覆盖。请安装覆盖该字符的字体并重新导出，正文未被修改。"
            )
        name = records[index - 1]["name"] if index else None
        if result and result[-1][0] == name:
            result[-1] = (name, result[-1][1] + c)
        else:
            result.append((name, c))
    return result


def apply_run_font(run, name):
    run.font.name = name
    fonts = run._element.get_or_add_rPr().get_or_add_rFonts()
    for k in ["ascii", "hAnsi", "eastAsia", "cs"]:
        fonts.set(qn("w:" + k), name)


def font_audit(groups, primary):
    used = []
    for group in groups:
        for position, (_, text) in enumerate(group["items"], 1):
            offset = 0
            try:
                resolved = font_runs(str(text), primary)
            except ValueError as exc:
                raise ValueError(
                    f"{exc} 来源物理页 {group.get('source_pdf_physical_page') or '未登记'}，段落位置 {position}。"
                ) from exc
            for name, part in resolved:
                if name:
                    used.append(
                        {
                            "source_page": group.get("source_pdf_physical_page"),
                            "source_locator": group.get("source_locator"),
                            "paragraph": position,
                            "offset": offset,
                            "font": name,
                            "characters": sorted(set(part)),
                            "unicode": sorted({f"U+{ord(c):04X}" for c in part}),
                        }
                    )
                offset += len(part)
    return {
        "schema": "font-resolution-v1",
        "primary_path": str(primary),
        "primary_sha256": hashlib.sha256(Path(primary).read_bytes()).hexdigest(),
        "fallbacks": fallback_records(),
        "substitutions": used,
        "text_changed": False,
        "docx_embedding": "full OFL supplementary fonts, obfuscated OpenXML",
        "pdf_embedding": "verified actual LibreOffice PDF font resources",
    }


def embed_fonts(path):
    """Embed only supplementary fonts actually referenced in the Word body.

    Obfuscate first 32 bytes with reversed GUID key (ECMA-376 font embedding).
    OFL allows embedding. No font outline or source text is altered.
    """
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    ct = "http://schemas.openxmlformats.org/package/2006/content-types"
    with ZipFile(path) as z:
        data = {n: z.read(n) for n in z.namelist()}
    body = ET.fromstring(data["word/document.xml"])
    names = {v for f in body.iter("{" + w + "}rFonts") for v in f.attrib.values()}
    if not any(r["name"] in names for r in fallback_records()):
        return
    table = ET.fromstring(data["word/fontTable.xml"])
    relationships_path = "word/_rels/fontTable.xml.rels"
    relations = (
        ET.fromstring(data[relationships_path])
        if relationships_path in data
        else ET.Element("{" + pkg + "}Relationships")
    )
    content_types = ET.fromstring(data["[Content_Types].xml"])
    for i, record in enumerate(fallback_records()):
        if record["name"] not in names:
            continue
        raw = bytearray(Path(record["path"]).read_bytes())
        # OS/2 fsType=0: installable embedding. Reject restricted fonts.
        tables = struct.unpack(">H", raw[4:6])[0]
        for j in range(tables):
            tag, _, start, _ = struct.unpack(">4sIII", raw[12 + j * 16 : 28 + j * 16])
            if tag == b"OS/2" and struct.unpack(">H", raw[start + 8 : start + 10])[0] != 0:
                raise ValueError("补充字体禁止嵌入：" + record["name"])
        key = uuid.UUID(record["sha256"][:32])
        mask = key.bytes[::-1]
        for j in range(32):
            raw[j] ^= mask[j % 16]
        target = f"fonts/supplement-{i}.odttf"
        data["word/" + target] = raw
        node = next((e for e in table if e.get("{" + w + "}name") == record["name"]), None)
        if node is None:
            node = ET.SubElement(table, "{" + w + "}font", {"{" + w + "}name": record["name"]})
        rid = f"rIdFileToolsFont{i}"
        for child in list(node):
            if child.tag == "{" + w + "}embedRegular":
                node.remove(child)
        ET.SubElement(
            node,
            "{" + w + "}embedRegular",
            {"{" + rel + "}id": rid, "{" + w + "}fontKey": "{" + str(key).upper() + "}"},
        )
        for e in list(relations):
            if e.get("Id") == rid:
                relations.remove(e)
        ET.SubElement(
            relations, "{" + pkg + "}Relationship", {"Id": rid, "Type": rel + "/font", "Target": target}
        )
    if not any(e.get("Extension") == "odttf" for e in content_types):
        ET.SubElement(
            content_types,
            "{" + ct + "}Default",
            {
                "Extension": "odttf",
                "ContentType": "application/vnd.openxmlformats-officedocument.obfuscatedFont",
            },
        )
    for name, tree in [
        ("word/fontTable.xml", table),
        (relationships_path, relations),
        ("[Content_Types].xml", content_types),
    ]:
        data[name] = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
    temp = Path(str(path) + ".fonts.tmp")
    with ZipFile(temp, "w", ZIP_DEFLATED) as z:
        for name, raw in data.items():
            z.writestr(name, raw)
    temp.replace(path)
