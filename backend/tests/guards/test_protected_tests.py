from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from tests.guards._protected_tests import (
    INVENTORY_FILE,
    file_test_ids,
    inventory_problems,
    inventory_source,
    present_test_ids,
    regenerated,
    scanned_files,
    unlisted,
)
from tests.guards._protected_tests_inventory import PROTECTED, RETIRED
from tests.guards._support import BACKEND

PLANTED = "tests/guards/test_planted.py"
KEPT = f"{PLANTED}::test_kept"
GONE = f"{PLANTED}::test_gone"
SOURCE = (
    "def test_kept():\n    def test_nested():\n        pass\n\n"
    "async def test_async():\n    pass\n\n"
    "def helper():\n    pass\n\n"
    "class TestGroup:\n    def test_member(self):\n        pass\n\n    def setup(self):\n        pass\n"
)


def _planted(root: Path) -> set[str]:
    path = root / PLANTED
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SOURCE, encoding="utf-8")
    return present_test_ids(root, scanned_files(root))


def test_no_protected_test_disappeared() -> None:
    present = present_test_ids(BACKEND, scanned_files(BACKEND))
    new = unlisted(present, PROTECTED)
    if new:
        warnings.warn(f"{len(new)} unlisted protected-area test(s), regenerate:\n  " + "\n  ".join(new), stacklevel=1)
    problems = inventory_problems(BACKEND, present, PROTECTED, RETIRED)
    assert not problems, f"{len(problems)} protected test problem(s):\n  " + "\n  ".join(problems)


def test_inventory_file_is_the_generated_one() -> None:
    assert INVENTORY_FILE.read_text(encoding="utf-8") == inventory_source(PROTECTED, RETIRED)


def test_mutation_top_level_and_class_tests_are_found_and_helpers_are_not(tmp_path: Path) -> None:
    _planted(tmp_path)
    assert file_test_ids(tmp_path, tmp_path / PLANTED) == {
        KEPT, f"{PLANTED}::test_async", f"{PLANTED}::TestGroup::test_member",
    }


def test_mutation_a_deleted_protected_test_is_reported(tmp_path: Path) -> None:
    problems = inventory_problems(tmp_path, _planted(tmp_path), [KEPT, GONE], {})
    assert problems == [f"{GONE}: a protected test disappeared; restore it or move it to RETIRED with its reason"]


@pytest.mark.parametrize("reason", ["subject deleted: the planted route", f"covered by {KEPT}"])
def test_mutation_a_retired_test_with_a_valid_reason_passes(tmp_path: Path, reason: str) -> None:
    assert inventory_problems(tmp_path, _planted(tmp_path), [KEPT], {GONE: reason}) == []


@pytest.mark.parametrize(("reason", "expected"), [
    ("obsolete", "retired reason must read"),
    ("subject deleted:", "retired reason must read"),
    (f"covered by {PLANTED}::test_missing", "does not exist"),
    ("covered by tests/guards/test_absent.py::test_kept", "does not exist"),
])
def test_mutation_a_retired_test_with_a_bad_reason_is_reported(tmp_path: Path, reason: str, expected: str) -> None:
    problems = inventory_problems(tmp_path, _planted(tmp_path), [KEPT], {GONE: reason})
    assert len(problems) == 1 and expected in problems[0]


def test_mutation_a_retired_test_that_is_present_or_still_listed_is_reported(tmp_path: Path) -> None:
    retired = {KEPT: "subject deleted: x", GONE: "subject deleted: y"}
    problems = inventory_problems(tmp_path, _planted(tmp_path), [GONE], retired)
    assert problems == [f"{GONE}: both protected and retired", f"{KEPT}: retired but present; drop it from RETIRED"]


def test_mutation_regenerating_only_adds(tmp_path: Path) -> None:
    present = _planted(tmp_path)
    retired = {f"{PLANTED}::test_async": f"covered by {KEPT}"}
    assert regenerated(present, [GONE], retired) == sorted({GONE, KEPT, f"{PLANTED}::TestGroup::test_member"})
