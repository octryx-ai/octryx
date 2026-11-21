"""Shared helpers for the test_office_identity_slide_gate_* modules."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Any

import pytest

from app.services.office_identity.template_snapshot import build_template_snapshot
from tests.office_template_fixture import write_template


def _write_png(path: Path, *, width: int, height: int) -> Path:
    """Minimal single-colour PNG, written without an image dependency."""
    raw = b"".join(b"\x00" + bytes([0x40, 0x00, 0x66] * width) for _ in range(height))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return path


def _codes(findings: list[dict[str, Any]]) -> list[str]:
    return [finding["code"] for finding in findings]


# ---------------------------------------------------------------------------
# picture_covers_title + layout preference (synthetic corporate template from
# ``tests.office_template_fixture``)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def brand_template(tmp_path_factory) -> Path:
    return write_template(tmp_path_factory.mktemp("brand") / "brand.potx", "brand")


@pytest.fixture(scope="module")
def brand_snapshot(brand_template) -> dict[str, Any]:
    return build_template_snapshot(brand_template)


@pytest.fixture(scope="module")
def diagram_png(tmp_path_factory) -> Path:
    return _write_png(tmp_path_factory.mktemp("diagram") / "topology.png", width=800, height=450)
