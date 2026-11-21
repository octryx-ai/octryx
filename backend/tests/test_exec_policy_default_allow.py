"""Defaults must work: a stored allow list never hides a default added later.

When ``cd`` and ``grep`` join the read-only defaults, a global exec policy row holding a full copy of the old list
would otherwise keep refusing ``cd <repo>; git status`` until an admin edits the row by hand. The effective list is
the stored list plus every current default the admin did not explicitly remove.
"""

from __future__ import annotations

import pytest

from app.services.command_safety import reading, writing
from app.services.exec_policy import policy_config
from app.services.exec_policy.service import get_effective_exec_policy_config
from tests.agent_definition_revision_fixtures import make_project
from tests.phased_workflow_fixtures import admin_user

COMMANDS = "diagnosis_read_only_commands"


def _body(view: dict, **lists) -> dict:
    return {"checks": {item["key"]: item["enabled"] for item in view["checks"]},
            "llm_risk": {key: view["llm_risk"][key] for key in ("timeout_seconds", "review_threshold",
                                                                 "deny_threshold")},
            "lists": {**view["lists"], **lists}}


@pytest.mark.asyncio
async def test_the_admin_removes_and_adds_and_a_later_default_still_arrives(db, monkeypatch):
    admin = await admin_user(db)
    view = await reading.platform_settings(db)
    commands = [item for item in view["lists"]["commands"] if item != "cd"] + ["tree"]
    saved = await writing.save_platform_settings(db, _body(view, commands=commands), actor_id=admin.id)
    assert "cd" not in saved["lists"]["commands"] and "tree" in saved["lists"]["commands"]
    origins = saved["list_origins"]["commands"]
    assert "cd" in origins["removed_defaults"] and "tree" not in origins["defaults"]  # the page tells them apart

    # A later release adds a default: it reaches the platform without anyone editing the stored list.
    monkeypatch.setitem(policy_config.DEFAULT_EXEC_POLICY_CONFIG, COMMANDS,
                        [*policy_config.DEFAULT_EXEC_POLICY_CONFIG[COMMANDS], "stat"])
    effective = await get_effective_exec_policy_config(db)
    assert "stat" in effective[COMMANDS] and "tree" in effective[COMMANDS] and "cd" not in effective[COMMANDS]


@pytest.mark.asyncio
async def test_a_workspace_override_keeps_its_removals_and_gets_new_defaults(db, monkeypatch):
    admin = await admin_user(db)
    project = await make_project(db)
    platform = await reading.platform_settings(db)
    commands = [item for item in platform["lists"]["commands"] if item != "find"]
    await writing.save_workspace_settings(db, project, {"mode": "override", "settings": _body(
        platform, commands=commands)}, actor_id=admin.id)
    monkeypatch.setitem(policy_config.DEFAULT_EXEC_POLICY_CONFIG, COMMANDS,
                        [*policy_config.DEFAULT_EXEC_POLICY_CONFIG[COMMANDS], "stat"])
    effective = await get_effective_exec_policy_config(db, project_id=project.id)
    assert "find" not in effective[COMMANDS] and "stat" in effective[COMMANDS]
