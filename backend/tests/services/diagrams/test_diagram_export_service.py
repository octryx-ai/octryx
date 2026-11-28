"""Tests for the drawio CLI PNG export service."""

from __future__ import annotations

import shutil
import stat
from pathlib import Path

import pytest

from app.services import diagram_export_service as export_service
from app.services.diagram_export_service import (
    DIAGRAM_PNG_CACHE_DIR_ENV,
    DRAWIO_BIN_ENV,
    DiagramRenderError,
    DiagramRendererUnavailableError,
    render_diagram_png,
    renderer_available,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

VALID_XML = (
    '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    '<mxCell id="2" value="Hello" style="rounded=1;" vertex="1" parent="1">'
    '<mxGeometry x="40" y="40" width="120" height="60" as="geometry"/>'
    "</mxCell></root></mxGraphModel>"
)

_FAKE_DRAWIO = """#!/usr/bin/env python3
import os
import sys

args = sys.argv[1:]
out = args[args.index("-o") + 1]
source = args[-1]
data = open(source, "rb").read()
counter = os.environ.get("FAKE_DRAWIO_COUNT_FILE")
if counter:
    with open(counter, "a") as handle:
        handle.write("x")
if b"FAIL_ME" in data:
    sys.stderr.write("Error: Export failed: " + source + "\\n")
    sys.exit(1)
with open(out, "wb") as handle:
    handle.write(b"\\x89PNG\\r\\n\\x1a\\n" + b"fake-png-body")
"""


@pytest.fixture
def fake_drawio(tmp_path, monkeypatch) -> Path:
    binary = tmp_path / "fake-drawio"
    binary.write_text(_FAKE_DRAWIO, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    counter = tmp_path / "invocations"
    monkeypatch.setenv(DRAWIO_BIN_ENV, str(binary))
    monkeypatch.setenv(DIAGRAM_PNG_CACHE_DIR_ENV, str(tmp_path / "png-cache"))
    monkeypatch.setenv("FAKE_DRAWIO_COUNT_FILE", str(counter))
    return counter


def _invocations(counter: Path) -> int:
    return len(counter.read_text(encoding="utf-8")) if counter.exists() else 0


def test_render_produces_png_and_serves_second_call_from_cache(fake_drawio):
    first = render_diagram_png(diagram_id="diag-1", diagram_xml=VALID_XML, scale=2)
    assert first.startswith(PNG_MAGIC)
    assert _invocations(fake_drawio) == 1

    second = render_diagram_png(diagram_id="diag-1", diagram_xml=VALID_XML, scale=2)
    assert second == first
    assert _invocations(fake_drawio) == 1  # cache hit, no second CLI run


def test_scale_is_part_of_the_cache_key(fake_drawio):
    render_diagram_png(diagram_id="diag-1", diagram_xml=VALID_XML, scale=1)
    render_diagram_png(diagram_id="diag-1", diagram_xml=VALID_XML, scale=2)
    assert _invocations(fake_drawio) == 2


def test_missing_binary_is_explicit_renderer_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv(DRAWIO_BIN_ENV, str(tmp_path / "missing-drawio"))
    monkeypatch.setenv(DIAGRAM_PNG_CACHE_DIR_ENV, str(tmp_path / "png-cache"))
    assert renderer_available() is False
    with pytest.raises(DiagramRendererUnavailableError, match="renderer_unavailable"):
        render_diagram_png(diagram_id="diag-1", diagram_xml=VALID_XML)


def test_cli_failure_raises_render_error(fake_drawio):
    with pytest.raises(DiagramRenderError, match="^drawio_export_failed exit_code=1$"):
        render_diagram_png(diagram_id="diag-bad", diagram_xml="<mxGraphModel>FAIL_ME</mxGraphModel>")


def test_xml_without_model_document_is_rejected(fake_drawio):
    with pytest.raises(DiagramRenderError, match="mxGraphModel"):
        render_diagram_png(diagram_id="diag-bad", diagram_xml="<svg>not drawio</svg>")
    assert _invocations(fake_drawio) == 0  # rejected before the CLI runs


def test_unsupported_scale_is_rejected(fake_drawio):
    with pytest.raises(DiagramRenderError, match="scale"):
        render_diagram_png(diagram_id="diag-1", diagram_xml=VALID_XML, scale=4)


def test_cache_is_bounded_lru(fake_drawio, tmp_path, monkeypatch):
    monkeypatch.setattr(export_service, "_CACHE_MAX_FILES", 2)
    for index in range(4):
        render_diagram_png(diagram_id=f"diag-{index}", diagram_xml=VALID_XML + f"<!--{index}-->")
    cached = list((tmp_path / "png-cache").glob("*.png"))
    assert len(cached) == 2


@pytest.mark.skipif(shutil.which("drawio") is None, reason="real drawio CLI not installed")
def test_real_drawio_binary_renders_png(tmp_path, monkeypatch):
    # The test checks rendering, not the timeout: a loaded gate machine can need more than the product's 60 s.
    monkeypatch.setattr(export_service, "RENDER_TIMEOUT_SECONDS", 300)
    monkeypatch.delenv(DRAWIO_BIN_ENV, raising=False)
    monkeypatch.setenv(DIAGRAM_PNG_CACHE_DIR_ENV, str(tmp_path / "png-cache"))
    png = render_diagram_png(diagram_id="diag-real", diagram_xml=VALID_XML, scale=1)
    assert png.startswith(PNG_MAGIC)
    assert len(png) > 500
