"""unittest's ``FAIL:`` / ``ERROR:`` blocks as tests, and its dotted test ids next to pytest's paths."""

from __future__ import annotations

import re
import shlex

_BLOCK = re.compile(r"^(?P<kind>FAIL|ERROR): (?P<name>[A-Za-z_][\w.]*) \((?P<where>[A-Za-z_][\w.]*)\)$")
_FILE = re.compile(r'^\s*File "(?P<path>[^"]+\.py)", line \d+')


def blocks(lines: list[str]) -> list[dict[str, str]]:
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
    parts = classname.split(".")
    for index in range(len(parts), 0, -1):
        relative = "/".join(parts[:index]) + ".py"
        if path == relative or path.endswith("/" + relative):
            return relative
    return ""


def path_form(test_id: str) -> str:
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
    if not prefix:
        return where
    marker = "unittest.loader._FailedTest."
    if where.startswith(marker):
        return f"{marker}{prefix}.{where[len(marker):]}"
    return f"{prefix}.{where}"


__all__ = ["blocks", "file_for", "module_prefix", "path_form", "prefixed"]
