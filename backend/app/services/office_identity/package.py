"""OPC package access for PowerPoint templates.

Reads a ``.potx``/``.pptx`` straight from the zip container: no temporary
extraction, no binary payloads leaving this module. Relationship targets are
resolved against the owning part, which is what makes theme resolution
(``presentation.xml`` -> ``sldMasterId`` -> master rels -> theme) correct,
never a hard-coded ``ppt/theme/theme1.xml`` guess.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from ..corp_identity.parsing import NS_P, NS_R

PRESENTATION_PART = "ppt/presentation.xml"

_TEMPLATE_CONTENT_TYPE = "presentationml.template.main+xml"
_PRESENTATION_CONTENT_TYPE = "presentationml.presentation.main+xml"

_LAYOUT_PATTERN = re.compile(r"^ppt/slideLayouts/slideLayout(\d+)\.xml$")
_MASTER_PATTERN = re.compile(r"^ppt/slideMasters/slideMaster(\d+)\.xml$")
_SLIDE_PATTERN = re.compile(r"^ppt/slides/slide(\d+)\.xml$")


def potx_bytes_to_pptx_bytes(data: bytes) -> bytes:
    """Rewrite the template content type so python-pptx accepts the package.

    python-pptx (1.0.2) rejects ``.potx`` outright; only the declared content
    type of the presentation part differs. Every other entry is copied
    verbatim, preserving order and compression.
    """
    out_buf = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data), "r") as zin,
        zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout,
    ):
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                content = content.decode("utf-8").replace(
                    _TEMPLATE_CONTENT_TYPE, _PRESENTATION_CONTENT_TYPE
                ).encode("utf-8")
            zout.writestr(item, content)
    return out_buf.getvalue()


def write_pptx_copy(source: Path, destination: Path) -> None:
    """Copy ``source`` to ``destination`` as a presentation package."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(potx_bytes_to_pptx_bytes(Path(source).read_bytes()))


def _rels_part_name(part_name: str) -> str:
    directory, base = posixpath.split(part_name)
    return posixpath.join(directory, "_rels", f"{base}.rels")


def _resolve_target(part_name: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    directory = posixpath.dirname(part_name)
    return posixpath.normpath(posixpath.join(directory, target))


class PresentationPackage:
    """Read-only view of a PowerPoint OPC package."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        try:
            self._zip = zipfile.ZipFile(self.path, "r")
        except zipfile.BadZipFile as error:
            raise ValueError(f"not an Office package (unreadable zip): {self.path}") from error
        self.names = frozenset(self._zip.namelist())
        self._xml_cache: dict[str, ET.Element | None] = {}
        self._rels_cache: dict[str, dict[str, str]] = {}

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> PresentationPackage:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- parts -------------------------------------------------------------

    def xml(self, part_name: str) -> ET.Element | None:
        if part_name in self._xml_cache:
            return self._xml_cache[part_name]
        element: ET.Element | None = None
        if part_name in self.names:
            try:
                element = ET.fromstring(self._zip.read(part_name))
            except (ET.ParseError, KeyError):
                element = None
        self._xml_cache[part_name] = element
        return element

    def rels(self, part_name: str) -> dict[str, str]:
        """Relationship id -> absolute part name, resolved against the owner."""
        if part_name in self._rels_cache:
            return self._rels_cache[part_name]
        resolved: dict[str, str] = {}
        rels_root = self.xml(_rels_part_name(part_name))
        if rels_root is not None:
            for rel in rels_root:
                rel_id = str(rel.attrib.get("Id") or "").strip()
                target = str(rel.attrib.get("Target") or "").strip()
                mode = str(rel.attrib.get("TargetMode") or "").strip()
                if not rel_id or not target or mode == "External":
                    continue
                resolved[rel_id] = _resolve_target(part_name, target)
        self._rels_cache[part_name] = resolved
        return resolved

    # -- presentation structure -------------------------------------------

    def presentation(self) -> ET.Element | None:
        return self.xml(PRESENTATION_PART)

    def master_parts(self) -> list[str]:
        """Master part names in ``sldMasterIdLst`` order (presentation order).

        Falls back to numeric part order only when the list is unreadable; the
        fallback is reported as a warning by the snapshot builder.
        """
        presentation = self.presentation()
        ordered: list[str] = []
        if presentation is not None:
            rels = self.rels(PRESENTATION_PART)
            id_list = presentation.find(f"{{{NS_P}}}sldMasterIdLst")
            for entry in list(id_list) if id_list is not None else []:
                target = rels.get(str(entry.attrib.get(f"{{{NS_R}}}id") or ""))
                if target and target in self.names and target not in ordered:
                    ordered.append(target)
        if ordered:
            return ordered
        return self._sorted_parts(_MASTER_PATTERN)

    def theme_for_master(self, master_part: str) -> str | None:
        for target in self.rels(master_part).values():
            if target.startswith("ppt/theme/") and target in self.names:
                return target
        return None

    def layout_parts_for_master(self, master_part: str) -> list[str]:
        """Layout parts of a master, in the master's declared order."""
        rels = self.rels(master_part)
        master = self.xml(master_part)
        ordered: list[str] = []
        if master is not None:
            id_list = master.find(f"{{{NS_P}}}sldLayoutIdLst")
            for entry in list(id_list) if id_list is not None else []:
                target = rels.get(str(entry.attrib.get(f"{{{NS_R}}}id") or ""))
                if target and target in self.names and target not in ordered:
                    ordered.append(target)
        if ordered:
            return ordered
        return [
            target
            for target in sorted(rels.values())
            if _LAYOUT_PATTERN.match(target)
        ]

    def slide_parts(self) -> list[str]:
        return self._sorted_parts(_SLIDE_PATTERN)

    def all_layout_parts(self) -> list[str]:
        return self._sorted_parts(_LAYOUT_PATTERN)

    def media_parts(self, suffix: str) -> list[str]:
        return sorted(
            name
            for name in self.names
            if name.startswith("ppt/media/") and name.endswith(suffix)
        )

    def _sorted_parts(self, pattern: re.Pattern[str]) -> list[str]:
        matched: list[tuple[int, str]] = []
        for name in self.names:
            match = pattern.match(name)
            if match:
                matched.append((int(match.group(1)), name))
        return [name for _, name in sorted(matched)]


__all__ = [
    "PRESENTATION_PART",
    "PresentationPackage",
    "potx_bytes_to_pptx_bytes",
    "write_pptx_copy",
]
