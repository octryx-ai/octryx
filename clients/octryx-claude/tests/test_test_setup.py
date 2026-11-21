"""The Stop hook tells the gate whether the session's folder has tests at all."""

from __future__ import annotations

import json

from octryx_claude.test_setup import has_test_setup


def test_finds_the_common_test_setups(tmp_path):
    home = tmp_path / "home"
    cases = {
        "py": ("pyproject.toml", "[tool.pytest.ini_options]\n"),
        "conftest": ("conftest.py", ""),
        "node": ("package.json", json.dumps({"scripts": {"test": "vitest run"}})),
        "java": ("pom.xml", "<project/>"),
        "go": ("go.mod", "module x"),
        "make": ("Makefile", "build:\n\ttrue\ntest:\n\tgo test ./...\n"),
    }
    for name, (marker, content) in cases.items():
        repo = home / name
        (repo / "src" / "deep").mkdir(parents=True)
        (repo / ".git").mkdir()
        (repo / marker).write_text(content)
        assert has_test_setup(str(repo / "src" / "deep"), home=home) is True, name


def test_no_test_setup_in_notes_folders_and_npm_default(tmp_path):
    home = tmp_path / "home"
    notes = home / "Documents" / "Notes"
    notes.mkdir(parents=True)
    (notes / "test.txt").write_text("hello world")
    assert has_test_setup(str(notes), home=home) is False
    repo = home / "web"
    (repo / ".git").mkdir(parents=True)
    (repo / "package.json").write_text(json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}))
    assert has_test_setup(str(repo), home=home) is False
    assert has_test_setup(str(home), home=home) is False
    assert has_test_setup("relative/path", home=home) is None
    assert has_test_setup(str(home / "missing"), home=home) is None
