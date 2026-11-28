"""Three structurally different templates for the generic-detection proof tests."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from tests.support.office_template_fixture import write_template

TEMPLATE_NAMES = ("brand", "default", "neutral")

_HOLDER = re.compile(rb'<p:sp><p:nvSpPr><p:cNvPr id="\d+" name="Icon Holder \d+"/>.*?</p:sp>')


def write_named_template(directory: Path, name: str) -> Path:
    if name == "default":
        from pptx import Presentation

        path = directory / "default.pptx"
        Presentation().save(str(path))
        return path
    if name == "neutral-plain":
        source = write_template(directory / "neutral-source.potx", "neutral")
        path = directory / "neutral-plain.potx"
        with zipfile.ZipFile(source) as src, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename.startswith("ppt/slideLayouts/slideLayout") and item.filename.endswith(".xml"):
                    data = _HOLDER.sub(b"", data)
                out.writestr(item, data)
        return path
    return write_template(directory / f"{name}.potx", name)


def layout_of_shape(snapshot: dict, shape: str) -> list[dict]:
    return [layout for layout in snapshot["layouts"] if layout["content_shape"] == shape]


__all__ = ["TEMPLATE_NAMES", "layout_of_shape", "write_named_template"]
