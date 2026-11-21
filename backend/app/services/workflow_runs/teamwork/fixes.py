"""A red pipeline after the team's work becomes targeted fix items, not a full re-plan (a full re-plan is
slow).

Without this, a pipeline red for one item's files sent the loop back
to the
coordinator (2:09 for a new plan), and the new plan re-ran all five items (6:50). So the pipeline's ``failed`` loop
goes back to the ``parallel_work`` node itself, and :func:`assign` reopens only the items that own what failed:

- a task without a passing proof test (``unproven``: ``"<item> (<proof>: <outcome>; ...)"``) goes to that item;
- a failing test goes to the item whose paths cover the failing code: a file of another item that the test's own
  failure output names (the traceback of a system test points into the screen it drives), else the owner of the test
  file itself;
- a red command without a failing test (a collection or import error) goes to the owners of the files its output
  names.

The review's findings take the same way (:func:`assign_review`): the product owner's ``decisions`` node, revising
automatically on a high finding, goes back to the team node, and each finding goes to the item owning the file it
names. A person's own answer there still goes to the coordinator.

What no item owns goes back to the coordinator (``replan``) with the pipeline's failure. A fix item that
blocks or fails also routes ``replan`` (the scheduler's rule): only then does the coordinator plan again.
"""

from __future__ import annotations

import re
from typing import Any

from . import MERGED
from .plan import reopen_fields, write_paths

# A repository file named in test output: ``src/kitchen-helper/api.py:12``, ``File "/abs/path/x.py", line 3``,
# ``static/a.js``.
_FILE = re.compile(r"((?:[\w@.+-]+/)*[\w@.+-]+\.(?:py|pyi|js|mjs|cjs|jsx|ts|tsx|vue|svelte|css|scss|html|json|toml|"
                   r"cfg|ini|ya?ml|sql|md))\b")
# pytest's failure section header: ``____ test_name ____`` or ``____ TestClass.test_name[param] ____``.
_SECTION = re.compile(r"^_{3,} (\S.*?) _{3,}\s*$", re.MULTILINE)
_SUMMARY = re.compile(r"^={3,} .*(short test summary|passed|failed|error).*={3,}\s*$", re.MULTILINE | re.IGNORECASE)
REASON = "the CI pipeline on the merged story is red in your part"
REVIEW_REASON = "the independent review of the merged story found this in your files"


def _owners(items: dict[str, dict[str, Any]], path: str) -> list[str]:
    from ..protected_paths import path_matches

    return [key for key, item in items.items()
            if any(path == pattern or path_matches(path, pattern) for pattern in write_paths(item))]


def _repo_owners(items: dict[str, dict[str, Any]], named: str) -> list[str]:
    """The owners of a file named in output, absolute or relative: the longest tail of its path that an item owns."""
    parts = [part for part in named.replace("\\", "/").split("/") if part not in ("", ".")]
    for start in range(len(parts)):
        owners = _owners(items, "/".join(parts[start:]))
        if owners:
            return owners
    return []


def _is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return "/tests/" in f"/{path}" or name.startswith("test_") or name.endswith(("_test.py", ".test.js", ".test.ts",
                                                                                  ".spec.js", ".spec.ts"))


def _code_owners(items: dict[str, dict[str, Any]], text: str) -> list[str]:
    """The items owning the non-test files ``text`` names, in the order they appear."""
    found: list[str] = []
    for named in _FILE.findall(text or ""):
        if _is_test_file(named) or "site-packages/" in named or named.startswith(("/usr/", "/opt/")):
            continue
        found += [key for key in _repo_owners(items, named) if key not in found]
    return found


def sections(output: str) -> dict[str, str]:
    """pytest's failure sections of ``output`` by their header (``test_name`` or ``Class.test_name[param]``)."""
    found: dict[str, str] = {}
    headers = list(_SECTION.finditer(output or ""))
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(output)
        summary = _SUMMARY.search(output, header.end(), end)
        found[header.group(1).strip()] = output[header.start():summary.start() if summary else end]
    return found


def _section_of(test_id: str, found: dict[str, str]) -> str:
    name = test_id.split("::")[-1]
    bare = name.split("[")[0]
    return next((text for header, text in found.items()
                 if header == name or header.endswith(f".{name}") or header.split("[")[0].split(".")[-1] == bare), "")


def assign(items: dict[str, dict[str, Any]], red: dict[str, Any]) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    """``(fixes, unassigned)``: per item what it fixes (``{"what", "output"}``), and the failures no item owns."""
    fixes: dict[str, list[dict[str, str]]] = {}
    unassigned: list[str] = []

    def add(key: str, what: str, output: str = "") -> None:
        entry = {"what": what, **({"output": output} if output else {})}
        if entry not in fixes.setdefault(key, []):
            fixes[key].append(entry)

    for line in red.get("unproven") or []:
        key, _sep, rest = str(line).partition(" (")
        if key in items:
            add(key, f"proof tests that did not pass in the pipeline: {rest.rstrip(')')}")
        else:
            unassigned.append(str(line))
    for result in red.get("results") or []:
        if result.get("exit_code") == 0 or result.get("no_tests"):
            continue
        output = str(result.get("output_tail") or "")
        command = str(result.get("command") or "")
        tests = [str(test) for test in result.get("failed_tests") or []]
        if not tests:
            owners = _code_owners(items, output) or [key for named in _FILE.findall(output)
                                                     for key in _repo_owners(items, named)]
            for key in dict.fromkeys(owners):
                add(key, f"`{command}` failed (exit {result.get('exit_code')}) on a file you own", output)
            if not owners:
                unassigned.append(f"{command} failed (exit {result.get('exit_code')}) and its output names no "
                                  "item's file")
            continue
        found = sections(output)
        for test in tests:
            text = _section_of(test, found)
            test_owners = _owners(items, test.split("::", 1)[0])
            code = [key for key in _code_owners(items, text) if key not in test_owners]
            owners = code[:1] or test_owners
            for key in owners:
                add(key, f"{test} failed in `{command}`" + (" (its failure points into your files)" if code else ""),
                    text)
            if not owners:
                unassigned.append(f"{test} failed in {command} and no item owns its test or the code it names")
    return fixes, unassigned


def assign_review(items: dict[str, dict[str, Any]],
                  findings: list[Any]) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    """The review's findings by the item that owns the file each names (``file:line [severity] fix``); the ones no
    item owns. Otherwise three high findings (flat cards instead of the
    gradient,
    a missing icon circle, a toast in the wrong language) each went through a coordinator round, about 10 minutes for
    2-minute fixes."""
    fixes: dict[str, list[dict[str, str]]] = {}
    unassigned: list[str] = []
    for finding in findings:
        rendered = finding.render()
        owners = _repo_owners(items, str(finding.file or "")) if finding.file else []
        for key in owners[:1]:
            fixes.setdefault(key, []).append({"what": f"review finding {rendered}"})
        if not owners:
            unassigned.append(rendered)
    return fixes, unassigned


def reopen_for_fixes(items: dict[str, dict[str, Any]], fixes: dict[str, list[dict[str, str]]], *,
                     source: str = "pipeline") -> dict[str, dict[str, Any]]:
    """The split with each item that has a fix back at ``pending`` (its next iteration, its own session resumed,
    ``fix`` naming exactly what failed). Items without a fix stay as they are: merged work is never built again."""
    reason = REASON if source == "pipeline" else REVIEW_REASON
    split = {key: dict(value) for key, value in items.items()}
    for key, entries in fixes.items():
        item = split.get(key)
        if item is None or item.get("status") != MERGED:
            continue
        whats = "; ".join(entry["what"] for entry in entries)
        split[key] = {**item, **reopen_fields(item, f"{reason}: {whats}"), "fix": entries, "fix_source": source}
    return split


def red_lines(unassigned: list[str]) -> list[str]:
    return [f"The CI pipeline is red and no item owns it: {line}" for line in unassigned]


def review_lines(unassigned: list[str]) -> list[str]:
    return [f"A review finding no item owns: {line}" for line in unassigned]


__all__ = ["REASON", "REVIEW_REASON", "assign", "assign_review", "red_lines", "reopen_for_fixes", "review_lines",
           "sections"]
