from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from tests.guards._slop_patterns import (
    BASELINE_FILE,
    Counts,
    baseline_source,
    ratchet_problems,
    scanned_files,
    slop_counts,
)
from tests.guards._slop_patterns_baseline import SLOP_BASELINE
from tests.guards._support import REPO_ROOT

PLANTED = "backend/app/planted.py"
LONG_BODY = "".join(f"    x{i} = {i}\n" for i in range(61))


def _planted(root: Path, source: str) -> dict[str, Counts]:
    path = root / PLANTED
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return slop_counts(root, [path])


def test_slop_patterns_are_within_the_baseline() -> None:
    # Only growth fails: a row that went down is reported as lowerable and regenerated when a batch is assembled.
    problems = ratchet_problems(slop_counts(REPO_ROOT, scanned_files(REPO_ROOT)), SLOP_BASELINE)
    lowerable = [problem for problem in problems if "lower the baseline" in problem]
    if lowerable:
        warnings.warn("can be lowered:\n  " + "\n  ".join(lowerable), stacklevel=1)
    failing = [problem for problem in problems if problem not in lowerable]
    assert not failing, f"{len(failing)} slop pattern problem(s):\n  " + "\n  ".join(failing)


def test_baseline_file_is_the_generated_one() -> None:
    assert BASELINE_FILE.read_text(encoding="utf-8") == baseline_source(SLOP_BASELINE)


@pytest.mark.parametrize(("source", "expected"), [
    ("def load(db, *, key):\n    return fetch(db, key=key)\n", (1, 0, 0, 0, 0)),
    ("async def load(db):\n    return await fetch(db)\n", (1, 0, 0, 0, 0)),
    ("try:\n    run()\nexcept Exception:\n    pass\n", (0, 1, 0, 0, 0)),
    ("try:\n    run()\nexcept:\n    pass\n", (0, 1, 0, 0, 0)),
    ("try:\n    run()\nexcept (ValueError, BaseException):\n    pass\n", (0, 1, 0, 0, 0)),
    ("def _load():\n    return 1\n\n\nload = _load\n", (0, 0, 1, 0, 0)),
    ("VALUE = 1\n" * 305, (0, 0, 0, 5, 0)),
    ("def build():\n" + LONG_BODY, (0, 0, 0, 0, 2)),
])
def test_mutation_planted_pattern_is_reported(tmp_path: Path, source: str, expected: Counts) -> None:
    found = _planted(tmp_path, source)
    assert found == {PLANTED: expected}
    assert ratchet_problems(found, {})


@pytest.mark.parametrize("source", [
    "def load(db, *, key):\n    return fetch(db, key=key, fresh=True)\n",
    "def load(db):\n    return fetch(db.session)\n",
    "@router.get('/x')\nasync def read(db):\n    return await handle(db)\n",
    "class Store:\n    def get(self, key):\n        return fetch(self, key)\n",
    "def ports(scheme):\n    return _PORTS.get(scheme)\n",
    "try:\n    run()\nexcept Exception:  # a broken plugin must not stop the others\n    pass\n",
    "try:\n    run()\nexcept Exception:\n    # the probe answers 'unknown' rather than failing the page\n    pass\n",
    "try:\n    run()\nexcept Exception:\n    log()\n    raise\n",
    "try:\n    run()\nexcept ValueError:\n    pass\n",
    "LIMIT = 10\nMAX_BYTES = LIMIT\n",
    "from typing import Any\nPayload = Any\n",
])
def test_mutation_clean_shapes_are_not_reported(tmp_path: Path, source: str) -> None:
    assert _planted(tmp_path, source) == {}


def test_mutation_a_grown_file_breaks_the_ratchet() -> None:
    problems = ratchet_problems({PLANTED: (0, 0, 0, 7, 0)}, {PLANTED: (0, 0, 0, 5, 0)})
    assert problems == [f"{PLANTED}: lines over 300 per file 7, baseline 5: fix the new ones"]
