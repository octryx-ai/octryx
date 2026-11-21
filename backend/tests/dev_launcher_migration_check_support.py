"""The sandbox fixture shared by the dev launcher migration check tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.dev_launcher_migration_support import Sandbox


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)
