"""The local SeaweedFS object stores keep writable volumes for every collection.

With too few volume slots (``-volume.max``) the knowledge bucket takes all of them, the
default collection that the filer's metadata log writes to has no writable volume, and
S3 PUTs after an idle period stall until the client read timeout (knowledge object
writes report ``unavailable`` with ``ReadTimeoutError``). Each compose file must leave
room beyond the knowledge bucket's volumes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
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
