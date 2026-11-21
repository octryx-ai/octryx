"""The chat send API enforces summary domain coverage before it finalizes."""

import asyncio

import pytest

import app.agent.engine as engine_module
from tests.conftest import ADMIN_PASSWORD


def _summary_responses():
    """Jira first, an early finish attempt, then Bitbucket and Confluence, then the final summary."""
    return [
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "call-jira",
                    "function": {
                        "name": "search_jira_tickets",
                        "arguments": '{"query": "updated >= -1d", "limit": 10}',
                    },
                }
            ],
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        },
        {
            "content": "I can finalize the summary now.",
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        },
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "call-bitbucket",
                    "function": {
                        "name": "list_recent_bitbucket_commits",
                        "arguments": '{"days": 1, "per_repo_limit": 10}',
                    },
                },
                {
                    "id": "call-confluence",
                    "function": {
                        "name": "search_confluence",
                        "arguments": '{"cql": "lastmodified >= now(\'-1d\')", "limit": 20}',
                    },
                },
            ],
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 15, "completion_tokens": 4, "total_tokens": 19},
        },
        {
            "content": "Final summary across Jira, Bitbucket, and Confluence.",
            "tool_calls": None,
            "model": "claude-haiku-4.5",
            "usage": {"prompt_tokens": 18, "completion_tokens": 5, "total_tokens": 23},
        },
    ]


def _tool_result(tool_name):
    if tool_name == "search_jira_tickets":
        return {
            "query": "updated >= -1d",
            "results": [{"ticket_id": "OCX-1", "summary": "Fix docs", "status": "Done", "updated": "2026-03-24"}],
        }
    if tool_name == "list_recent_bitbucket_commits":
        return {
            "days": 1,
            "commits": [
                {
                    "project_key": "SHOP",
                    "repo_slug": "acme-orders-config",
                    "repository_label": "SHOP/acme-orders-config",
                    "display_id": "abc1234",
                    "author_name": "Alice Example",
                    "author_timestamp": 1710000000000,
                    "message": "Update health check docs",
                }
            ],
        }
    return {
        "count": 1,
        "results": [{"title": "Health check docs", "space_key": "INFRA"}],
    }


def _stub_runtime_and_tools(monkeypatch, response_queue, executed_tools):
    async def fake_resolve_control_plane_runtimes(_db, runtime_target_id=None):
        return [{"provider_name": "copilot", "model": "claude-haiku-4.5"}]

    async def fake_chat_with_runtime_fallback(*, runtimes, messages, tools, max_tokens=4096, reasoning_effort=None):
        return response_queue.pop(0), runtimes[0]

    async def fake_execute_tool_with_plugins(tool_name, tool_args, tool_context):
        executed_tools.append(tool_name)
        return _tool_result(tool_name)

    monkeypatch.setattr(engine_module, "resolve_control_plane_runtimes", fake_resolve_control_plane_runtimes)
    monkeypatch.setattr(engine_module, "_chat_with_runtime_fallback", fake_chat_with_runtime_fallback)
    monkeypatch.setattr(engine_module, "execute_tool_with_plugins", fake_execute_tool_with_plugins)


async def _seed_summary_project_with_profile(db):
    # The summary workflow plans connector tools; the execution profile gate
    # blocks it unless the project activates the required connectors.
    import uuid as _uuid

    from sqlalchemy import select as _select

    from app.models import Project, User, UserProject

    admin_user = (await db.execute(_select(User).where(User.username == "admin"))).scalars().first()
    summary_project = Project(
        id=str(_uuid.uuid4()),
        name=f"summary-coverage-{_uuid.uuid4().hex[:6]}",
        is_active=True,
        config={
            "jira_url": "https://jira.example.com",
            "bitbucket_url": "https://bitbucket.example.com",
            "confluence_url": "https://confluence.example.com",
        },
    )
    db.add(summary_project)
    db.add(UserProject(user_id=admin_user.id, project_id=summary_project.id, role="member"))
    await db.commit()
    # Domain coverage comes only from an explicit scenario profile, never from prompt words.
    from app.models import ScenarioProfile

    db.add(
        ScenarioProfile(
            id=str(_uuid.uuid4()),
            owner_id=admin_user.id,
            project_id=summary_project.id,
            name="Daily cross-source summary",
            match_config={},
            planner_config={},
            execution_config={"required_domains": ["jira", "bitbucket", "confluence"], "enforce_domain_coverage": True},
            is_active=True,
        )
    )
    await db.commit()
    return summary_project


async def _poll_until_idle(client, payload, session_id):
    final_payload = payload
    for _ in range(100):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session_id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break
    return final_payload


@pytest.mark.asyncio
@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_send_api_enforces_summary_domain_coverage_before_finalizing(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303
    response_queue = _summary_responses()
    executed_tools: list[str] = []
    _stub_runtime_and_tools(monkeypatch, response_queue, executed_tools)
    summary_project = await _seed_summary_project_with_profile(db)

    send_resp = await client.post(
        "/admin/chat/api/send",
        json={
            "prompt": "Create a daily summary from Jira, Bitbucket and Confluence for today.",
            "project_id": summary_project.id,
        },
    )
    assert send_resp.status_code == 200
    payload = send_resp.json()
    session_id = payload["selectedSession"]["id"]
    final_payload = await _poll_until_idle(client, payload, session_id)

    assert final_payload["selectedSessionIsRunning"] is False
    assert executed_tools == [
        "search_jira_tickets",
        "list_recent_bitbucket_commits",
        "search_confluence",
    ]
    assistant_contents = [
        item["content"] or "" for item in final_payload["selectedMessages"] if item["role"] == "assistant"
    ]
    assert assistant_contents[-1] == "Final summary across Jira, Bitbucket, and Confluence."
