"""Shared helpers for the test_office_identity_template_snapshot_* modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.office_identity.template_snapshot import build_template_snapshot
from tests.office_template_fixture import write_template


@pytest.fixture(scope="module")
def brand_template(tmp_path_factory) -> Path:
    return write_template(tmp_path_factory.mktemp("brand") / "brand.potx", "brand")


@pytest.fixture(scope="module")
def brand_snapshot(brand_template) -> dict:
    return build_template_snapshot(brand_template)
