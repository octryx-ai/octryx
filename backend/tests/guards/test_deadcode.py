from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from tests.guards._deadcode_baseline import DEAD_CODE_BASELINE
from tests.guards._support import APP, BACKEND, assert_guard, comparison_problems, counted
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

MIN_CONFIDENCE = 80
# vulture rates an unused function or method at 60; every other kind of finding at that level is too noisy.
FUNCTION_CONFIDENCE = 60
FUNCTION_FINDINGS = ("unused function ", "unused method ")
# The framework calls these: routes, MCP tools and resources, model validators and ORM event listeners.
FRAMEWORK_DECORATORS = (
    "@*router.get", "@*router.post", "@*router.put", "@*router.patch", "@*router.delete", "@*router.websocket",
    "@*router.api_route", "@app.get", "@server.tool", "@server.resource", "@model_validator", "@field_validator",
    "@field_serializer", "@validates", "@event.listens_for",
)
_LINE = re.compile(
    r"^(?P<path>[^:]+):\d+: (?P<message>.+) \((?P<confidence>\d+)% confidence(?:, \d+ lines?)?\)$"
)


def vulture_findings(*targets: Path, cwd: Path) -> set[str]:
    paths = [str(target.relative_to(cwd)) if target.is_relative_to(cwd) else str(target) for target in targets]
    run = subprocess.run(
        [sys.executable, "-m", "vulture", *paths, "--min-confidence", str(FUNCTION_CONFIDENCE),
         "--ignore-decorators", ",".join(FRAMEWORK_DECORATORS)],
        cwd=cwd, capture_output=True, text=True, check=False,
    )
    # 3 means "dead code found"; any other non-zero code is a broken run, not a clean one.
    assert run.returncode in (0, 3), f"vulture failed ({run.returncode}): {run.stderr or run.stdout}"
    findings: Counter[str] = Counter()
    for line in run.stdout.splitlines():
        match = _LINE.match(line.strip())
        assert match, f"unparsed vulture line: {line}"
        if int(match["confidence"]) >= MIN_CONFIDENCE or match["message"].startswith(FUNCTION_FINDINGS):
            findings[f"{match['path']}: {match['message']}"] += 1
    return counted(findings)


def test_dead_code_equals_the_baseline() -> None:
    assert_guard(vulture_findings(APP, cwd=BACKEND), DEAD_CODE_BASELINE, what="dead code")


# The trusted baseline is the one on the base branch the gate merges into; a branch may only remove entries.
BASE_REF = os.environ.get("OCTRYX_GUARD_BASE", "origin/0.0.2")
BASELINE_PATH = "backend/tests/guards/_deadcode_baseline.py"
_COUNT = re.compile(r"^(?P<key>.*) \(x(?P<count>\d+)\)$")


def _counts(keys: object) -> Counter[str]:
    counts: Counter[str] = Counter()
    for key in keys:
        match = _COUNT.match(key)
        counts[match["key"] if match else key] += int(match["count"]) if match else 1
    return counts


def growth(base: object, candidate: object) -> list[str]:
    before, after = _counts(base), _counts(candidate)
    return [f"{key}: {before[key]} -> {count}" for key, count in sorted(after.items()) if count > before[key]]


def _base_baseline() -> set[str] | None:
    shown = subprocess.run(["git", "show", f"{BASE_REF}:{BASELINE_PATH}"], cwd=BACKEND, capture_output=True,
                           text=True, check=False)
    if shown.returncode:
        return None
    namespace: dict[str, object] = {"__name__": "base_deadcode_baseline"}
    exec(compile(shown.stdout, f"{BASE_REF}:{BASELINE_PATH}", "exec"), namespace)  # noqa: S102 - the base branch's own file
    return {entry.key for entry in namespace["DEAD_CODE_BASELINE"]}


def test_the_baseline_only_shrinks_against_the_base_branch() -> None:
    base = _base_baseline()
    if base is None:
        pytest.skip(f"{BASE_REF} is not available in this checkout")
    assert not growth(base, {entry.key for entry in DEAD_CODE_BASELINE}), \
        f"the dead-code baseline grew against {BASE_REF}: delete the code instead"


def test_mutation_a_new_or_higher_baseline_entry_is_growth() -> None:
    base = {"a.py: unused function 'f'", "b.py: unused import 'x' (x2)"}
    assert growth(base, base - {"a.py: unused function 'f'"}) == []
    assert growth(base, base | {"c.py: unused function 'g'"}) == ["c.py: unused function 'g': 0 -> 1"]
    assert growth(base, {"b.py: unused import 'x' (x3)"}) == ["b.py: unused import 'x': 2 -> 3"]


def test_mutation_planted_dead_code_is_reported(tmp_path: Path) -> None:
    # vulture counts a name as used anywhere in the scanned code, so the planted names must be unique.
    planted = tmp_path / "planted.py"
    planted.write_text(
        "import os as _guard_planted_os\n\n\n"
        "def _guard_planted_unused(value):\n    return value + 1\n\n\n"
        "def answer():\n    return 42\n    print('never runs')\n",
        encoding="utf-8",
    )
    found = vulture_findings(APP, planted, cwd=BACKEND)
    assert f"{planted}: unused import '_guard_planted_os'" in found
    assert f"{planted}: unused function '_guard_planted_unused'" in found
    assert f"{planted}: unreachable code after 'return'" in found
    assert comparison_problems(found, DEAD_CODE_BASELINE, what="dead code")


def test_mutation_framework_route_is_not_dead(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text(
        "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n\n"
        "@router.get('/planted')\ndef _guard_planted_route():\n    return 1\n",
        encoding="utf-8",
    )
    assert not [key for key in vulture_findings(planted, cwd=BACKEND) if "_guard_planted_route" in key]
