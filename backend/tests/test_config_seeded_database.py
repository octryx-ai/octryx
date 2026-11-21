"""Database seeding can skip the demo project, seeds the Acme orders agents with their step contracts, and init_db creates the hot-path indexes."""

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import selectinload

import app.bootstrap as bootstrap_module
from app.bootstrap import seed_database
from app.models import AgentDefinition, Project, User


@pytest.mark.asyncio
async def test_seed_database_can_skip_demo_project(db, monkeypatch):
    await db.execute(delete(Project).where(Project.name == "demo"))
    await db.commit()

    monkeypatch.setattr(bootstrap_module.settings, "seed_demo_project", False)
    try:
        await seed_database(db)
        await db.commit()
    finally:
        monkeypatch.setattr(bootstrap_module.settings, "seed_demo_project", True)

    demo_project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one_or_none()
    assert demo_project is None


async def _load_seeded_agents(db) -> list[AgentDefinition]:
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    return (
        (
            await db.execute(
                select(AgentDefinition)
                .where(
                    AgentDefinition.owner_id == admin_user.id,
                    AgentDefinition.name.in_(
                        [
                            "Document Updater",
                            "Coding agent",
                        ]
                    ),
                )
                .options(selectinload(AgentDefinition.steps))
            )
        )
        .scalars()
        .all()
    )


def _assert_document_updater_steps(document_updater: AgentDefinition) -> None:
    assert [step.name for step in document_updater.steps] == [
        "Collect changes",
        "Derive documentation needs",
        "Update Confluence",
    ]
    assert document_updater.steps[0].allowed_tools == [
        "list_recent_bitbucket_commits",
        "search_jira_tickets",
        "prepare_bitbucket_repository",
        "git_change_summary",
        "list_workspace_git_commits",
        "analyze_workspace_repository",
    ]
    assert document_updater.steps[1].allowed_tools == [
        "knowledge_search",
        "search_confluence",
        "list_confluence_pages",
        "get_confluence_page",
    ]
    assert document_updater.steps[2].allowed_tools == [
        "list_confluence_pages",
        "get_confluence_page",
        "update_confluence_page",
        "create_confluence_page",
    ]


@pytest.mark.asyncio
async def test_seeded_acme_orders_agents_have_expected_step_contracts(db):
    agents = await _load_seeded_agents(db)

    agent_by_name = {agent.name: agent for agent in agents if agent.is_active}
    assert set(agent_by_name) == {"Document Updater", "Coding agent"}

    document_updater = agent_by_name["Document Updater"]
    _assert_document_updater_steps(document_updater)

    # The coding agent is the built-in one; its mode, not its name, gives scheduled runs the work-item envelope.
    coding_delivery_agent = agent_by_name["Coding agent"]
    assert (coding_delivery_agent.builtin_key, coding_delivery_agent.execution_mode) == ("coding", "coding_delivery")
    assert coding_delivery_agent.capability_ceiling == "deliver"
    assert coding_delivery_agent.require_self_review is True
    assert "internal Agent Task" in (coding_delivery_agent.system_prompt or "")
    assert [step.name for step in coding_delivery_agent.steps] == [
        "Intake and task state",
        "Clarification gate",
        "Plan slices and gather evidence",
        "Implement and verify",
        "Review-agent gate",
        "Finalize and sync trackers",
    ]
    assert "aws_read_operation" in coding_delivery_agent.steps[0].allowed_tools
    assert "aws_read_operation" in coding_delivery_agent.steps[2].allowed_tools
    assert "aws_action_operation" in coding_delivery_agent.steps[3].allowed_tools
    assert coding_delivery_agent.steps[1].allowed_tools == [
        "get_jira_ticket",
        "update_jira_ticket",
        "todo_write",
        "todo_read",
    ]
    assert coding_delivery_agent.steps[4].step_type == "self_review"
    assert "spawn_sub_agent" in coding_delivery_agent.steps[4].allowed_tools


@pytest.mark.asyncio
async def test_init_db_creates_additional_hot_path_indexes(db):
    approval_indexes = {row[1] for row in (await db.execute(text("PRAGMA index_list('approvals')"))).all()}
    project_indexes = {row[1] for row in (await db.execute(text("PRAGMA index_list('projects')"))).all()}
    provider_indexes = {row[1] for row in (await db.execute(text("PRAGMA index_list('llm_providers')"))).all()}
    model_indexes = {row[1] for row in (await db.execute(text("PRAGMA index_list('llm_models')"))).all()}
    webhook_indexes = {row[1] for row in (await db.execute(text("PRAGMA index_list('webhooks')"))).all()}
    webhook_event_indexes = {row[1] for row in (await db.execute(text("PRAGMA index_list('webhook_events')"))).all()}

    assert "ix_approvals_status" in approval_indexes
    assert "ix_projects_created_at" in project_indexes
    assert "ix_llm_providers_created_at" in provider_indexes
    assert "ix_llm_models_last_synced_at" in model_indexes
    assert "ix_webhooks_created_at" in webhook_indexes
    assert "ix_webhook_events_status" in webhook_event_indexes
    assert "ix_webhook_events_received_at" in webhook_event_indexes
