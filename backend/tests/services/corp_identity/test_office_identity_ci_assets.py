"""CI assets (logos, images, the SVG icon catalog) are extracted with servable paths, and manual overrides
layer over the extracted identity while keeping it visible."""

import struct
import zlib
from pathlib import Path

from docx import Document

from app.services.corp_identity.ci_assets import extract_ci_assets


def _png(path: Path) -> Path:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * 4 for _ in range(4))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def _docx_with_header_logo(path: Path, tmp_path: Path) -> Path:
    doc = Document()
    logo = _png(tmp_path / "logo.png")
    doc.sections[0].header.paragraphs[0].add_run().add_picture(str(logo))
    doc.add_paragraph("body")
    doc.save(str(path))
    return path


def test_header_image_is_extracted_as_a_logo(tmp_path):
    template = _docx_with_header_logo(tmp_path / "brand.docx", tmp_path)
    root = tmp_path / "profile"
    root.mkdir()

    assets = extract_ci_assets(root, document_paths=[str(template)])

    assert assets["counts"]["logos"] == 1
    logo = assets["logos"][0]
    assert logo["kind"] == "logo"
    assert logo["medium"] == "document"
    # The asset was copied into the profile with a stable, relative path.
    copied = root / logo["path"]
    assert copied.is_file()
    assert logo["path"].startswith("ci-assets/documents/")


def test_icon_catalog_becomes_icon_assets():
    catalog = {
        "categories": {
            "General": [
                {"name": "Cloud", "slug": "cloud", "named_path": "icons/general/cloud.svg"},
                {"name": "Lock", "slug": "lock", "named_path": "icons/general/lock.svg"},
            ]
        }
    }
    assets = extract_ci_assets(Path("/tmp/nope"), icon_catalog=catalog)

    assert assets["counts"]["icons"] == 2
    assert {a["name"] for a in assets["icons"]} == {"Cloud", "Lock"}
    assert all(a["kind"] == "icon" and a["format"] == "svg" for a in assets["icons"])


def test_unreadable_template_is_skipped_not_fatal(tmp_path):
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a zip")
    root = tmp_path / "profile"
    root.mkdir()

    assets = extract_ci_assets(root, document_paths=[str(broken)])

    assert assets["counts"]["logos"] == 0
    assert assets["counts"]["images"] == 0
