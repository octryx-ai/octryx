"""A test declared new must be new at the run's base: relabelled tests, bare selectors and existing methods are refused, unreadable or failing lookups are not absent files, and concrete new cases or files are accepted."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.contract_coverage_support import (  # noqa: F401
    FILE,
    NEW,
    REGRESSION,
    _clarify,
    _criterion,
    _server_pipeline,
    _submit,
)

# --- selector granularity and proven absence -----------------------------------------------------------------


def _commit_at_base(run, path: str, text: str) -> str:
    """Add ``text`` to ``path`` in the run's copy and make that commit the run's base."""
    root = Path(run.context["local_path"])
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as handle:
        handle.write(text)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "at base"], cwd=root, capture_output=True, check=True, env=env)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                          check=True).stdout.strip()
    run.context = {**dict(run.context or {}), "base_sha": base}
    return base


EXISTING_CLASS = "\nclass TestExisting:\n    def test_existing(self):\n        assert True\n"


# --- the validator's limits --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_existing_test_relabelled_new_is_refused_and_a_genuinely_new_id_is_accepted(db, tmp_path):
    run, _session, context = await _clarify(db, tmp_path)
    relabelled = [_criterion("AC1", "slugify keeps working", [(REGRESSION[2], "new")])]

    refused = await _submit(context, relabelled)

    assert refused["status"] == "refused" and refused["error"] == "invalid_output"
    assert f"{REGRESSION[2]}: is marked 'new' but already exists at the run's base" in refused["message"]
    assert "test_contract" not in dict(run.context.get("outputs") or {})
    genuinely_new = [_criterion("AC1", "truncate_words", [(NEW[0], "new"), (REGRESSION[2], "regression")])]
    assert (await _submit(context, genuinely_new))["status"] == "recorded"


@pytest.mark.asyncio
async def test_without_the_runs_copy_at_its_base_nothing_is_assumed(db, tmp_path):
    _run, _session, context = await _clarify(db, tmp_path, with_copy=False)

    answer = await _submit(context, [_criterion("AC1", "truncate_words", [(NEW[0], "new")])])

    assert answer["status"] == "refused" and answer["error"] == "needs_configuration"
    assert "working copy at its base commit could not be read" in answer["message"]


@pytest.mark.parametrize("selector", [FILE, "tests/", FILE + "::TestExisting"])
@pytest.mark.asyncio
async def test_a_selector_is_not_proof_of_a_new_test(db, tmp_path, selector):
    # An existing file, a folder, an existing class as 'new'.
    run, _session, context = await _clarify(db, tmp_path)
    if "::TestExisting" in selector:
        _commit_at_base(run, FILE, EXISTING_CLASS)
        await db.flush()

    answer = await _submit(context, [_criterion("AC1", "new behaviour", [(selector, "new")])])

    assert answer["status"] == "refused", answer
    assert "test_contract" not in dict(run.context.get("outputs") or {})


@pytest.mark.asyncio
async def test_an_unreadable_base_file_is_not_an_absent_file(db, tmp_path, monkeypatch):
    # A failing read of the base never means "new".
    from app.services.workflow_runs import safe_git

    run, _session, context = await _clarify(db, tmp_path)
    original = safe_git.git

    async def unavailable(cwd, *args, **kwargs):
        if args[0] == "show":
            return 1, "", "git_unavailable"
        return await original(cwd, *args, **kwargs)

    monkeypatch.setattr(safe_git, "git", unavailable)
    answer = await _submit(context, [_criterion("AC1", "new behaviour", [(NEW[0], "new")])])
    assert answer["status"] == "refused" and answer["error"] == "needs_configuration", answer
    assert "test_contract" not in dict(run.context.get("outputs") or {})


@pytest.mark.asyncio
async def test_a_failing_tree_lookup_is_not_an_absent_file(db, tmp_path, monkeypatch):
    from app.services.workflow_runs import safe_git

    _run, _session, context = await _clarify(db, tmp_path)
    original = safe_git.git

    async def timeout(cwd, *args, **kwargs):
        if args[0] == "ls-tree":
            return 1, "", "git_unavailable"
        return await original(cwd, *args, **kwargs)

    monkeypatch.setattr(safe_git, "git", timeout)
    answer = await _submit(context, [_criterion("AC1", "a new file", [("tests/test_words.py", "new")])])
    assert answer["status"] == "refused" and answer["error"] == "needs_configuration", answer


@pytest.mark.parametrize(("selector", "existing_class"), [
    (NEW[0], False),                                                  # a new test function in an existing file
    (f"{FILE}::TestExisting::test_truncates_words", True),            # a new method in an existing class
    (f"{FILE}::TestTruncateWords::test_truncates_words", False),      # a new method in a new class
    ("tests/test_words.py::test_truncates_words", False),             # a test in a new file
    ("tests/test_words.py", False),                                   # a provably new file
])
@pytest.mark.asyncio
async def test_a_concrete_new_test_case_or_a_new_file_is_accepted(db, tmp_path, selector, existing_class):
    run, _session, context = await _clarify(db, tmp_path)
    if existing_class:
        _commit_at_base(run, FILE, EXISTING_CLASS)
        await db.flush()

    criteria = [_criterion("AC1", "truncate_words", [(selector, "new")]),
                _criterion("AC2", "existing behaviour keeps working", [(test, "regression") for test in REGRESSION])]
    answer = await _submit(context, criteria)

    assert answer["status"] == "recorded", answer


@pytest.mark.parametrize("selector", [f"{FILE}::TestExisting::test_existing", f"{FILE}::helper_not_a_test"])
@pytest.mark.asyncio
async def test_an_existing_method_or_a_non_test_name_is_refused(db, tmp_path, selector):
    run, _session, context = await _clarify(db, tmp_path)
    _commit_at_base(run, FILE, EXISTING_CLASS)
    await db.flush()

    answer = await _submit(context, [_criterion("AC1", "new behaviour", [(selector, "new")])])

    assert answer["status"] == "refused" and answer["error"] == "invalid_output", answer


@pytest.mark.asyncio
async def test_existing_selectors_stay_valid_as_regression(db, tmp_path):
    run, _session, context = await _clarify(db, tmp_path)
    _commit_at_base(run, FILE, EXISTING_CLASS)
    await db.flush()
    regression = [(FILE, "regression"), (f"{FILE}::TestExisting", "regression"), (REGRESSION[0], "regression")]

    answer = await _submit(context, [_criterion("AC1", "truncate_words", [(NEW[0], "new")]),
                                     _criterion("AC2", "existing behaviour", regression)])

    assert answer["status"] == "recorded", answer
