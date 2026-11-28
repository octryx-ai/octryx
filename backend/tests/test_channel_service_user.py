"""Contract: an unmapped channel sender runs as its channel's service user."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, Role, Session, User, UserProject, UserRole
from app.plugins.channels.teams_plugin import TeamsPlugin
from app.services.channel_config import ChannelConfigService
from app.services.channel_config.service_user import service_username
from app.services.channel_router_runtime import ChannelMessageRouter
from app.services.channel_router_runtime.approval_commands import SENDER_UNRESOLVED_REPLY
from app.services.channel_router_runtime.run_as import SERVICE_USER_NOT_CONFIGURED_REPLY
from tests.scripted_pool_support import scripted_turns  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_turns")


def _router(db) -> ChannelMessageRouter:
    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    router = ChannelMessageRouter()
    router._session_factory = _Factory()
    return router


@pytest.fixture
def agent_turns(scripted_turns) -> list[dict]:  # noqa: F811 - the imported fixture
    scripted_turns["default"] = "Status is green."
    return scripted_turns["calls"]


async def _teams_channel(db, *, require_registered_user: bool = False) -> tuple[int, str, TeamsPlugin]:
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    channel = await ChannelConfigService.create(
        db, plugin_id="msteams", name=f"Teams {uuid.uuid4().hex[:6]}", project_id=project.id, enabled=False, config={}
    )
    plugin = TeamsPlugin(
        "msteams",
        {
            "__channel_id": str(channel.id),
            "__channel_name": channel.name,
            "__channel_project_id": project.id,
            "require_registered_user": require_registered_user,
            "dm_policy": "open",
        },
    )
    plugin.sent = []

    async def _send(target: str, content: str, **kwargs) -> bool:
        plugin.sent.append(content)
        return True

    plugin.send_message = _send
    return channel.id, project.id, plugin


async def _teams_message(plugin: TeamsPlugin, sender: str, text: str) -> dict:
    await plugin.receive_webhook(
        {
            "type": "message",
            "text": text,
            "from": {"id": sender},
            "conversation": {"conversationType": "personal", "id": f"conv-{sender}"},
            "serviceUrl": "https://smba.example/",
        }
    )
    message = await plugin.receive_message()
    assert message is not None
    return message


async def _service_user(db, channel_id: int) -> User:
    return (await db.execute(select(User).where(User.username == service_username(channel_id)))).scalar_one()


async def _global_roles(db, user_id: str) -> set[str]:
    rows = await db.execute(select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id))
    return set(rows.scalars().all())


@pytest.mark.asyncio
async def test_unmapped_teams_sender_runs_as_the_channel_service_user(db, agent_turns):
    channel_id, project_id, plugin = await _teams_channel(db)
    service_user = await _service_user(db, channel_id)
    assert (service_user.account_type, service_user.auth_source, service_user.is_active) == (
        "channel_service",
        "channel_service",
        True,
    )
    assert await _global_roles(db, service_user.id) == {"viewer"}
    memberships = (await db.execute(select(UserProject).where(UserProject.user_id == service_user.id))).scalars().all()
    assert [(m.project_id, m.role) for m in memberships] == [(project_id, "viewer")]

    router = _router(db)
    await router._handle_message(str(channel_id), plugin, await _teams_message(plugin, "unmapped-1", "status please"))

    assert [(turn["user_id"], turn["project_id"]) for turn in agent_turns] == [(service_user.id, project_id)]
    session = await db.get(Session, agent_turns[0]["session_id"])
    assert session.user_id == service_user.id
    assert plugin.sent == ["Status is green."]

    await router._handle_message(
        str(channel_id), plugin, await _teams_message(plugin, "unmapped-1", f"approve {uuid.uuid4()}")
    )
    assert plugin.sent[-1] == SENDER_UNRESOLVED_REPLY
    assert len(agent_turns) == 1


@pytest.mark.asyncio
async def test_without_a_valid_service_user_the_channel_refuses_and_setup_repairs_it(db, agent_turns):
    channel_id, _project_id, plugin = await _teams_channel(db)
    router = _router(db)

    # Someone elevated the service user: it is refused, not used.
    service_user = await _service_user(db, channel_id)
    admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    db.add(UserRole(user_id=service_user.id, role_id=admin_role.id))
    await db.commit()
    await router._handle_message(str(channel_id), plugin, await _teams_message(plugin, "unmapped-2", "hello"))
    assert plugin.sent == [SERVICE_USER_NOT_CONFIGURED_REPLY]
    assert SERVICE_USER_NOT_CONFIGURED_REPLY.startswith("channel_service_user_not_configured:")

    # Saving the channel is the setup step: idempotent, it restores exactly the viewer role.
    await ChannelConfigService.update(db, channel_id, name="Teams repaired")
    assert await _global_roles(db, service_user.id) == {"viewer"}
    await router._handle_message(str(channel_id), plugin, await _teams_message(plugin, "unmapped-2", "hello"))
    assert [turn["user_id"] for turn in agent_turns] == [service_user.id]

    # A channel that never got a service user refuses; it never picks another active user.
    unset = TeamsPlugin("msteams", {"__channel_id": "987654", "__channel_project_id": "", "dm_policy": "open"})
    unset.sent = []

    async def _send(target: str, content: str, **kwargs) -> bool:
        unset.sent.append(content)
        return True

    unset.send_message = _send
    await router._handle_message("987654", unset, await _teams_message(unset, "unmapped-3", "hello"))
    assert unset.sent == [SERVICE_USER_NOT_CONFIGURED_REPLY]

    strict_id, _pid, strict = await _teams_channel(db, require_registered_user=True)
    await router._handle_message(str(strict_id), strict, await _teams_message(strict, "unmapped-4", "hello"))
    assert strict.sent == []
    assert len(agent_turns) == 1
