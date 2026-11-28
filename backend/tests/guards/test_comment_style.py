from __future__ import annotations

import re
import warnings
from pathlib import Path

import pytest

from tests.guards._comment_style import (
    BASELINE_FILE,
    NARRATION,
    Counts,
    baseline_source,
    comment_style_counts,
    ratchet_problems,
    scanned_files,
)
from tests.guards._comment_style_baseline import COMMENT_STYLE_BASELINE
from tests.guards._support import REPO_ROOT
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

PLANTED = "backend/app/planted.py"
RATCHETED_PLANTED = "backend/app/schemas/planted.py"
CODE = "VALUE = 1\n"


def _planted(root: Path, relative: str, source: str) -> dict[str, Counts]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return comment_style_counts(root, [path])


def test_comment_style_is_within_the_baseline() -> None:
    # Only growth fails: a row that went down is reported as lowerable and regenerated when a batch is assembled.
    problems = ratchet_problems(comment_style_counts(REPO_ROOT, scanned_files(REPO_ROOT)), COMMENT_STYLE_BASELINE)
    lowerable = [problem for problem in problems if "lower the baseline" in problem]
    if lowerable:
        warnings.warn("can be lowered:\n  " + "\n  ".join(lowerable), stacklevel=1)
    failing = [problem for problem in problems if problem not in lowerable]
    assert not failing, f"{len(failing)} comment style problem(s):\n  " + "\n  ".join(failing)


def test_baseline_file_is_the_generated_one() -> None:
    assert BASELINE_FILE.read_text(encoding="utf-8") == baseline_source(COMMENT_STYLE_BASELINE)


@pytest.mark.parametrize(("relative", "source", "expected"), [
    (PLANTED, 'def _helper():\n    """Private."""\n    return 1\n', (1, 0, 0, 0, 0)),
    (PLANTED, 'class _Helper:\n    """Private\n    class."""\n', (2, 0, 0, 0, 0)),
    (PLANTED, 'def helper():\n    """Not an interface."""\n', (1, 0, 0, 0, 0)),
    (PLANTED, 'class Helper:\n    def __init__(self):\n        """Dunder."""\n', (1, 0, 0, 0, 0)),
    ("backend/tests/test_planted.py", 'def test_it():\n    """Prose."""\n    assert True\n', (1, 0, 0, 0, 0)),
    ("backend/tests/test_planted.py", 'class TestIt:\n    """Prose."""\n', (1, 0, 0, 0, 0)),
    ("backend/tests/planted_support.py", 'def build():\n    """Helper."""\n', (1, 0, 0, 0, 0)),
    (PLANTED, '@router.get("/x")\nasync def read():\n    """One.\n\n    Three.\n    """\n', (0, 2, 0, 0, 0)),
    ("clients/octryx-claude/planted.py", '"""One.\n\nThree.\n"""\nVALUE = 1\n', (0, 2, 0, 0, 0)),
    (PLANTED, "VALUE = 1  # moved from services/old.py\n", (0, 0, 1, 0, 0)),
    (PLANTED, "import os  # noqa: F401 - moved from services/old.py\n", (0, 0, 1, 0, 0)),
    (PLANTED, '@router.get("/")\ndef read():\n    """Answers C12B-04."""\n', (0, 0, 1, 0, 0)),
    (PLANTED, "# why\n# and why\n" + CODE * 5, (0, 0, 0, 2, 7)),
])
def test_mutation_planted_violation_in_a_new_file_is_reported(
    tmp_path: Path, relative: str, source: str, expected: Counts,
) -> None:
    found = _planted(tmp_path, relative, source)
    assert found == {relative: expected}
    assert ratchet_problems(found, {})


@pytest.mark.parametrize("source", [
    '@router.post("/x")\nasync def create():\n    """Two\n    lines."""\n',
    "# why\n" + CODE,
    "# why\n" + CODE * 6 + "OTHER = 2  # noqa: F401\n",
    "# uncut 4 rows; the owner decides; the train leaves; backward is fine\n" + CODE * 6,
])
def test_mutation_compliant_source_is_not_reported(tmp_path: Path, source: str) -> None:
    assert _planted(tmp_path, PLANTED, source) == {}


def test_mutation_exempt_cli_module_docstring_may_be_long(tmp_path: Path) -> None:
    relative = "backend/app/services/knowledge/eval/run.py"
    assert _planted(tmp_path, relative, '"""Usage.\n\n    python -m run\n"""\n') == {}


def test_mutation_count_increase_in_a_baselined_file_is_reported(tmp_path: Path) -> None:
    found = _planted(tmp_path, RATCHETED_PLANTED, "A = 1  # finding C12-01\nB = 2  # finding C12-02\n" + CODE * 12)
    assert ratchet_problems(found, {RATCHETED_PLANTED: (0, 0, 1, 0, 0)}) == [
        f"{RATCHETED_PLANTED}: narration lines 2, baseline 1: fix the new ones",
    ]


def test_mutation_count_decrease_in_a_baselined_file_asks_for_a_lower_baseline(tmp_path: Path) -> None:
    problems = ratchet_problems(_planted(tmp_path, RATCHETED_PLANTED, CODE), {RATCHETED_PLANTED: (1, 0, 1, 0, 0)})
    assert len(problems) == 2 and all("lower the baseline" in problem for problem in problems)


@pytest.mark.parametrize(("source", "suffix"), [
    ("# why\n# and why\n" + CODE * 4, "2/6, baseline 2/8: the share rose, remove comments"),
    ("# one\n# two\n# three\n" + CODE * 15, "3/18, baseline 2/8: fix the new ones"),
    ("# why\n# and why\n" + CODE * 20, "0/0, baseline 2/8: lower the baseline"),
])
def test_mutation_comment_share_change_is_reported(tmp_path: Path, source: str, suffix: str) -> None:
    problems = ratchet_problems(_planted(tmp_path, RATCHETED_PLANTED, source), {RATCHETED_PLANTED: (0, 0, 0, 2, 8)})
    assert len(problems) == 1 and problems[0].startswith(f"{RATCHETED_PLANTED}: comment lines over 15 % {suffix}")


def test_mutation_more_code_with_the_same_comments_needs_no_new_baseline(tmp_path: Path) -> None:
    found = _planted(tmp_path, RATCHETED_PLANTED, "# why\n# and why\n" + CODE * 8)
    assert found == {RATCHETED_PLANTED: (0, 0, 0, 2, 10)}
    assert ratchet_problems(found, {RATCHETED_PLANTED: (0, 0, 0, 2, 8)}) == []


def test_mutation_outside_ratcheted_every_finding_fails_and_the_baseline_may_not_list_it(tmp_path: Path) -> None:
    found = _planted(tmp_path, PLANTED, "A = 1  # finding C12-01\n" + CODE * 12)
    problems = ratchet_problems(found, {PLANTED: (0, 0, 1, 0, 0)})
    assert problems == [
        f"{PLANTED}: narration lines 1: fix them (no baseline outside RATCHETED)",
        f"{PLANTED}: outside RATCHETED, the baseline may not list it (.venv/bin/python -m tests.guards._comment_style "
        "(from backend/))",
    ]
    assert ratchet_problems({}, {"backend/tests/test_old.py": (1, 0, 0, 0, 0)}) == [
        "backend/tests/test_old.py: outside RATCHETED, the baseline may not list it (.venv/bin/python -m "
        "tests.guards._comment_style (from backend/))",
    ]


def test_mutation_a_comment_share_outside_ratcheted_fails_without_a_baseline(tmp_path: Path) -> None:
    found = _planted(tmp_path, "clients/octryx-claude/planted.py", "# why\n# and why\n" + CODE * 5)
    assert ratchet_problems(found, {}) == ["clients/octryx-claude/planted.py: comment lines over 15 % 2/7: remove comments"]


def test_mutation_regenerating_never_adds_a_row_or_raises_a_count() -> None:
    from tests.guards._comment_style import regenerated

    assert regenerated({RATCHETED_PLANTED: (1, 0, 0, 0, 0)}, {}) == {}, "a new finding gets no row"
    grown = regenerated({RATCHETED_PLANTED: (9, 0, 0, 0, 0)}, {RATCHETED_PLANTED: (2, 0, 0, 0, 0)})
    assert grown == {RATCHETED_PLANTED: (2, 0, 0, 0, 0)}
    lowered = regenerated({RATCHETED_PLANTED: (1, 0, 0, 0, 0)}, {RATCHETED_PLANTED: (2, 0, 0, 0, 0)})
    assert lowered == {RATCHETED_PLANTED: (1, 0, 0, 0, 0)}
    assert regenerated({}, {RATCHETED_PLANTED: (2, 0, 0, 0, 0)}) == {}, "a clean file leaves the baseline"


def test_the_baseline_lists_only_ratcheted_files() -> None:
    from tests.guards._comment_style import ratcheted

    assert [key for key in COMMENT_STYLE_BASELINE if not ratcheted(key)] == []


def test_frontend_scan_uses_the_same_narration_list() -> None:
    scanner = (REPO_ROOT / "frontend/chat/tests/unit/commentStyleScan.mjs").read_text(encoding="utf-8")
    block = scanner.split("const NARRATION = new RegExp([", 1)[1].split("].join", 1)[0]
    assert "|".join(re.findall(r"String\.raw`([^`]*)`", block)) == NARRATION.pattern
