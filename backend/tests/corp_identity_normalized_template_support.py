"""Shared template builders and profile fixtures for the normalised template tests."""

from __future__ import annotations

from pathlib import Path

import pytest

DERIVED_KEY = "diagram-full-generated"


def _default_template(path: Path, tag: str = "") -> Path:
    """python-pptx's default template, optionally made content-unique.

    Uploads are de-duplicated by content digest, so two tests uploading the
    byte-identical default template would share one profile. ``tag`` writes a
    core property to keep them apart without changing anything normalisation
    looks at.
    """
    from pptx import Presentation

    presentation = Presentation()
    if tag:
        presentation.core_properties.title = tag
    presentation.save(str(path))
    return path


def _variant_template(path: Path) -> Path:
    """A different, still valid template — stands in for an edited original."""
    from pptx import Presentation

    presentation = Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[0])
    presentation.save(str(path))
    return path


@pytest.fixture
def profile_root(tmp_path: Path) -> Path:
    root = tmp_path / "profile"
    root.mkdir()
    return root


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return _default_template(tmp_path / "template.pptx")
