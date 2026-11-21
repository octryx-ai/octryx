"""The line length: the launcher reports only the long lines a change adds."""

from __future__ import annotations

import subprocess
from pathlib import Path

from octryx_claude.contract_sizes import LONG_LINE_MARKER, line_floor, sizes


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c",
                           "commit.gpgsign=false", *args], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


def test_only_added_lines_longer_than_the_smallest_limit_are_reported(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    existing = "x = '" + "a" * 300 + "'\n"
    (root / "src/old.py").write_text(f"short = 1\n{existing}")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    base = _git(root, "rev-parse", "HEAD")
    (root / "src/old.py").write_text(f"short = 1\n{existing}y = '" + "b" * 200 + "'\n")
    (root / "src/style.css").write_text("a{" + "color:red;" * 497 + "}\n")  # one 4,974-character line
    url = f"# https://example.invalid/{'p' * 200}  # {LONG_LINE_MARKER}\n"
    (root / "src/new.py").write_text(url + "ok = 1\n")
    found = sizes(root, base, 160)["long_lines"]
    assert ["src/style.css", 1, 4973] in found
    assert ["src/old.py", 3, 206] in found  # the added line, never the long line the file had before
    assert not any(entry[0] == "src/old.py" and entry[1] == 2 for entry in found)
    assert not any(entry[0] == "src/new.py" for entry in found)  # marked: a URL that cannot be wrapped
    assert "long_lines" not in sizes(root, base, 0)


def test_the_floor_is_the_smallest_limit_of_the_style():
    style = {"general": {"max_line_length": 160}, "languages": {"python": {"max_line_length": 120},
                                                                "dart": {"max_line_length": 0}}}
    assert line_floor(style) == 120 and line_floor({"general": {}}) == 0 and line_floor(None) == 0
