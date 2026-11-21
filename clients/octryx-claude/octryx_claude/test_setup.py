"""Does the session's folder have tests at all?

The platform's "done means verified" gate asks for a green test run after a code change. In a folder with no test
setup (a notes folder, a scripts folder without tests) that request can only make the model fumble: it invents a
throwaway test or fails to install a runner. So the Stop hook tells the platform what it found here
(``test_setup``: ``True`` / ``False``), from the session's folder up to the repository root (never above the home
folder):

- Python: ``pytest.ini``, ``conftest.py``, ``tox.ini``, ``noxfile.py``, a ``[tool.pytest`` / ``pytest`` mention in
  ``pyproject.toml`` or ``setup.cfg``;
- JavaScript/TypeScript: ``package.json`` with a real ``test`` script (not npm's "no test specified"), a vitest or
  jest config;
- JVM: ``pom.xml``, ``build.gradle(.kts)``; Go: ``go.mod``; Rust: ``Cargo.toml``; .NET: a ``*.csproj``; Ruby: a
  ``spec`` folder with a ``Gemfile``;
- a ``Makefile`` with a ``test:`` target; a ``tests`` or ``test`` folder next to code.

Detection only reads names and small files; it never runs anything. Unsure is ``None`` (the platform then decides).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

MAX_LEVELS = 8
MAX_READ_BYTES = 256 * 1024
_FILES = ("pytest.ini", "conftest.py", "tox.ini", "noxfile.py", "pom.xml", "build.gradle", "build.gradle.kts",
          "go.mod", "Cargo.toml", "vitest.config.ts", "vitest.config.js", "vitest.config.mts", "jest.config.js",
          "jest.config.ts", "jest.config.cjs", "jest.config.mjs")
_NO_TEST = re.compile(r"no test specified", re.I)
_MAKE_TEST = re.compile(r"^test\s*:", re.M)


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_READ_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _folder_has_tests(folder: Path) -> bool:
    if any((folder / name).is_file() for name in _FILES):
        return True
    for name in ("pyproject.toml", "setup.cfg"):
        if "pytest" in _read(folder / name):
            return True
    package = folder / "package.json"
    if package.is_file():
        try:
            script = str(((json.loads(_read(package)) or {}).get("scripts") or {}).get("test") or "")
        except (ValueError, AttributeError):
            script = ""
        if script and not _NO_TEST.search(script):
            return True
    if _MAKE_TEST.search(_read(folder / "Makefile")):
        return True
    if (folder / "Gemfile").is_file() and (folder / "spec").is_dir():
        return True
    try:
        if any(path.suffix == ".csproj" for path in folder.iterdir()):
            return True
    except OSError:
        pass
    return any((folder / name).is_dir() for name in ("tests", "test"))


def has_test_setup(cwd: str, *, home: Path | None = None) -> bool | None:
    """``True``/``False`` for the session's folder and its parents up to the repository root; ``None`` if unsure."""
    if not cwd or not cwd.startswith("/"):
        return None
    try:
        folder = Path(cwd).resolve()
        home = (home or Path.home()).resolve()
    except (OSError, RuntimeError):
        return None
    if not folder.is_dir():
        return None
    for _ in range(MAX_LEVELS):
        if folder == home or folder == folder.parent:
            return False
        if _folder_has_tests(folder):
            return True
        if (folder / ".git").exists():
            return False  # the repository root without a test setup
        folder = folder.parent
    return False


__all__ = ["has_test_setup"]
