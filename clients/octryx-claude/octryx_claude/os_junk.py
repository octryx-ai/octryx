"""Operating-system files (``.DS_Store``, ``Thumbs.db``, ...) never enter a tree or patch built from a working
copy."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

DATA = Path(__file__).with_name("os_junk.json")


@cache
def _data() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


@cache
def excludes() -> tuple[str, ...]:
    data = _data()
    files = tuple(f":(exclude,glob)**/{name}" for name in data["files"])
    folders = tuple(f":(exclude,glob)**/{name}/**" for name in data["folders"])
    return files + folders


def add_all() -> tuple[str, ...]:
    return ("add", "-A", "--", ".", *excludes())


__all__ = ["DATA", "add_all", "excludes"]
