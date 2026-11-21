"""Tests for panel agent management: knowledge/approval pagination, agent launch, transitional detection, and filter utilities."""

import asyncio
import uuid

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.engine import AgentEvent, _filter_tool_definitions, _infer_repo_tool_args
from app.models import AgentDefinition, AgentStep, Message, User
from app.services.sample_workspace_bootstrap.sample_agents import DOCUMENT_UPDATER_DEFINITION
from app.services.session import turn_runner
from tests.conftest import ADMIN_PASSWORD


async def _create_document_updater_agent(db) -> AgentDefinition:
    owner = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    definition = DOCUMENT_UPDATER_DEFINITION
    agent = AgentDefinition(
        id=str(uuid.uuid4()), owner_id=owner.id, name=definition["name"], description=definition["description"],
        goal=definition["goal"], agent_type=definition["agent_type"], thinking_level=definition["thinking_level"],
        branch_prefix="octryx", system_prompt=definition["system_prompt"], output_prompt=definition["output_prompt"],
        is_active=True,
    )
    db.add(agent)
    await db.flush()
    for index, step in enumerate(definition["steps"], start=1):
        db.add(AgentStep(
            id=str(uuid.uuid4()), agent_id=agent.id, position=index, name=step["name"], step_type=step["step_type"],
            instructions=step["instructions"], success_criteria=step["success_criteria"],
            allowed_tools=step.get("allowed_tools") or [], is_enabled=True,
        ))
    await db.commit()
    return agent


def _stub_turn_runner_run_agent(monkeypatch, observed: dict) -> None:
    async def fake_run_agent(
        *,
        session_id,
        user_message,
        user_id,
        project_id,
        agent_type,
        db,
        runtime_target_id=None,
        thinking_level=None,
        agent_definition=None,
        run_origin=None,
    ):
        observed["agent_type"] = agent_type
        observed["thinking_level"] = thinking_level
        observed["agent_definition"] = agent_definition
        await asyncio.sleep(0.05)
        assistant_message = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="assistant",
            content="Document updater run completed.",
            model="stepfun/step-3.5-flash:free",
        )
        db.add(assistant_message)
        await db.commit()
        yield AgentEvent(role="assistant", content="Document updater run completed.")

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)


def _assert_observed_document_updater_definition(observed: dict) -> None:
    assert observed["agent_type"] == "change"
    assert observed["thinking_level"] == "deep"
    assert observed["agent_definition"]["name"] == "Document Updater"
    assert observed["agent_definition"]["branchPrefix"] == "octryx"
    assert observed["agent_definition"]["steps"][0]["allowedTools"]
    assert [step["name"] for step in observed["agent_definition"]["steps"]] == [
        "Collect changes",
        "Derive documentation needs",
        "Update Confluence",
    ]
    assert observed["agent_definition"]["steps"][2]["allowedTools"] == [
        "list_confluence_pages",
        "get_confluence_page",
        "update_confluence_page",
        "create_confluence_page",
    ]
    assert "Execute the following ordered steps" in observed["agent_definition"]["prompt"]


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_a_document_updater_agent_can_launch_chat(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    agent = await _create_document_updater_agent(db)

    observed = {}
    _stub_turn_runner_run_agent(monkeypatch, observed)

    send_resp = await client.post(
        "/admin/chat/api/send",
        json={
            "prompt": "Update the affected confluence pages",
            "agent_id": agent.id,
        },
    )
    assert send_resp.status_code == 200
    payload = send_resp.json()
    assert payload["selectedAgentId"] == agent.id
    assert payload["selectedAgentName"] == "Document Updater"
    assert payload["selectedSession"]["status"] == "running"
    for _ in range(20):
        if observed:
            break
        await asyncio.sleep(0.05)
    _assert_observed_document_updater_definition(observed)

    session_id = payload["selectedSession"]["id"]
    for _ in range(20):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session_id}")
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break
    assert final_payload["selectedSessionIsRunning"] is False
    assert final_payload["selectedMessages"][-1]["content"] == "Document updater run completed."


def test_filter_tool_definitions_by_allowed_tools():
    definitions = [
        {"function": {"name": "prepare_bitbucket_repository"}},
        {"function": {"name": "write_workspace_file"}},
        {"function": {"name": "commit_and_push_repository_branch"}},
    ]
    filtered = _filter_tool_definitions(definitions, ["write_workspace_file"])
    assert [item["function"]["name"] for item in filtered] == ["write_workspace_file"]


def test_infer_repo_tool_args_uses_latest_repo_state_defaults():
    latest_repo_state = {
        "local_path": "/workspace/repos/acme-orders-catalog-plugin",
        "repo_readme_path": "/workspace/repos/acme-orders-catalog-plugin/README.md",
        "branch_name": "octryx/readme-acme-orders-catalog-plugin",
    }

    analyze_args = _infer_repo_tool_args("analyze_workspace_repository", {}, latest_repo_state)
    write_args = _infer_repo_tool_args("write_workspace_file", {"content": "# README"}, latest_repo_state)
    commit_args = _infer_repo_tool_args(
        "commit_and_push_repository_branch", {"commit_message": "docs: update"}, latest_repo_state
    )
    relative_write_args = _infer_repo_tool_args(
        "write_workspace_file", {"path": "application-center/README.md", "content": "# Child"}, latest_repo_state
    )
    relative_read_args = _infer_repo_tool_args("read_workspace_file", {"path": "README.md"}, latest_repo_state)

    assert analyze_args["path"] == latest_repo_state["local_path"]
    assert write_args["path"] == latest_repo_state["repo_readme_path"]
    assert commit_args["local_path"] == latest_repo_state["local_path"]
    assert commit_args["branch_name"] == latest_repo_state["branch_name"]
    assert relative_write_args["path"] == "/workspace/repos/acme-orders-catalog-plugin/application-center/README.md"
    assert relative_read_args["path"] == latest_repo_state["repo_readme_path"]


def test_infer_repo_tool_args_keeps_workspace_relative_paths_workspace_relative(monkeypatch, tmp_path):
    workspace_root = tmp_path / "workspace"
    repo_root = workspace_root / "var" / "repos" / "bitbucket" / "SHOP" / "acme-orders-catalog-plugin"
    repo_root.mkdir(parents=True)
    monkeypatch.setattr(engine_module, "WORKSPACE_ROOT", workspace_root)

    inferred = _infer_repo_tool_args(
        "list_workspace_directory",
        {"path": "var/repos/bitbucket/SHOP"},
        {
            "local_path": str(repo_root),
            "relative_path": "var/repos/bitbucket/SHOP/acme-orders-catalog-plugin",
        },
    )

    assert inferred["path"] == str((workspace_root / "var" / "repos" / "bitbucket" / "SHOP").resolve())
