"""Controls audit: every block explains itself. A denial of the run's tool policy and a pause
come from the prompt catalog ("<what>. <why>. Next: <step>."), never from a string in the code; this guard keeps it
so."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.prompt_catalog import seed_prompt_set
from app.services.prompt_catalog.seeds.run import SPECS
from app.services.workflow_runs.protected_paths import _MESSAGES

APP = Path(__file__).resolve().parents[1] / "app" / "services" / "workflow_runs" / "octryx"
# A Workspace admin writes the role's command rule text itself (Workspace › Roles): its own words are the reason.
ADMIN_TEXTS = {"role_denied"}


def _calls(path: Path, name: str) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "id", "") == name]


def test_every_denial_of_the_run_tool_policy_reads_its_text_from_the_catalog():
    loose = []
    for call in _calls(APP / "tool_policy.py", "_deny"):
        message = call.args[1] if len(call.args) > 1 else None
        catalog = isinstance(message, ast.Call) and getattr(message.func, "id", "") == "run_text"
        if not catalog and not (isinstance(message, ast.Name) and message.id in ADMIN_TEXTS):
            loose.append(f"tool_policy.py:{call.lineno}")
    assert loose == [], f"a denial without a catalog text (run.block.*): {loose}"


def test_every_block_and_pause_text_names_the_next_step():
    keys = [spec for spec in SPECS if spec.key.startswith(("run.block.", "run.pause.", "run.shell.strict_refused"))]
    assert len(keys) >= 15
    missing = [spec.key for spec in keys if "Next:" not in spec.seed]
    assert missing == []


def test_every_protected_path_kind_reads_with_a_next_step():
    prompts = seed_prompt_set()
    for kind, text in _MESSAGES.items():
        rendered = prompts.render("run.block.protected", detail=text.format(path="x.py", title="Fix"))
        assert "Next:" in rendered, kind


def test_a_confirmed_test_says_who_bound_it():
    """In class S nobody confirms the reproduction test, the run binds its own; "a person confirmed" appears only
    when a person did."""
    from app.services.workflow_runs.protected_paths import KIND_CONFIRMED_TEST, protected_message
    from app.services.workflow_runs.test_runs import confirm_tests, confirmed_by

    person = protected_message(KIND_CONFIRMED_TEST, "tests/test_pricing.py", "Minimal fix")
    own = protected_message(KIND_CONFIRMED_TEST, "tests/test_pricing.py", "Minimal fix", "run")
    assert "a person confirmed" in person and "a person" not in own
    assert "the reproduction test this run submitted" in own and "'Minimal fix'" in own
    prompts = seed_prompt_set()
    assert all("Next:" in prompts.render("run.block.protected", detail=text) for text in (person, own))
    run = SimpleNamespace(context={})
    assert confirmed_by(run) == "person"  # before any confirmation
    confirm_tests(run, ["tests/test_pricing.py::test_vat"], by="run")
    assert confirmed_by(run) == "run"
    confirm_tests(run, ["tests/test_pricing.py::test_vat"])  # a person confirmed the contract later
    assert confirmed_by(run) == "person"


@pytest.mark.asyncio
@pytest.mark.parametrize(("reason", "detail", "expected"), [
    ("budget_limit", {"keys": ["cost"]}, "used up its budget (cost)"),
    ("loop_limit", {"edge_id": "rework", "used": 2, "limit": 2}, "the work went back 2 of 2 times"),
    ("needs_configuration", {}, "Next:"),
])
async def test_a_pause_without_its_own_text_gets_the_catalogs(db, reason, detail, expected):
    from app.services.workflow_runs.limits import pause_run
    from app.services.workflow_runs.records import new_chat_session, start_run
    from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased, run_workspace

    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, phased_definition()),
                          project_id=workspace_id, session=session)
    await pause_run(db, run, reason=reason, actor_id=None, detail=dict(detail))
    message = run.node_state["pause"]["message"]
    assert expected in message and "Next:" in message


def test_every_pause_reason_has_its_own_catalog_text_for_people():
    """The attention overview, the inbox and the timeline read why a run paused and what to do next from the
    catalog, for every reason (not a few texts and "a limit was reached" for the rest)."""
    from app.services.prompt_catalog.registry import prompt_key_registry
    from app.services.workflow_runs.limits import pause_message
    from app.services.workflow_runs.states import PAUSE_REASONS

    registry = prompt_key_registry()
    assert [reason for reason in PAUSE_REASONS if f"run.pause.{reason}" not in registry] == []
    assert "Next:" in pause_message(None, "evidence_unresolved", {})
    assert pause_message(None, "evidence_unresolved", {"message": "Its own words."}) == "Its own words."
