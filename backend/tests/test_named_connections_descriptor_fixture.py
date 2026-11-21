"""The frontend's descriptor fixture is generated from the server's descriptors and never drifts.

``frontend/chat/tests/unit/namedConnectorDescriptors.mjs`` is what the UI tests render connector cards from;
``scripts/generate_named_connector_descriptors.py`` writes it from ``list_descriptors()`` (the panel API's
payload). A descriptor change without a regenerated fixture fails here.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.services.admin.project.named_connection_view import list_descriptors

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_named_connector_descriptors.py"


def _script():
    spec = importlib.util.spec_from_file_location("generate_named_connector_descriptors", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_fixture_matches_the_server_descriptors() -> None:
    assert _script().main(["--check"]) == 0, "rerun backend/scripts/generate_named_connector_descriptors.py"


def test_the_fixture_is_exactly_the_panel_payload_and_a_drift_is_caught(tmp_path, monkeypatch) -> None:
    script = _script()
    text = script.render()
    body = text.split("export const DESCRIPTORS = ", 1)[1].split(";\n", 1)[0]
    assert list(json.loads(body).values()) == list_descriptors()["connectors"]

    fixture = tmp_path / "namedConnectorDescriptors.mjs"
    monkeypatch.setattr(script, "FIXTURE", fixture)
    fixture.write_text(text.replace('"testable": true', '"testable": false', 1), encoding="utf-8")
    assert script.main(["--check"]) == 1
    assert script.main([]) == 0 and fixture.read_text(encoding="utf-8") == text
    assert script.main(["--check"]) == 0
