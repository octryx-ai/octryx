"""The chat prompt names the Workspace's connected scopes and follows the person's language.

Without them a model asks the person for a ``project_key`` when asked "Which pull requests are open?", or
searches Jira without a project and misses the issue; told "Jira project CHEF ... Bitbucket
CHEF/kitchen-helper-mini", it solves both. A question in German gets a German answer.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.core.context.workspace_scopes_prompt import workspace_scopes_prompt
from app.agent.core.prompts.prompt_builder import build_minimal_personality_prompt, build_personality_prompt
from app.models import CodeRepository, ConnectorNamedConnection, Personality, Project
from app.services.prompt_catalog import render_prompt
from tests.connection_support import connect


async def _workspace(db) -> Project:
    project = Project(id=str(uuid.uuid4()), name=f"Demo Shop {uuid.uuid4().hex[:6]}")
    db.add(project)
    await db.flush()
    return project


async def _bind(db, connection_id: str, keys: list[str]) -> None:
    row = (await db.execute(select(ConnectorNamedConnection).where(ConnectorNamedConnection.id == connection_id))).scalar_one()
    row.bound_scopes = keys
    await db.flush()


@pytest.mark.asyncio
async def test_t15_t20_the_prompt_names_the_bound_project_space_and_the_default_repository(db) -> None:
    project = await _workspace(db)
    await _bind(db, await connect(db, "jira", project.id), ["CHEF"])
    await _bind(db, await connect(db, "confluence", project.id), ["CHEF"])
    await _bind(db, await connect(db, "bitbucket", project.id), ["chef/kitchen-helper-mini"])
    db.add(CodeRepository(
        id=str(uuid.uuid4()), project_id=project.id, name="CHEF/kitchen-helper-mini", repo_root="/tmp/none",
        provider="bitbucket", remote_url="http://fake-scm:8853/scm/CHEF/kitchen-helper-mini.git", default_branch="main",
    ))
    await db.flush()

    prompt = await workspace_scopes_prompt(db, project.id)

    assert prompt.startswith("## Workspace scopes")
    # The original spelling, never the binding's canonical lower case a model might copy into its call.
    assert ": project CHEF" in prompt and ": space CHEF" in prompt and ": repository CHEF/kitchen-helper-mini" in prompt
    assert "chef/kitchen-helper-mini" not in prompt
    assert "- Repository CHEF/kitchen-helper-mini (bitbucket, default branch main) — default" in prompt
    assert "instead of asking for it" in prompt
    assert "fake-" not in prompt.replace("fake-scm", ""), "never a secret or config value"
    assert len(prompt) < 600, "short: one line per connection and repository"


@pytest.mark.asyncio
async def test_a_workspace_without_bound_scopes_or_repositories_adds_nothing(db) -> None:
    project = await _workspace(db)
    await connect(db, "jira", project.id)  # unbound: serves every key, names none
    assert await workspace_scopes_prompt(db, project.id) == ""
    assert await workspace_scopes_prompt(db, None) == ""


def test_t12_the_language_line_follows_the_persons_message() -> None:
    for language in ("de", "en"):
        line = build_personality_prompt(Personality(user_id="u", language=language)).splitlines()[0]
        assert line.startswith("Respond in the language of the person's latest message")
        assert "exclusively" not in line
    assert render_prompt("personality.language.en").startswith("Respond in the language of the person's latest")
    # The minimal tier keeps the language line.
    full = build_personality_prompt(Personality(user_id="u", language="de"))
    assert build_minimal_personality_prompt(full).startswith("Respond in the language of the person's latest")


def test_t15_a_bound_key_is_shown_as_the_workspace_spells_it() -> None:
    from app.agent.core.context.workspace_scopes_prompt import original_spelling, repository_spellings

    class Repo:
        name = "kitchen-helper"
        remote_url = "http://fake-scm:8853/scm/CHEF/Kitchen-Helper-Mini.git"

    spellings = repository_spellings([Repo()])
    assert original_spelling("chef/kitchen-helper-mini", spellings) == "CHEF/Kitchen-Helper-Mini", "from the clone URL"
    assert original_spelling("chef/other", spellings) == "CHEF/other", "the project part as spelled elsewhere"
    assert original_spelling("ops", spellings) == "ops", "unknown keys stay as bound"
