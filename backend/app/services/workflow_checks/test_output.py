"""Per-test results from what a test runner wrote, keyed by the canonical test id (``test_ids``). Pure.

Readers, the structured one first:

- **JUnit XML** (pytest ``--junitxml``, Jenkins/GitLab/Bitbucket/GitHub pipelines): a ``<testcase>`` with
  ``<failure>`` is an assertion failure, ``<error>`` an error, ``<skipped>`` skipped. Its id comes from the ``file``
  attribute when present, else from ``classname`` resolved against the repository's files (``test_ids.Resolver``).
  A case without classname is a module that failed to collect. When the text carries JUnit XML only the XML counts.
- **pytest** ``-v`` / ``-rA`` lines (also xdist's ``[gw0] [ 50%] PASSED id``): node ids, canonical as printed.
  ``ERROR path`` without ``::`` is a collection error of that file.
- **unittest** ``-v`` (``test_y (pkg.mod.TestA.test_y) ... ok`` on Python 3.11+, ``(pkg.mod.TestA)`` on 3.10 and below)
  with the ``FAIL:``/``ERROR:`` blocks for messages; ``unittest.loader._FailedTest`` is a module that failed to load.
- **Dart / Flutter** (``flutter test``, ``dart test``; the expanded reporter they print when not on a terminal):
  ``00:01 +3 ~1 -1: <file>: <groups and name>``. The counters (passed, skipped, failed) of each line say what the
  previous test did; ``[E]`` marks a failing test. Its id is ``test/x_test.dart::<full name>``, the file relative to
  its ``test/`` (or ``integration_test/``) folder's parent; a run of one file names its file only in ``loading``.
  Several files run concurrently by default and their lines interleave, so the counters cannot be attributed: such
  a run keeps its failures and reports a problem for the rest. A run is sequential when every file it names was
  loaded on its own ``loading`` line and its tests never interleave (one file, or ``flutter test -j 1``).
- **Go** ``--- PASS|FAIL|SKIP: Name``: the name names no file, so the result stays ``unresolved`` (open: Go's
  ``-json`` package output).

``failed`` means the test ran and an assertion failed; ``error`` means it did not get that far. A file- or
class-level ``error`` result marked ``scope: collection`` covers every test under it. A test whose id cannot be
resolved is kept in ``unresolved`` with its reason and its raw parts (re-resolved when the run knows more files);
a report that cannot be read, or output that lists fewer tests than its runner reported, is a ``problem``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .test_ids import Resolver, file_of, normalize

PASSED, FAILED, ERROR, SKIPPED = "passed", "failed", "error", "skipped"
SCOPE_COLLECTION = "collection"
MAX_RESULTS = 2000
MAX_XML_BYTES = 2_000_000
MAX_MESSAGE = 500
MAX_HINT_FILES = 500

_WORDS = {"PASSED": PASSED, "XPASS": PASSED, "FAILED": FAILED, "ERROR": ERROR, "SKIPPED": SKIPPED,
          "XFAIL": SKIPPED, "PASS": PASSED, "FAIL": FAILED, "SKIP": SKIPPED}
_PYTEST_WORD = r"(?P<word>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)"
_PYTEST_LINE = re.compile(rf"^(?P<id>[^\s\[][^\s]*?::.+?)\s+{_PYTEST_WORD}(?:\s+\[\s*\d+%\])?\s*$")
_XDIST_LINE = re.compile(rf"^\[gw\d+\]\s+\[\s*\d+%\]\s+{_PYTEST_WORD}\s+(?P<id>\S+::.+?)\s*$")
# Not unittest's own summary `FAILED (failures=1)`: it is no failed test.
_PYTEST_SUMMARY = re.compile(r"^(?P<word>PASSED|FAILED|ERROR|XFAIL|XPASS)\s+(?P<id>[^\s(]\S*?(?:::.+?)?)"
                             r"(?:\s+-\s+(?P<msg>.*))?$")
_PYTEST_COUNTS = re.compile(r"^(?:=+ )?(?P<body>\d+ (?:passed|failed|error|errors|skipped|deselected|xfailed|"
                            r"xpassed)\b.*) in [\d.]+s")
_GO_LINE = re.compile(r"^\s*--- (?P<word>PASS|FAIL|SKIP): (?P<id>\S+)")
# Node's spec reporter (`node --test`): "✔ name (0.1ms)", "✖ name (2ms)", "﹣ name # SKIP";
# its summary "ℹ tests 7". A name names no file: the platform's own runs attribute it (stacks.json report_env).
_NODE_LINE = re.compile(r"^\s*(?P<mark>[✔✖﹣])\s+(?P<name>.+?)(?:\s+\([\d.]+m?s\))?(?P<skip>\s+# (?:SKIP|TODO).*)?$")
_NODE_TESTS = re.compile(r"^ℹ tests (?P<count>\d+)$")
_UNITTEST_HEAD = r"(?P<name>[A-Za-z_][\w.]*) \((?P<where>[A-Za-z_][\w.]*)\)"
_UNITTEST_WORD = r"(?P<word>ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)"
_UNITTEST_LINE = re.compile(rf"^{_UNITTEST_HEAD}(?: \.\.\. {_UNITTEST_WORD})?$")
_UNITTEST_TAIL = re.compile(rf"^.* \.\.\. {_UNITTEST_WORD}$")
_UNITTEST_BLOCK = re.compile(rf"^(?P<kind>FAIL|ERROR): {_UNITTEST_HEAD}$")
_UNITTEST_RAN = re.compile(r"^Ran (?P<count>\d+) tests? in ")
_FAILED_TEST = "unittest.loader._FailedTest"


@dataclass(slots=True)
class ParsedTests:
    results: dict[str, dict[str, str]] = field(default_factory=dict)
    unresolved: list[dict[str, str]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    format: str = ""
    # A Dart run that ended "All tests passed!" with none skipped or failed: how many passed (whole suite only).
    suite_passed: int = 0

    def executed(self) -> int:
        """Tests the runner executed (a collection error is no executed test)."""
        return sum(1 for value in self.results.values() if value.get("scope") != SCOPE_COLLECTION) + sum(
            1 for item in self.unresolved if item.get("scope") != SCOPE_COLLECTION)

    def fields(self) -> dict[str, Any]:
        """What a recorded test run carries (``results``, and ``unresolved``/``problems`` only when present)."""
        extra = {key: value for key, value in (("unresolved", self.unresolved), ("problems", self.problems),
                                               ("suite_passed", self.suite_passed)) if value}
        return {"results": self.results, **extra}

    def add(self, test_id: str, outcome: str, message: str = "", *, scope: str = "", replace: bool = True) -> None:
        if len(self.results) >= MAX_RESULTS or (not replace and test_id in self.results):
            return
        value = {"outcome": outcome, "message": str(message or "")[:MAX_MESSAGE]}
        self.results[test_id] = {**value, "scope": scope} if scope else value

    def add_reported(self, resolver: Resolver, *, classname: str, name: str, file: str, outcome: str,
                     message: str = "", collection: bool = False) -> None:
        if collection:
            test_id, why = resolver.module(name) if not file else (normalize(file), "")
        else:
            test_id, why = resolver.resolve(classname, name, file)
        scope = SCOPE_COLLECTION if collection else ""
        if test_id:
            self.add(test_id, outcome, message, scope=scope)
        elif len(self.unresolved) < MAX_RESULTS:
            raw = ".".join(part for part in (classname, name) if part) or file
            item = {"raw": raw, "classname": classname, "name": name, "file": file, "outcome": outcome,
                    "message": str(message or "")[:MAX_MESSAGE], "reason": why}
            self.unresolved.append({**item, "scope": scope} if scope else item)


def _junit_root(text: str) -> tuple[Any | None, str]:
    start = text.find("<testsuite")
    end = max(text.rfind("</testsuites>") + len("</testsuites>"), text.rfind("</testsuite>") + len("</testsuite>"))
    if start < 0 or end <= start:
        return None, "the JUnit report has no complete <testsuite>"
    if end - start > MAX_XML_BYTES:
        return None, "the JUnit report is larger than 2 MB"
    if "<!ENTITY" in text[:end] or "<!DOCTYPE" in text[:end]:
        return None, "the JUnit report declares entities"  # a report is data, never an entity expansion
    try:
        return ElementTree.fromstring(text[start:end]), ""
    except ElementTree.ParseError as error:
        return None, f"the JUnit report is not well-formed XML ({error})"


def parse_junit(text: str, resolver: Resolver | None = None) -> ParsedTests:
    parsed = ParsedTests(format="junit")
    resolver = resolver or Resolver()
    root, problem = _junit_root(str(text or ""))
    if root is None:
        parsed.problems.append(problem)
        return parsed
    for case in root.iter("testcase"):
        failure, error, skipped = case.find("failure"), case.find("error"), case.find("skipped")
        outcome = FAILED if failure is not None else ERROR if error is not None else (
            SKIPPED if skipped is not None else PASSED)
        node = failure if failure is not None else error
        message = str((node.get("message") if node is not None else "") or (node.text if node is not None else "")
                      or "").strip()
        classname, name = str(case.get("classname") or ""), str(case.get("name") or "")
        parsed.add_reported(resolver, classname=classname, name=name, file=str(case.get("file") or ""),
                            outcome=outcome, message=message, collection=not classname and outcome == ERROR)
    if not parsed.results and not parsed.unresolved:
        parsed.problems.append("the JUnit report lists no test case")
    return parsed


def _pytest_counts(line: str) -> int | None:
    match = _PYTEST_COUNTS.match(line)
    if not match:
        return None
    return sum(int(number) for number, word in re.findall(r"(\d+) (passed|failed)\b", match["body"]))


def _unittest_where(name: str, where: str) -> str:
    """The dotted class of a unittest line: ``pkg.mod.TestA.test_y`` (Python 3.11+) or ``pkg.mod.TestA``."""
    return where[: -len(name) - 1] if where.endswith("." + name) else where


def _unittest_outcome(word: str) -> str:
    word = word.strip()
    if word == "ok":
        return PASSED
    if word in ("FAIL", "unexpected success"):
        return FAILED
    if word == "ERROR":
        return ERROR
    return SKIPPED  # skipped '…' / expected failure


def _unittest_add(parsed: ParsedTests, resolver: Resolver, name: str, where: str, outcome: str, message: str,
                  file: str = "") -> None:
    if where.startswith(_FAILED_TEST):
        # The module could not be imported: unittest names it after the loader's placeholder class.
        module = where[len(_FAILED_TEST) + 1:] or name
        parsed.add_reported(resolver, classname="", name=module, file="", outcome=ERROR, message=message,
                            collection=True)
        return
    parsed.add_reported(resolver, classname=_unittest_where(name, where), name=name, file=file, outcome=outcome,
                        message=message)


def _unittest_messages(lines: list[str]) -> dict[tuple[str, str], str]:
    """The last line of each ``FAIL:`` / ``ERROR:`` block's traceback (``AssertionError: …``) by ``(name, where)``.

    A block is its header (and the test's docstring line), a dashed line, then the traceback up to the next ruler."""
    messages: dict[tuple[str, str], str] = {}
    current: tuple[str, str] | None = None
    body, last = False, ""
    for line in lines:
        block = _UNITTEST_BLOCK.match(line)
        dashes = re.match(r"^-{20,}$", line)
        if current and dashes and not body:
            body = True
            continue
        if block or dashes or re.match(r"^={20,}$", line) or _UNITTEST_RAN.match(line):
            if current and last:
                messages.setdefault(current, last)
            current, body, last = ((block["name"], block["where"]) if block else None), False, ""
            continue
        if current and body and line.strip() and not line.startswith(" "):
            last = line.strip()
    return messages


_COLLECTING = re.compile(r"^_+ ERROR collecting (?P<file>\S+) _+$")


def _collection_messages(lines: list[str]) -> dict[str, str]:
    """The first ``E   …`` line of each pytest ``ERROR collecting <file>`` section, by file.

    ``pytest -v`` prints a collection error's summary as a bare ``ERROR <file>``; its cause (``ModuleNotFoundError``
    while the module under test does not exist yet) is only in the section above."""
    messages: dict[str, str] = {}
    current: str | None = None
    for line in lines:
        if header := _COLLECTING.match(line):
            current = normalize(header["file"])
            continue
        if re.match(r"^[_=]{5,}", line):
            current = None
            continue
        if current and line.startswith("E ") and current not in messages:
            messages[current] = line[1:].strip()
    return messages


def parse_lines(text: str, resolver: Resolver | None = None, command: str = "") -> ParsedTests:
    parsed = ParsedTests()
    resolver = resolver or Resolver()
    lines = [line.rstrip() for line in str(text or "").splitlines()]
    messages = _unittest_messages(lines)
    collecting = _collection_messages(lines)
    reported: int | None = None
    pending: tuple[str, str] | None = None  # a unittest line whose docstring line carries the outcome
    listed: set[tuple[str, str]] = set()  # the unittest tests a ``-v`` line already reported
    from .unittest_blocks import blocks, file_for, module_prefix, prefixed

    prefix = module_prefix(command)  # discover -s tests names modules from tests/

    failed_blocks = blocks(lines)  # a FAIL/ERROR block's traceback names the test's file
    block_paths = {(block["name"], block["where"]): block["path"] for block in failed_blocks}
    any_path = [block["path"] for block in failed_blocks if block["path"]]  # a module's file also names its passes
    for line in lines:
        if (counts := _pytest_counts(line)) is not None:
            reported = counts
        if ran := _UNITTEST_RAN.match(line):
            reported = int(ran["count"])
        summary = _PYTEST_SUMMARY.match(line)
        if summary and (summary["word"] != "ERROR" or "::" in summary["id"] or file_of(normalize(summary["id"]))):
            test_id = normalize(summary["id"])
            scope = SCOPE_COLLECTION if "::" not in test_id else ""
            parsed.add(test_id, _WORDS[summary["word"]], summary["msg"] or collecting.get(test_id, ""), scope=scope)
            parsed.format = parsed.format or "pytest"
            continue
        if match := (_PYTEST_LINE.match(line) or _XDIST_LINE.match(line)):
            parsed.add(normalize(match["id"]), _WORDS[match["word"]], replace=False)
            parsed.format = parsed.format or "pytest"
            continue
        if tests := _NODE_TESTS.match(line):
            reported = int(tests["count"])
            continue
        if match := _NODE_LINE.match(line):
            outcome = SKIPPED if match["skip"] or match["mark"] == "﹣" else FAILED if match["mark"] == "✖" else PASSED
            parsed.unresolved.append({"raw": match["name"], "classname": "", "name": match["name"], "file": "",
                                      "outcome": outcome, "message": "",
                                      "reason": "a node test name names no test file"})
            parsed.format = parsed.format or "node"
            continue
        if match := _GO_LINE.match(line):
            # A Go test name names no file: kept, never matched (a canonical id names its file).
            parsed.unresolved.append({"raw": match["id"], "classname": "", "name": match["id"], "file": "",
                                      "outcome": _WORDS[match["word"]], "message": "",
                                      "reason": "a Go test name names no test file"})
            parsed.format = parsed.format or "go"
            continue
        unittest = _UNITTEST_LINE.match(line)
        if unittest and (unittest["word"] or "." in unittest["where"]):
            if unittest["word"] is None:
                pending = (unittest["name"], unittest["where"])
                continue
            name, where = unittest["name"], unittest["where"]
        elif pending and (tail := _UNITTEST_TAIL.match(line)):
            (name, where), unittest = pending, tail
        else:
            pending = None
            continue
        pending = None
        listed.add((name, where))
        _unittest_add(parsed, resolver, name, prefixed(where, prefix), _unittest_outcome(unittest["word"]),
                      messages.get((name, where), ""),
                      next((found for path in [block_paths.get((name, where), ""), *any_path]
                            if (found := file_for(_unittest_where(name, prefixed(where, prefix)), path))), ""))
        parsed.format = parsed.format or "unittest"
    for block in failed_blocks:  # without -v a failed test is only its block
        if (block["name"], block["where"]) in listed:
            continue
        listed.add((block["name"], block["where"]))
        where = prefixed(block["where"], prefix)
        _unittest_add(parsed, resolver, block["name"], where, FAILED if block["kind"] == "FAIL" else ERROR,
                      messages.get((block["name"], block["where"]), ""),
                      file_for(_unittest_where(block["name"], where), block["path"]))
        parsed.format = parsed.format or "unittest"
    if reported is not None and reported > parsed.executed():
        parsed.problems.append(f"the output lists {parsed.executed()} of the {reported} tests its runner reported "
                               "(run the tests verbosely: pytest -v / -rA, unittest -v, or with --junitxml)")
    return parsed


_DART_LINE = re.compile(r"^\d+:\d{2} \+(?P<passed>\d+)(?: ~(?P<skipped>\d+))?(?: -(?P<failed>\d+))?: (?P<text>.*)$")
_DART_END = ("All tests passed!", "Some tests failed.")
_DART_TEST_DIRS = ("test", "integration_test", "test_driver")


def _dart_file(path: str) -> str:
    """``/abs/app/test/x_test.dart`` → ``test/x_test.dart`` (relative to the test folder's parent)."""
    parts = normalize(path).split("/")
    for index in range(len(parts) - 1, -1, -1):
        if parts[index] in _DART_TEST_DIRS:
            return "/".join(parts[index:])
    return normalize(path).lstrip("/")


def _dart_split(text: str, single: str) -> tuple[str, str]:
    """``(file, test name)`` of a reporter line's description."""
    head, sep, rest = text.partition(".dart: ")
    if sep and " " not in head.strip("/").split("/")[-1]:
        return _dart_file(head + ".dart"), rest
    return single, text


def _dart_sequential(lines: list[str], loading: list[str], single: str) -> bool:
    order: list[str] = []
    for line in lines:
        match = _DART_LINE.match(line)
        if not match or match["text"].startswith("loading ") or match["text"] in _DART_END:
            continue
        file = _dart_split(match["text"], single)[0]
        if not order or order[-1] != file:
            if file in order:
                return False  # a file's tests resumed after another file's: interleaved
            order.append(file)
    return len(order) <= 1 or set(order) <= set(loading)


def parse_dart(text: str, command: str = "") -> ParsedTests:
    """Per-test results of the Dart / Flutter expanded reporter (module docstring). ``command``: the test command;
    its one ``.dart`` argument names the file when the output lost its ``loading`` line (as with
    ``flutter test test/x_test.dart 2>&1 | tail -30``, which otherwise records no result at all)."""
    parsed = ParsedTests(format="dart")
    lines = [line.rstrip() for line in str(text or "").splitlines()]
    loading = list(dict.fromkeys(_dart_file(line.split(": loading ", 1)[1]) for line in lines
                                 if ": loading " in line and _DART_LINE.match(line)))
    named = [_dart_file(word) for word in str(command or "").split() if word.endswith(".dart")]
    from ..engineering_knowledge.stacks import collection_errors

    broken = collection_errors()  # finding 7: a file that failed to load (stack data), not a test named "loading …"
    if not loading and len(set(named)) == 1:
        loading = named[:1]
    single = loading[0] if len(loading) == 1 else ""
    concurrent = not _dart_sequential(lines, loading, single)
    previous: tuple[int, int, int] = (0, 0, 0)
    current = ""
    message: list[str] = []
    failing, failing_scope = "", ""
    unnamed = False
    for line in lines:
        match = _DART_LINE.match(line)
        if not match:
            if failing and line.strip() and len(message) < 8:
                message.append(line.strip())
            continue
        if failing:
            parsed.add(failing, ERROR if failing_scope else FAILED, " ".join(message), scope=failing_scope)
            failing, message = "", []
        counts = (int(match["passed"]), int(match["skipped"] or 0), int(match["failed"] or 0))
        body = match["text"]
        load_error = next((found for pattern in broken if (found := pattern.match(body))), None)
        if load_error is not None:
            described = ""
            failing, failing_scope = _dart_file(load_error["file"]), SCOPE_COLLECTION
        elif body.startswith("loading ") or body in _DART_END:
            described = ""
        else:
            failed_mark = body.endswith(" [E]")
            file, name = _dart_split(body.removesuffix(" [E]"), single)
            described = f"{file}::{name}" if file and name else ""
            unnamed = unnamed or not file
            if failed_mark and described:
                failing, failing_scope = described, ""
        if current and not concurrent and counts != previous:
            if counts[0] > previous[0]:
                parsed.add(current, PASSED, replace=False)
            elif counts[1] > previous[1]:
                parsed.add(current, SKIPPED, replace=False)
        previous = counts
        if described and described != current:
            current = described
        elif not described:
            current = ""
    if failing:
        parsed.add(failing, ERROR if failing_scope else FAILED, " ".join(message), scope=failing_scope)
    # The closing "Failing tests:" block names every failing test with its file
    # (``flutter test 2>&1 | tail -n 5`` keeps only that block; without it the red confirmed test is never recorded).
    if "Failing tests:" in lines:
        for line in lines[lines.index("Failing tests:") + 1:]:
            head, sep, name = line.strip().partition(".dart: ")
            if not sep or not line.startswith("  "):
                break
            parsed.add(f"{_dart_file(head + '.dart')}::{name}", FAILED, replace=False)
    end = next((match for line in reversed(lines) if (match := _DART_LINE.match(line))
                and match["text"] in _DART_END), None)
    if end is not None and end["text"] == "All tests passed!" and not end["skipped"] and not end["failed"]:
        parsed.suite_passed = int(end["passed"])
    if concurrent and end is not None and end["text"] == "All tests passed!" and not end["skipped"] and \
            not end["failed"]:
        # a whole run of several files ran concurrently, so no single pass could be
        # attributed and the confirmed test was "missing from the last run"; when the run ends with every test
        # passed and none skipped, every test it named passed.
        for line in lines:
            match = _DART_LINE.match(line)
            if match and not match["text"].startswith("loading ") and match["text"] not in _DART_END:
                file, name = _dart_split(match["text"].removesuffix(" [E]"), single)
                if file and name:
                    parsed.add(f"{file}::{name}", PASSED, replace=False)
        concurrent = False
    if concurrent:
        parsed.problems.append("the test files ran concurrently, so only their failures are attributed (run the "
                               "tests with the JSON reporter the stack declares, or one test file at a time)")
    elif unnamed:
        parsed.problems.append("the output names no test file (run flutter test with the test file's path)")
    return parsed


def _is_dart(text: str) -> bool:
    return any((match := _DART_LINE.match(line.rstrip())) and (match["text"].startswith("loading ")
                                                                 or match["text"] in _DART_END)
               for line in str(text or "").splitlines())


def parse(text: str, resolver: Resolver | None = None, command: str = "") -> ParsedTests:
    """Per-test results of a test command's output (JUnit XML in it wins over its printed lines)."""
    text = str(text or "")
    if "<testcase" in text:
        report = parse_junit(text, resolver)
        if report.results or report.unresolved:
            return report
        lines = parse_lines(text, resolver, command)
        lines.problems = [*report.problems, *lines.problems]
        return lines
    from .dart_json import is_dart_json, parse_dart_json

    if is_dart_json(text):  # concurrent files attributed exactly (evidence_unresolved,/)
        return parse_dart_json(text)
    if _is_dart(text):
        return parse_dart(text, command)
    return parse_lines(text, resolver, command)


def hint_files(raw: Iterable[Any] | None) -> list[str]:
    """Bounded, canonical test-file hints from a report (anything else is dropped)."""
    files = [normalize(item) for item in (raw or []) if isinstance(item, str)]
    return list(dict.fromkeys(item for item in files if file_of(item) and not item.startswith("/")
                              and ".." not in item.split("/")))[:MAX_HINT_FILES]


__all__ = ["ERROR", "FAILED", "MAX_RESULTS", "PASSED", "ParsedTests", "SCOPE_COLLECTION", "SKIPPED", "hint_files",
           "parse", "parse_dart", "parse_junit", "parse_lines"]
