"""Formatting fixes of confirmed tests: an AST-identical reformat passes on the bound fingerprint, a semantic change or an already drifted file stays refused."""

from __future__ import annotations

import copy

import pytest

from app.services.workflow_runs.test_runs import confirm_tests, confirmed_test_drift, snapshot_confirmed_tests
from app.tools.context import ToolContext
from app.tools.registry import TOOL_REGISTRY
from tests.declared_lint_and_format_only_support import (  # noqa: F401
    LONG,
    TEST_FILE,
    _copy,
    _gate_definition,
    _server_pipeline,
    _started,
)
from tests.phased_workflow_fixtures import PHASE
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

CONFIRMED = f"{TEST_FILE}::test_truncate_words_joins_kept_words"


# (b) formatting fixes of confirmed tests -----------------------------------------------------------------------------


CONFIRMED_TEST = ("from textkit import truncate_words\n\n\n"
                  "def test_truncate_words_joins_kept_words():\n" + LONG)


REFORMATTED = ("from textkit import truncate_words\n\n\n"
               "def test_truncate_words_joins_kept_words():\n"
               "    assert truncate_words(\n"
               "        'one two three four five six seven', 2\n"
               "    ) == 'one two'  # E501 fixed\n")


async def _implement_with_confirmed_test(db, tmp_path):
    implement = copy.deepcopy(PHASE)
    implement["workflow_contract"].update(capability_class="change",
                                          path_rules={"protect_confirmed_tests": True, "create": ["src/**"]})
    definition = _gate_definition([{"type": "tool_called", "params": {"tools": ["knowledge_search"]},
                                     "blocking": True, "description": "Evidence searched"}], phase_checks=[])
    definition["nodes"][1]["config"] = implement
    root = tmp_path / "copy"
    context = _copy(root)
    (root / TEST_FILE).write_text(CONFIRMED_TEST)  # written by tests first, confirmed red
    admin, session, run = await _started(db, definition, context)
    confirm_tests(run, [CONFIRMED])
    await snapshot_confirmed_tests(db, run)
    await db.commit()
    tool_context = ToolContext(user_id=admin.id, project_ids=[], roles=[], session_id=session.id,
                               project_config={}, workspace_root=str(root), db=db)
    return run, root, tool_context


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["edit_workspace_file", "write_workspace_file"])
async def test_a_semantic_change_to_a_confirmed_test_stays_refused(db, tmp_path, tool):
    run, root, context = await _implement_with_confirmed_test(db, tmp_path)
    weakened = LONG.replace("== 'one two'", "is not None")
    params = ({"path": TEST_FILE, "old_string": LONG, "new_string": weakened} if tool == "edit_workspace_file" else
              {"path": TEST_FILE, "content": CONFIRMED_TEST.replace(LONG, weakened)})

    refused = await TOOL_REGISTRY[tool].execute(params, context)

    decision = str(refused.get("coding_policy_decision"))
    assert "error" in refused and "workflow_phase_path_rule" in decision and "confirmed" in decision, refused
    assert (root / TEST_FILE).read_text() == CONFIRMED_TEST
    assert confirmed_test_drift(run) == []


# The confirmed baseline is proven before a formatting write; lint paths. ---------------------------------------


@pytest.mark.asyncio
async def test_format_refuses_a_file_that_already_drifted_from_confirmation(db, tmp_path):
    # A semantic change first, then an AST-identical reformat of the tampered content.
    run, root, context = await _implement_with_confirmed_test(db, tmp_path)
    confirmed = dict(run.context["confirmed_test_files"][CONFIRMED])
    tampered = CONFIRMED_TEST.replace("== 'one two'", "is not None")
    path = root / TEST_FILE
    path.write_text(tampered)
    assert confirmed_test_drift(run)
    new_text = tampered.replace("  # E501", "\n    # formatting")

    result = await TOOL_REGISTRY["write_workspace_file"].execute({"path": TEST_FILE, "content": new_text}, context)

    assert "error" in result, result
    assert path.read_text() == tampered  # refused before the write
    assert run.context["confirmed_test_files"][CONFIRMED] == confirmed  # the snapshot is never rebound


