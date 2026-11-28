"""The app folder's structure from ast-grep: definitions, calls and imports per tracked file, no model."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .context_pack_languages import EXTENSIONS, rules

MAX_FILES = 8000
MAX_FILE_BYTES = 200_000
SCAN_TIMEOUT = 30.0
_LAST = re.compile(r"[A-Za-z_$][\w$]*$")


@dataclass
class Structure:
    files: list[str] = field(default_factory=list)
    definitions: list[tuple[str, str, int, int]] = field(default_factory=list)  # file, name, first, last line
    calls: list[tuple[str, int, str]] = field(default_factory=list)  # file, line, callee's last name
    imports: list[tuple[str, str]] = field(default_factory=list)  # file, the import's text
    cut: bool = False

    # The cache stores a file as its index in ``files``: a large app's facts stay a few MB.
    def to_json(self) -> dict[str, object]:
        index = {name: number for number, name in enumerate(self.files)}
        return {"files": self.files, "cut": self.cut,
                "definitions": [(index[file], *rest) for file, *rest in self.definitions],
                "calls": [(index[file], *rest) for file, *rest in self.calls],
                "imports": [(index[file], *rest) for file, *rest in self.imports]}

    @classmethod
    def from_json(cls, data: dict[str, object]) -> Structure:
        files = [str(name) for name in data.get("files") or []]

        def rows(key: str) -> list[tuple]:
            return [(files[item[0]], *item[1:]) for item in data.get(key) or []]

        return cls(files, rows("definitions"), rows("calls"), rows("imports"), bool(data.get("cut")))


def ast_grep() -> str | None:
    from . import tools
    from .tools_data import TOOLS

    tool = next((item for item in TOOLS if item["id"] == "ast-grep"), None)
    try:
        root = tools.default_root()
        if tool is not None and tools._version_of(tool, root) is not None:
            return tools._executable(tool, root)
    except Exception:  # noqa: BLE001 - outside a launcher install the PATH's ast-grep is used
        pass
    return shutil.which("ast-grep")


def _readable(root: Path, files: list[str]) -> list[str]:
    kept = []
    for name in files:
        try:
            if PurePosixPath(name).suffix.lower() in EXTENSIONS and (root / name).stat().st_size <= MAX_FILE_BYTES:
                kept.append(name)
        except OSError:
            continue
    return kept


def _callee(text: str) -> str:
    found = _LAST.search(text.strip())
    return found.group(0) if found else ""


def _add(structure: Structure, match: dict[str, object], tracked: set[str]) -> None:
    name = str(match.get("file") or "")
    if name not in tracked:
        return
    rule = str(match.get("ruleId") or "")
    span = dict(match.get("range") or {})
    first = int(dict(span.get("start") or {}).get("line", 0)) + 1
    last = int(dict(span.get("end") or {}).get("line", 0)) + 1
    values = {key: str(dict(value).get("text") or "")
              for key, value in dict(dict(match.get("metaVariables") or {}).get("single") or {}).items()}
    if rule.startswith("def:") and values.get("NAME"):
        structure.definitions.append((name, values["NAME"], first, last))
    elif rule.startswith("call:") and _callee(values.get("CALLEE", "")):
        structure.calls.append((name, first, _callee(values["CALLEE"])))
    elif rule.startswith("import:"):
        structure.imports.append((name, " ".join(str(match.get("text") or "").split())[:200]))


def read_structure(root: str, files: list[str]) -> Structure:
    base = Path(root)
    readable = _readable(base, files)
    structure = Structure(files=list(files), cut=len(readable) > MAX_FILES)
    readable = readable[:MAX_FILES]
    executable = ast_grep()
    languages = {EXTENSIONS[PurePosixPath(name).suffix.lower()] for name in readable}
    if executable is None or not readable:
        return structure
    try:
        out = subprocess.run([executable, "scan", "--inline-rules", rules(languages), "--json=stream", *readable],
                             cwd=base, capture_output=True, timeout=SCAN_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        structure.cut = True
        return structure
    tracked = set(readable)
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        try:
            _add(structure, json.loads(line), tracked)
        except (ValueError, TypeError, AttributeError):
            continue
    return _lean(structure)


# Kept: calls to names the app defines and the imports of test files, the only ones the pack follows.
def _lean(structure: Structure) -> Structure:
    from .context_pack_match import is_test

    defined = {name for _file, name, _first, _last in structure.definitions}
    structure.calls = [call for call in structure.calls if call[2] in defined]
    structure.imports = [item for item in structure.imports if is_test(item[0])]
    return structure


__all__ = ["Structure", "ast_grep", "read_structure"]
