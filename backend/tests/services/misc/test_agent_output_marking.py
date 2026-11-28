"""Anti-slop E: every outlet that sends agent-written text carries one marker line naming the responsible person."""

from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.models import AuditLog, CodeRepository, User
from app.services.ai_marking import MARKER_PREFIX, MarkingFacts, marker_line, marking_facts, storage_marker
from app.services.ai_marking_channels import marked_message, reaches_others
from app.services.ai_marking_responsible import responsible_name
from app.services.ai_marking_tools import MARKED_TOOLS, mark_fields
from app.services.pr_review_bot.bot_user import ACCOUNT_TYPE_REVIEW_BOT
from app.services.work_item_analysis.reporter_questions import INTRO, comment_body
from app.time_utils import utc_now
from app.tools.context import ToolContext
from tests.agent_definition_revision_fixtures import make_project
from tests.phased_workflow_fixtures import join_workspace
from tests.services.secure_work.test_servicenow_intake_api import _analysed_item, sn  # noqa: F401 - sn is a fixture

FACTS = MarkingFacts(responsible="Run Owner", model="claude-haiku-5-5", run_key="OCX-14")
LINE = marker_line(FACTS)


# --- a) the marked write tools -----------------------------------------------------------------------------------


@pytest.mark.parametrize("tool", sorted(MARKED_TOOLS))
def test_each_marked_tool_gets_the_line_in_its_text_fields_once(tool):
    marked = MARKED_TOOLS[tool]
    params = {"other": "kept", **{field: "Agent text" for field in marked.fields}}
    once = mark_fields(tool, params, FACTS)

    expected = f"<p>Agent text</p>{storage_marker(FACTS)}" if marked.storage else f"Agent text\n\n{LINE}"
    assert once["other"] == "kept"
    assert all(once[field] == expected for field in marked.fields)
    assert mark_fields(tool, once, FACTS) == once
    assert mark_fields(tool, params, None) == params


@pytest.mark.parametrize("tool", sorted(MARKED_TOOLS))
def test_a_created_object_carries_the_line_without_text_and_an_update_without_text_is_untouched(tool):
    marked = MARKED_TOOLS[tool]
    result = mark_fields(tool, {"id": "1"}, FACTS)

    if marked.always:
        assert result == {"id": "1", marked.fields[0]: storage_marker(FACTS) if marked.storage else LINE}
    else:
        assert result == {"id": "1"}


@pytest.mark.parametrize("tool", sorted(name for name, marked in MARKED_TOOLS.items() if marked.storage))
def test_a_confluence_storage_body_gets_the_xhtml_line(tool):
    field = MARKED_TOOLS[tool].fields[0]
    once = mark_fields(tool, {field: "<p>Doc</p>"}, FACTS)

    assert once[field] == f"<p>Doc</p>{storage_marker(FACTS)}"
    assert mark_fields(tool, once, FACTS) == once


def test_an_unlisted_tool_is_never_marked():
    assert mark_fields("read_jira_ticket", {"body": "Agent text"}, FACTS) == {"body": "Agent text"}


# --- b) the registry marks before the governed checks -----------------------------------------------------------


async def _user(db, display_name: str, *, account_type: str = "human") -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(username=f"user-{suffix}", email=f"user-{suffix}@example.test", password_hash="x",
                display_name=display_name, account_type=account_type)
    db.add(user)
    await db.flush()
    return user


def _context(db, user_id: str) -> ToolContext:
    return ToolContext(user_id=user_id, project_ids=[], roles=[], session_id="no-run", project_config={}, db=db)


@pytest.mark.asyncio
async def test_the_approval_sees_the_marked_arguments(db, monkeypatch):
    import app.tools.registry as registry

    caller = await _user(db, "Run Owner")
    seen: list[dict] = []

    async def gate(tool_name, params, context):
        seen.append(params)
        return {"error": "blocked for the test"}

    monkeypatch.setattr(registry, "_run_governed_tool_checks", gate)
    result = await registry.execute_tool("add_jira_comment", {"ticket_id": "OPS-2", "body": "Done"},
                                         _context(db, caller.id))

    assert result == {"error": "blocked for the test"}
    assert seen == [{"ticket_id": "OPS-2", "body": "Done\n\n— Written by an agent (octryx) — responsible: Run Owner."}]


@pytest.mark.asyncio
async def test_the_plugin_path_dispatches_the_marked_arguments(db, monkeypatch):
    import app.tools.registry as registry

    caller = await _user(db, "Run Owner")
    seen: list[dict] = []

    async def dispatch(tool_name, params, context):
        seen.append(params)
        return {"status": "comment_added"}

    monkeypatch.setattr(registry, "_execute_tool_with_plugins", dispatch)
    await registry.execute_tool_with_plugins("add_jira_comment", {"ticket_id": "OPS-2", "body": "Done"},
                                             _context(db, caller.id))

    assert seen[0]["body"].endswith("— responsible: Run Owner.")


# --- c) who is responsible ---------------------------------------------------------------------------------------


def _run(project_id: str, requested_by: str, **fields) -> SimpleNamespace:
    return SimpleNamespace(**{"project_id": project_id, "requested_by": requested_by, "responsible_user_id": None,
                              "repository": None, "context": {}, **fields})


async def _workspace_with_admin(db) -> tuple[str, User]:
    project = await make_project(db)
    admin = await _user(db, "Workspace Admin")
    await join_workspace(db, admin, project.id, role="admin")
    return project.id, admin


@pytest.mark.asyncio
async def test_the_runs_responsible_wins_then_its_requester(db):
    project_id, _admin = await _workspace_with_admin(db)
    owner, requester = await _user(db, "Run Owner"), await _user(db, "Run Requester")

    assert await responsible_name(db, run=_run(project_id, requester.id, responsible_user_id=owner.id)) == "Run Owner"
    assert await responsible_name(db, run=_run(project_id, requester.id)) == "Run Requester"


@pytest.mark.asyncio
async def test_a_non_human_requester_hands_over_to_a_workspace_admin(db):
    project_id, _admin = await _workspace_with_admin(db)
    service = await _user(db, "Service Account", account_type="service")

    assert await responsible_name(db, run=_run(project_id, service.id)) == "Workspace Admin"


@pytest.mark.asyncio
async def test_a_review_bot_run_names_its_commenter(db):
    project_id, _admin = await _workspace_with_admin(db)
    bot = await _user(db, "Review Bot", account_type=ACCOUNT_TYPE_REVIEW_BOT)
    commenter = await _user(db, "Commenter")
    run = _run(project_id, bot.id, repository="github:acme/payments",
               context={"pr_review": {"requested_by": commenter.id}})

    assert await responsible_name(db, run=run) == "Commenter"


@pytest.mark.asyncio
async def test_an_automatic_review_names_who_switched_the_bot_on(db):
    project_id, _admin = await _workspace_with_admin(db)
    bot = await _user(db, "Review Bot", account_type=ACCOUNT_TYPE_REVIEW_BOT)
    enabler, switcher = await _user(db, "Bot Enabler"), await _user(db, "Bot Switcher")
    record = CodeRepository(project_id=project_id, provider="github", name="acme/payments", is_active=True,
                            repo_root="/srv/repos")
    db.add(record)
    await db.flush()
    now = utc_now()
    for user, trigger, at in ((enabler, "webhook", now - timedelta(minutes=5)), (switcher, "off", now)):
        db.add(AuditLog(user_id=user.id, action="pr_review_bot.settings_changed", resource_type="code_repository",
                        resource_id=record.id, details={"settings": {"trigger": trigger}}, created_at=at))
    await db.flush()

    assert await responsible_name(db, run=_run(project_id, bot.id, repository="github:acme/payments")) == "Bot Enabler"
    assert await responsible_name(db, run=_run(project_id, bot.id, repository="github:acme/other")) == (
        "Workspace Admin")


@pytest.mark.asyncio
async def test_a_tool_call_outside_a_run_names_the_calling_user(db):
    caller = await _user(db, "Run Owner")
    service = await _user(db, "Service Account", account_type="service")

    assert await marking_facts(_context(db, caller.id)) == MarkingFacts(responsible="Run Owner")
    assert await marking_facts(_context(db, service.id)) is None


# --- d) channels -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("channel_type", "others"), [
    ("", False), (None, False), ("personal", False), ("im", False), ("Private", False), ("direct", False),
    ("dm", False), ("channel", True), ("groupChat", True), ("group", True), ("supergroup", True)])
def test_only_conversations_beyond_the_requester_are_marked(channel_type, others):
    assert reaches_others(channel_type) is others


@pytest.mark.asyncio
async def test_a_channel_message_names_the_user_else_the_fallback_else_stays_as_is(db):
    sender = await _user(db, "Run Owner")

    assert await marked_message(db, "Answer", user_id=sender.id, fallback_name="Chat Name") == (
        "Answer\n\n— Written by an agent (octryx) — responsible: Run Owner.")
    assert await marked_message(db, "Answer", user_id=None, fallback_name=" Chat Name ") == (
        "Answer\n\n— Written by an agent (octryx) — responsible: Chat Name.")
    assert await marked_message(db, "Answer", user_id=None) == "Answer"


@pytest.mark.asyncio
@pytest.mark.parametrize(("output", "marked"), [({"response": "The agent's answer"}, True),
                                                ({"processed": 3}, False)])
async def test_task_output_to_a_channel_is_marked_only_with_an_agent_response(db, monkeypatch, output, marked):
    from app.plugins import plugin_manager
    from app.scheduler.output.channel_output import deliver_task_output_channel
    from app.services.channel_config import ChannelConfigService

    owner = await _user(db, "Task Owner")
    sent: list[str] = []

    class Plugin:
        async def send_message(self, target, message, **_kwargs):
            sent.append(message)
            return True

    async def get_model(_db, channel_id):
        return SimpleNamespace(id=channel_id, name="team", enabled=True, plugin_id="slack",
                               config={"default_target": "#team"})

    monkeypatch.setattr(ChannelConfigService, "get_model", staticmethod(get_model))
    monkeypatch.setattr(plugin_manager, "get_channel", lambda _channel_id: Plugin())
    task = SimpleNamespace(name="Nightly", owner_id=owner.id, config={"output_channel_id": 7})
    task_run = SimpleNamespace(id="r1", status="completed", session_id=None, error=None, output=output)

    assert (await deliver_task_output_channel(db, task, task_run))["status"] == "sent"
    assert sent[0].endswith("— responsible: Task Owner.") is marked
    assert sent[0].count(MARKER_PREFIX) == int(marked)


# --- e) reporter questions ---------------------------------------------------------------------------------------


def test_reporter_questions_end_with_the_line_on_cloud_and_data_center():
    cloud = comment_body(["Which version?"], "acc-1", cloud=True, marker=LINE)
    assert cloud["content"][-1] == {"type": "paragraph", "content": [{"type": "text", "text": LINE}]}
    assert cloud["content"][:-1] == comment_body(["Which version?"], "acc-1", cloud=True)["content"]

    server = comment_body(["Which version?"], "reporter", cloud=False, marker=LINE)
    assert server == f"[~reporter] {INTRO}\n* Which version?\n\n{LINE}"
    assert comment_body(["Which version?"], "reporter", cloud=False) == f"[~reporter] {INTRO}\n* Which version?"


# --- f) ServiceNow work note ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_work_note_preview_names_the_confirming_user(db, sn):  # noqa: F811
    from app.services.secure_work.servicenow.worknote import send_worknote

    item, admin = await _analysed_item(db, servicenow_worknote_mode="table_api")
    preview = await send_worknote(db, item=item, user=admin, note_at=None, confirm=False)

    assert preview["state"] == "needs_confirmation"
    assert preview["preview"]["text"].endswith(f"\n\n— Written by an agent (octryx) — responsible: {admin.display_name}.")
    assert sn.writes == []


@pytest.mark.asyncio
async def test_platform_text_for_a_run_is_not_marked(monkeypatch):
    from app.services import ai_marking_tools
    from app.services.ai_marking_tools import marked_arguments, platform_text

    async def facts(_context):
        return FACTS

    monkeypatch.setattr(ai_marking_tools, "marking_facts", facts)
    params = {"ticket_id": "OCX-1", "body": "Follow-up issue: OCX-2"}
    with platform_text():
        assert await marked_arguments("add_jira_comment", params, None) == params
    assert (await marked_arguments("add_jira_comment", params, None))["body"].endswith(LINE)
