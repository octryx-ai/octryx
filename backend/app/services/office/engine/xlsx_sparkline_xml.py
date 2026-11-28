"""Package XML for sparklines: the x14 namespaces, sheet part names and the ``sparklineGroups`` extension, which
openpyxl neither writes nor keeps (see ``xlsx_extras``)."""

from __future__ import annotations

import posixpath
import zipfile

from lxml import etree

_X14 = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"
_XM = "http://schemas.microsoft.com/office/excel/2006/main"
_SPARKLINE_EXT = "{05C60535-1F16-4fd2-B633-F4F36F0B64E0}"
_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _sheet_parts(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = etree.fromstring(archive.read("xl/workbook.xml"))
    rels = etree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {rel.get("Id"): rel.get("Target") for rel in rels.iter(f"{{{_PKG_REL}}}Relationship")}
    parts: dict[str, str] = {}
    for sheet in workbook.iter(f"{{{_MAIN}}}sheet"):
        target = targets.get(sheet.get(f"{{{_REL}}}id"), "")
        parts[sheet.get("name")] = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
    return parts


def _with_sparklines(payload: bytes, groups: list[str]) -> bytes:
    root = etree.fromstring(payload)
    ext_list = root.find(f"{{{_MAIN}}}extLst")
    if ext_list is None:
        ext_list = etree.SubElement(root, f"{{{_MAIN}}}extLst")
    for ext in list(ext_list):
        if ext.get("uri") == _SPARKLINE_EXT:
            ext_list.remove(ext)
    ext = etree.SubElement(ext_list, f"{{{_MAIN}}}ext", nsmap={"x14": _X14})
    ext.set("uri", _SPARKLINE_EXT)
    container = etree.SubElement(ext, f"{{{_X14}}}sparklineGroups", nsmap={"xm": _XM})
    for group in groups:
        container.append(etree.fromstring(group))
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
