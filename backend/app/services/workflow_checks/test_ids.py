"""One canonical test id across the platform. Pure.

The canonical id is pytest's node id: ``path/to/test_file.py::Class::Nested::test_name[param]`` — the test file as
a POSIX path relative to the test runner's root, the class chain, then the test with its parametrize id. Every
producer converts to it (``submit_test_contract``, the confirmation, chat, octryx-claude's device/terminal reports,
CI) and every gate compares only canonical ids. A selector selects the tests under it: a file
(``tests/test_x.py``), a class (``tests/test_x.py::TestA``), a parametrized test without its parameter
(``tests/test_x.py::test_y`` selects ``tests/test_x.py::test_y[1]``) or a directory (``tests/``).

Dotted names (JUnit ``classname``, unittest, Jenkins ``className``) name a module, not a file:
``tests.test_x.TestA`` is ``tests/test_x.py::TestA`` only if that file exists. The :class:`Resolver` answers from
the files it knows — the repository tree when the platform holds the working copy, plus the files the confirmed
tests, the contract and earlier runs name and the files the launcher found for a report. Exactly one candidate
file resolves the name; none or several leave it **unresolved** with the reason. Nothing is matched silently: an
unresolved result never selects a confirmed test (``test_results.evidence_unresolved``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

TEST_FILE_SUFFIXES = frozenset({".py", ".go", ".java", ".kt", ".kts", ".scala", ".ts", ".tsx", ".js", ".jsx", ".mjs",
                                ".rb", ".cs", ".php", ".rs", ".swift", ".dart"})
MAX_ID_CHARS = 500
_DOTTED = re.compile(r"^[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*$")


def normalize(raw: object) -> str:
    """The id with its path written canonically (``./``, backslashes, doubled slashes, pytest's old ``::()``)."""
    text = str(raw or "").strip()[:MAX_ID_CHARS]
    if not text:
        return ""
    head, sep, tail = text.partition("::")
    head = head.replace("\\", "/")
    while head.startswith("./"):
        head = head[2:]
    head = re.sub(r"/{2,}", "/", head)
    parts = [part for part in tail.split("::") if part not in ("", "()")] if sep else []
    return "::".join([head, *parts]) if parts else head


def file_of(test_id: str) -> str | None:
    """The test file a canonical id names, else ``None`` (a dotted name, a bare function, a directory)."""
    head = str(test_id or "").split("::", 1)[0]
    return head if PurePosixPath(head).suffix in TEST_FILE_SUFFIXES else None


def is_canonical(test_id: str) -> bool:
    """A relative path inside the repository: a test file (with its class/test chain) or a directory ``dir/``."""
    head = str(test_id or "").split("::", 1)[0]
    if not head or head.startswith("/") or re.match(r"^[A-Za-z]:", head) or ".." in head.split("/"):
        return False
    return file_of(test_id) is not None or (head.endswith("/") and "::" not in test_id)


def selects(selector: str, test_id: str) -> bool:
    """Whether the canonical ``selector`` (a test, class, file, directory) selects the canonical ``test_id``."""
    if test_id == selector:
        return True
    if selector.endswith("/"):
        return test_id.startswith(selector)
    if _dart_named(selector, test_id):
        return True
    return test_id.startswith(selector + "::") or ("[" not in selector and test_id.startswith(selector + "["))


def _dart_named(selector: str, test_id: str) -> bool:
    """A Dart test is reported by its full name, its groups and its own name joined by spaces
    (``test/x_test.dart::Grind starts at 15``); a selector may name the test without its groups."""
    file, _, name = selector.partition("::")
    return (file.endswith(".dart") and bool(name) and "::" not in name
            and test_id.startswith(file + "::") and test_id.endswith(" " + name))


def covers(result_id: str, selector: str) -> bool:
    """Whether a file- or class-level result (a collection error) covers every test the ``selector`` names."""
    return selector.startswith(result_id + "::")


def module_path(dotted: str) -> str:
    """``tests.test_x`` → ``tests/test_x.py`` (only the spelling; :class:`Resolver` decides whether it exists)."""
    return dotted.replace(".", "/") + ".py"


class Resolver:
    """Resolves dotted names to canonical ids against the files it knows (``files``) and the working copy
    (``root``, when the platform holds it). Deterministic; ambiguity is reported, never decided."""

    def __init__(self, files: Iterable[str] = (), root: Path | str | None = None) -> None:
        self.files = {file for item in files if (file := file_of(normalize(item)))}
        self.root = Path(root).resolve() if root else None

    def exists(self, relative: str) -> bool:
        if relative in self.files:
            return True
        if self.root is None:
            return False
        path = (self.root / relative).resolve()
        return path.is_relative_to(self.root) and path.is_file()

    def _candidates(self, parts: list[str]) -> list[tuple[str, list[str]]]:
        return [(path, parts[index:]) for index in range(len(parts), 0, -1)
                if self.exists(path := module_path(".".join(parts[:index])))]

    def resolve(self, classname: str, name: str = "", file: str = "") -> tuple[str | None, str]:
        """``(canonical id, "")`` or ``(None, why)`` for a test reported as ``classname`` + ``name``.

        ``file`` (JUnit's ``file`` attribute) names the module directly; the class chain is what the classname
        adds after the module. Without it the module is the one existing file the classname's prefix spells."""
        classname, name = str(classname or "").strip(), str(name or "").strip()
        if file:
            path = normalize(file)
            if not file_of(path):
                return None, f"'{file}' is not a test file"
            module = path.removesuffix(PurePosixPath(path).suffix).replace("/", ".")
            if not path.endswith(".py"):
                # Another runner's classname is no module path (node's JUnit says "test"): the file names the test.
                return "::".join([path, *([name] if name else [])]), ""
            if classname and classname != module and not classname.startswith(module + "."):
                return None, f"classname '{classname}' does not belong to file '{path}'"
            chain = classname[len(module) + 1:].split(".") if classname.startswith(module + ".") else []
            return "::".join([path, *[part for part in chain if part], *([name] if name else [])]), ""
        if not classname:
            # pytest reports a module that failed to collect as a testcase without classname, named by its module.
            return self.module(name)
        if not _DOTTED.match(classname):
            return None, f"'{classname}' is not a module path"
        candidates = self._candidates(classname.split("."))
        if not candidates:
            return None, f"no test file for '{classname}' ({module_path(classname)} or a parent module)"
        if len(candidates) > 1:
            return None, f"'{classname}' is ambiguous: {', '.join(path for path, _chain in candidates)}"
        path, chain = candidates[0]
        return "::".join([path, *chain, *([name] if name else [])]), ""

    def module(self, dotted: str) -> tuple[str | None, str]:
        """The test file a dotted module name spells (a collection error names only its module)."""
        dotted = str(dotted or "").strip()
        if file_of(normalize(dotted)):
            return normalize(dotted), ""
        if not _DOTTED.match(dotted):
            return None, f"'{dotted}' is not a module path"
        path = module_path(dotted)
        return (path, "") if self.exists(path) else (None, f"no test file {path}")

    def selector(self, raw: object) -> tuple[str | None, str]:
        """A submitted test id as a canonical selector, or why it cannot be one (the submitter fixes it)."""
        test_id = normalize(raw)
        if not test_id:
            return None, "empty test id"
        if is_canonical(test_id):
            return test_id, ""
        head = test_id.split("::", 1)[0]
        if "::" not in test_id and _DOTTED.match(head) and "." in head:
            resolved, why = self.resolve(".".join(head.split(".")[:-1]), head.split(".")[-1])
            if resolved:
                return resolved, ""
            module, _ = self.module(head)
            if module:
                return module, ""
            return None, (f"{test_id} is not a test id: name it as the test runner's node id "
                          f"(path/to/test_file.py::Class::test) — {why}")
        return None, f"{test_id} is not a test id: name its file (path/to/test_file.py::Class::test)"


__all__ = ["MAX_ID_CHARS", "Resolver", "TEST_FILE_SUFFIXES", "covers", "file_of", "is_canonical", "module_path",
           "normalize", "selects"]
