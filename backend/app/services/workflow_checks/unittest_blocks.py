"""unittest's ``FAIL:`` / ``ERROR:`` blocks as tests, and its dotted test ids next to pytest's paths.

A plain `python3 -m unittest` (no ``-v``) prints only
``F.`` and a ``FAIL: test_x (tests.test_pricing.PricingTest)`` block; no line per test, so without these blocks the
run has no failing test and the reproduction confirmation offers no "Confirm".
A block is a failed (``FAIL``) or erroring (``ERROR``)
test of its own; its traceback names the test file (``File ".../app/tests/test_pricing.py", line 8``), which
gives the file relative to where unittest ran (``tests/test_pricing.py``), as other runners report from the app
folder. :func:`path_form` writes a dotted id the way pytest does, so the two forms compare
(``tests.test_pricing.PricingTest.test_x`` ⇔ ``tests/test_pricing.py::PricingTest::test_x``).
"""

from __future__ import annotations

import re
import shlex

_BLOCK = re.compile(r"^(?P<kind>FAIL|ERROR): (?P<name>[A-Za-z_][\w.]*) \((?P<where>[A-Za-z_][\w.]*)\)$")
_FILE = re.compile(r'^\s*File "(?P<path>[^"]+\.py)", line \d+')


def blocks(lines: list[str]) -> list[dict[str, str]]:
    """Each block's ``kind``, ``name``, ``where`` (as printed) and ``path`` (the traceback's test file, else "")."""
    found: list[dict[str, str]] = []
    for line in lines:
        if header := _BLOCK.match(line):
            found.append({"kind": header["kind"], "name": header["name"], "where": header["where"], "path": ""})
        elif found and (file := _FILE.match(line)) and not found[-1]["path"]:
            path = file["path"].replace("\\", "/")
            if "/site-packages/" not in path and "/lib/python" not in path:
                found[-1]["path"] = path  # the first frame outside the library: the test's own file
    return found


def file_for(classname: str, path: str) -> str:
    """The test file of ``classname`` relative to where unittest ran: the longest module prefix whose spelling ends
    the traceback's path (``tests.test_pricing.PricingTest`` + ``/x/demo-shop/tests/test_pricing.py`` →
    ``tests/test_pricing.py``); ``""`` when none does."""
    parts = classname.split(".")
    for index in range(len(parts), 0, -1):
        relative = "/".join(parts[:index]) + ".py"
        if path == relative or path.endswith("/" + relative):
            return relative
    return ""


def path_form(test_id: str) -> str:
    """A dotted unittest id the way pytest writes it: the module up to the first CapWords part (a class), then the
    class chain and the test (``tests.test_pricing.PricingTest.test_x`` → ``tests/test_pricing.py::PricingTest::
    test_x``). An id that has ``::`` or no class stays as it is."""
    if "::" in test_id or "/" in test_id or "." not in test_id:
        return test_id
    parts = test_id.split(".")
    first_class = next((index for index, part in enumerate(parts) if part[:1].isupper()), None)
    if not first_class:
        return test_id
    return "::".join(["/".join(parts[:first_class]) + ".py", *parts[first_class:]])


_VALUE_OPTIONS = {"-s": "start", "--start-directory": "start", "-t": "top", "--top-level-directory": "top",
                  "-p": "pattern", "--pattern": "pattern", "-k": ""}
_POSITIONAL = ("start", "pattern", "top")


def module_prefix(command: str) -> str:
    """The folder, relative to where the command ran, that ``unittest discover`` names its modules from, dotted
    (``""``: the command's own folder, or no discover). ``discover -s tests``
    names ``test_pricing.PricingTest`` for ``tests/test_pricing.py``; without the prefix a green gate sees no
    confirmed test. Without
    ``-t`` the top folder is the start folder; an absolute folder cannot be placed and gives ``""``."""
    segment = next((part for part in re.split(r"&&|\|\||;|\|", str(command or "")) if "unittest" in part), "")
    try:
        words = shlex.split(segment)
    except ValueError:
        return ""
    if "unittest" not in words or words[words.index("unittest") + 1:words.index("unittest") + 2] != ["discover"]:
        return ""
    found: dict[str, str] = {}
    rest, positional = words[words.index("unittest") + 2:], 0
    while rest:
        word = rest.pop(0)
        option, _, inline = word.partition("=")
        if option in _VALUE_OPTIONS:
            value = inline if inline else (rest.pop(0) if rest else "")
            if _VALUE_OPTIONS[option]:
                found[_VALUE_OPTIONS[option]] = value
        elif not word.startswith("-") and positional < len(_POSITIONAL):
            found.setdefault(_POSITIONAL[positional], word)
            positional += 1
    folder = found.get("top") or found.get("start") or ""
    folder = folder.removeprefix("./").rstrip("/")
    if folder in ("", ".") or folder.startswith(("/", "~")) or ".." in folder.split("/"):
        return ""
    return folder.replace("/", ".")


def prefixed(where: str, prefix: str) -> str:
    """A unittest ``where`` as named from the command's folder (a module that failed to load keeps its marker)."""
    if not prefix:
        return where
    marker = "unittest.loader._FailedTest."
    if where.startswith(marker):
        return f"{marker}{prefix}.{where[len(marker):]}"
    return f"{prefix}.{where}"


__all__ = ["blocks", "file_for", "module_prefix", "path_form", "prefixed"]
