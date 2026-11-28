"""Shared helpers for the test_office_identity_template_normalization_* modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.office_identity.template_normalization import normalize_template
from app.services.office_identity.template_snapshot import slots_by_role

DERIVED_KEY = "diagram-full-generated"


@pytest.fixture(scope="module")
def default_template(tmp_path_factory) -> Path:
    from pptx import Presentation

    path = tmp_path_factory.mktemp("normalization-source") / "default.pptx"
    Presentation().save(str(path))
    return path


@pytest.fixture(scope="module")
def normalized_default(tmp_path_factory, default_template) -> dict[str, Any]:
    output = tmp_path_factory.mktemp("normalization-output") / "normalized.pptx"
    return normalize_template(default_template, output)


def _picture_slot(layout: dict[str, Any]) -> dict[str, Any]:
    slots = slots_by_role(layout, "picture")
    assert slots, f"derived layout {layout.get('key')} has no picture slot"
    return slots[0]
