"""The app's draw.io diagrams at the end of a changing phase: exported, checked against the code."""

from __future__ import annotations

import base64
import os
import subprocess
import time
import urllib.parse
import zlib
from pathlib import Path

import pytest

from octryx_claude import diagram_facts

CONFIG = {"enabled": True, "folder": "docs/diagrams", "images": "docs/images"}
NAVIGATION = """<mxfile><diagram id="n" name="Navigation"><mxGraphModel><root><mxCell id="0"/>
<mxCell id="1" parent="0"/>
<mxCell id="a" value="OnboardingPage" vertex="1" parent="1"><mxGeometry x="20" y="20" width="160" height="60"
as="geometry"/></mxCell>
<mxCell id="b" value="&lt;b&gt;Beans list&lt;/b&gt;&lt;br&gt;all packs" vertex="1" parent="1"><mxGeometry x="20" y="140"
width="160" height="60" as="geometry"/></mxCell>
<mxCell id="c" value="Settings" vertex="1" parent="1"><mxGeometry x="220" y="140" width="160" height="60"
as="geometry"/></mxCell>
<mxCell id="e" value="Skip" edge="1" parent="1" source="a" target="b"><mxGeometry relative="1" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""


def _app(tmp_path: Path) -> Path:
    app = tmp_path / "repo" / "coffee"
    (app / "lib/features/onboarding").mkdir(parents=True)
    (app / "lib/features/onboarding/onboarding_page.dart").write_text("class OnboardingPage {}\n")
    (app / "lib/features/beans/beans_list_page.dart").parent.mkdir(parents=True)
    (app / "lib/features/beans/beans_list_page.dart").write_text("class BeansListPage {}\n")
    (app / "docs/diagrams").mkdir(parents=True)
    (app / "docs/diagrams/navigation.drawio").write_text(NAVIGATION)
    (app / "README.md").write_text("# Coffee\n![Navigation](docs/images/navigation.png)\n")
    return tmp_path / "repo"


def test_labels_read_every_page_also_a_compressed_one(tmp_path):
    inner = '<mxGraphModel><root><mxCell id="x" value="BeanRepository" vertex="1"/></root></mxGraphModel>'
    packed = base64.b64encode(zlib.compress(urllib.parse.quote(inner).encode(), 9)[2:-4]).decode()
    path = tmp_path / "a.drawio"
    path.write_text(f'<mxfile><diagram id="d">{packed}</diagram></mxfile>')
    assert diagram_facts.labels(path) == ["BeanRepository"]
    path.write_text("<html>no diagram</html>")
    with pytest.raises(ValueError, match="no mxfile"):
        diagram_facts.labels(path)


def test_without_the_cli_the_png_is_missing_and_the_labels_are_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(diagram_facts, "drawio_cli", lambda: None)
    facts = diagram_facts.diagram_facts(_app(tmp_path), CONFIG)
    (item,) = facts["files"]
    assert facts["tool"] == "missing" and item["path"] == "coffee/docs/diagrams/navigation.drawio"
    assert (item["valid"], item["png_state"]) == (True, "missing_tool")
    assert item["png"] == "coffee/docs/images/navigation.png"
    assert item["unmatched"] == ["Settings"]  # "Beans list" is BeansListPage; an edge label is no box


def test_a_png_older_than_its_diagram_is_stale_and_invalid_xml_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(diagram_facts, "drawio_cli", lambda: None)
    root = _app(tmp_path)
    png = root / "coffee/docs/images/navigation.png"
    png.parent.mkdir(parents=True)
    png.write_bytes(b"\x89PNG")
    old = time.time() - 3600
    os.utime(png, (old, old))
    (root / "coffee/docs/diagrams/broken.drawio").write_text("<mxfile><diagram>")
    facts = diagram_facts.diagram_facts(root, CONFIG)
    broken, navigation = facts["files"]
    assert broken["valid"] is False and navigation["png_state"] == "stale" and navigation["referenced"] is True
    assert diagram_facts.diagram_facts(root, {**CONFIG, "enabled": False}) is None


@pytest.mark.skipif(diagram_facts.drawio_cli() is None, reason="needs the draw.io CLI")
def test_the_cli_exports_the_png_next_to_the_readme(tmp_path):
    root = _app(tmp_path)
    facts = diagram_facts.diagram_facts(root, CONFIG)
    (item,) = facts["files"]
    assert item["png_state"] == "exported" and item["referenced"] is True, item.get("error")
    assert (root / item["png"]).read_bytes()[:4] == b"\x89PNG"
    again = diagram_facts.diagram_facts(root, CONFIG)
    assert again["files"][0]["png_state"] == "current"  # nothing changed: no second export


def test_an_export_that_ends_without_its_png_is_tried_once_more(tmp_path, monkeypatch):
    """The draw.io CLI now and then ends without the PNG on a busy machine; the next attempt writes it."""
    calls = []

    def run(argv, **_kwargs):
        calls.append(argv)
        if len(calls) > 1:
            Path(argv[argv.index("-o") + 1]).write_bytes(b"\x89PNG")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(diagram_facts.subprocess, "run", run)
    target = tmp_path / "out" / "a.png"

    assert diagram_facts._export("drawio", tmp_path / "a.drawio", target) == ""
    assert len(calls) == 2 and target.read_bytes() == b"\x89PNG"


def test_an_export_that_fails_twice_reports_the_second_answer(tmp_path, monkeypatch):
    answers = iter(["first", "second"])
    monkeypatch.setattr(diagram_facts.subprocess, "run",
                        lambda argv, **_k: subprocess.CompletedProcess(argv, 1, "", next(answers)))

    assert diagram_facts._export("drawio", tmp_path / "a.drawio", tmp_path / "a.png") == "second"
