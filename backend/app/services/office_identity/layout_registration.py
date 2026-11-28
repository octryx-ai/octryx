"""Register generated ``slideLayout`` parts in a PowerPoint package."""

from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path

from lxml import etree

from .layout_authoring import NS_P, GeneratedLayout, LayoutSpec, build_layout_xml

NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
NS_PR = "http://schemas.openxmlformats.org/package/2006/relationships"

LAYOUT_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"
)
LAYOUT_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
)

#: Fixed zip timestamp for parts this module creates, so that normalising the
#: same template twice yields byte-identical output.
_FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def _next_layout_number(names: set[str]) -> int:
    numbers = [
        int(name[len("ppt/slideLayouts/slideLayout") : -len(".xml")])
        for name in names
        if name.startswith("ppt/slideLayouts/slideLayout")
        and name.endswith(".xml")
        and name[len("ppt/slideLayouts/slideLayout") : -len(".xml")].isdigit()
    ]
    return max(numbers, default=0) + 1


def _rels_name(part: str) -> str:
    directory, base = posixpath.split(part)
    return posixpath.join(directory, "_rels", f"{base}.rels")


def _next_rel_id(rels_root: etree._Element) -> str:
    used = {str(rel.attrib.get("Id") or "") for rel in rels_root}
    numbers = [int(value[3:]) for value in used if value.startswith("rId") and value[3:].isdigit()]
    return f"rId{max(numbers, default=0) + 1}"


def _next_layout_id(id_list: etree._Element) -> int:
    #: ECMA-376: slide layout ids are >= 2147483648.
    ids = []
    for entry in id_list:
        try:
            ids.append(int(entry.attrib.get("id", 0)))
        except (TypeError, ValueError):
            continue
    return max([*ids, 2147483648]) + 1


def _register_in_master(
    master_xml: bytes, layout_part: str, master_part: str, master_rels: bytes
) -> tuple[bytes, bytes, str, int]:
    rels_root = etree.fromstring(master_rels)
    rel_id = _next_rel_id(rels_root)
    relationship = etree.SubElement(rels_root, f"{{{NS_PR}}}Relationship")
    relationship.set("Id", rel_id)
    relationship.set("Type", LAYOUT_REL_TYPE)
    relationship.set("Target", posixpath.relpath(layout_part, posixpath.dirname(master_part)))

    master_root = etree.fromstring(master_xml)
    id_list = master_root.find(f"{{{NS_P}}}sldLayoutIdLst")
    if id_list is None:
        raise ValueError(f"master has no sldLayoutIdLst: {master_part}")
    layout_id = _next_layout_id(id_list)
    entry = etree.SubElement(id_list, f"{{{NS_P}}}sldLayoutId")
    entry.set("id", str(layout_id))
    entry.set(f"{{{NS_R}}}id", rel_id)
    return (
        etree.tostring(master_root, xml_declaration=True, encoding="UTF-8", standalone=True),
        etree.tostring(rels_root, xml_declaration=True, encoding="UTF-8", standalone=True),
        rel_id,
        layout_id,
    )


def _register_content_type(content_types: bytes, parts: list[str]) -> bytes:
    root = etree.fromstring(content_types)
    declared = {
        str(node.attrib.get("PartName") or "") for node in root.findall(f"{{{NS_CT}}}Override")
    }
    for part in parts:
        part_name = f"/{part}"
        if part_name in declared:
            continue
        override = etree.SubElement(root, f"{{{NS_CT}}}Override")
        override.set("PartName", part_name)
        override.set("ContentType", LAYOUT_CONTENT_TYPE)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _read_package(source: Path) -> tuple[list[zipfile.ZipInfo], dict[str, bytes]]:
    with zipfile.ZipFile(source, "r") as archive:
        entries = list(archive.infolist())
        payloads = {item.filename: archive.read(item.filename) for item in entries}
    return entries, payloads


def _add_layout(
    payloads: dict[str, bytes],
    new_parts: dict[str, bytes],
    spec: LayoutSpec,
    layout_part: str,
) -> GeneratedLayout:
    donor_xml = payloads.get(spec.donor_part)
    if donor_xml is None:
        raise ValueError(f"donor layout part missing: {spec.donor_part}")
    master_xml = payloads.get(spec.master_part)
    master_rels = payloads.get(_rels_name(spec.master_part))
    if master_xml is None or master_rels is None:
        raise ValueError(f"master part or its relationships missing: {spec.master_part}")

    layout_xml, removed = build_layout_xml(donor_xml, spec)
    donor_rels = payloads.get(_rels_name(spec.donor_part))
    if donor_rels is None:
        raise ValueError(f"donor layout has no relationships: {spec.donor_part}")

    master_xml, master_rels, rel_id, layout_id = _register_in_master(
        master_xml, layout_part, spec.master_part, master_rels
    )
    payloads[spec.master_part] = master_xml
    payloads[_rels_name(spec.master_part)] = master_rels
    new_parts[layout_part] = layout_xml
    # The donor's relationships resolve relative to the same directory, so
    # copying them verbatim keeps the master link and every image the donor
    # design uses.
    new_parts[_rels_name(layout_part)] = donor_rels
    return GeneratedLayout(
        spec=spec,
        part=layout_part,
        rel_id=rel_id,
        layout_id=layout_id,
        removed_placeholders=removed,
    )


def _write_package(
    output: Path,
    entries: list[zipfile.ZipInfo],
    payloads: dict[str, bytes],
    new_parts: dict[str, bytes],
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as out:
        for item in entries:
            out.writestr(item, payloads[item.filename])
        for name in sorted(new_parts):
            info = zipfile.ZipInfo(name, date_time=_FIXED_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            out.writestr(info, new_parts[name])


def add_layouts(source: Path, output: Path, specs: list[LayoutSpec]) -> list[GeneratedLayout]:
    if not specs:
        raise ValueError("add_layouts requires at least one layout spec")
    source = Path(source)
    output = Path(output)

    entries, payloads = _read_package(source)

    names = set(payloads)
    if "[Content_Types].xml" not in names:
        raise ValueError(f"not an OPC package (no [Content_Types].xml): {source}")

    next_number = _next_layout_number(names)
    generated: list[GeneratedLayout] = []
    new_parts: dict[str, bytes] = {}
    for spec in specs:
        layout_part = f"ppt/slideLayouts/slideLayout{next_number}.xml"
        next_number += 1
        generated.append(_add_layout(payloads, new_parts, spec, layout_part))

    payloads["[Content_Types].xml"] = _register_content_type(
        payloads["[Content_Types].xml"], [item.part for item in generated]
    )
    _write_package(output, entries, payloads, new_parts)
    return generated


__all__: list[str] = ["LAYOUT_CONTENT_TYPE", "LAYOUT_REL_TYPE", "add_layouts"]
