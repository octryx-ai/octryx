"""The local SeaweedFS object stores keep writable volumes for every collection; with too few slots the
filer's metadata log has no writable volume and S3 PUTs stall after idle periods."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILES = (
    ROOT / "docker-compose.yml",
    ROOT / "deployment" / "local" / "object-store" / "compose.yaml",
)
MINIMUM_SLOTS = 8


@pytest.mark.parametrize("compose_file", COMPOSE_FILES, ids=lambda path: path.name)
def test_object_store_has_volume_slots_beyond_the_knowledge_bucket(compose_file: Path) -> None:
    values = re.findall(r"^\s*-\s*-volume\.max=(\d+)\s*$", compose_file.read_text(encoding="utf-8"), re.M)
    assert len(values) == 1, f"exactly one -volume.max in {compose_file}"
    assert int(values[0]) >= MINIMUM_SLOTS
