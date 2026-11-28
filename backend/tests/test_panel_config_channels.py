"""Channel instances and sessions in the admin panel, and the channel router's session titles, messages and project."""

import pytest
from sqlalchemy import select

from app.models import Message, Project, Session, User
from app.services.auth import hash_password
from tests.conftest import ADMIN_PASSWORD
from tests.scripted_pool_support import scripted_turns  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_turns")


@pytest.mark.asyncio
async def test_admin_panel_can_manage_multiple_channel_instances(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    first_resp = await client.post(
        "/admin/chat/api/panel/channels",
        json={
            "plugin_id": "msteams",
            "name": "Acme Orders Teams Bot",
            "project_id": project.id,
            "enabled": False,
            "config": {"dev_mode": True, "app_id": "", "app_password": ""},
        },
    )
    assert first_resp.status_code == 200
    first = first_resp.json()
    assert first["plugin_id"] == "msteams"
    assert first["name"] == "Acme Orders Teams Bot"
    assert first["project_id"] == project.id

    second_resp = await client.post(
        "/admin/chat/api/panel/channels",
        json={
            "plugin_id": "msteams",
            "name": "Shop Teams Bot",
            "project_id": None,
            "enabled": False,
            "config": {"dev_mode": True, "app_id": "", "app_password": ""},
        },
    )
    assert second_resp.status_code == 200
    second = second_resp.json()
    assert second["plugin_id"] == "msteams"
    assert second["id"] != first["id"]

    list_resp = await client.get("/admin/chat/api/panel/channels")
    assert list_resp.status_code == 200
    channels = list_resp.json()
    teams_channels = [channel for channel in channels if channel["plugin_id"] == "msteams"]
    assert len(teams_channels) >= 2
    assert {channel["name"] for channel in teams_channels} >= {"Acme Orders Teams Bot", "Shop Teams Bot"}

    templates_resp = await client.get("/admin/chat/api/panel/channels/available")
    assert templates_resp.status_code == 200
    assert any(channel["plugin_id"] == "msteams" for channel in templates_resp.json())


@pytest.mark.asyncio
async def test_admin_panel_lists_channel_sessions_for_admins_only(client, db):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session = Session(
        user_id=admin.id,
        project_id=project.id,
        agent_type="chat",
        status="active",
        metadata_={
            "channel": "msteams",
            "channel_id": "2",
            "channel_name": "Octryx Teams",
            "channel_key": "2:teams-thread:19:abc",
            "conversation_id": "19:abc",
            "channel_type": "channel",
            "sender_id": "teams-user-1",
            "channel_session": True,
            "title": "Teams ping 1",
        },
    )
    direct_session = Session(
        user_id=admin.id,
        project_id=project.id,
        agent_type="chat",
        status="active",
        metadata_={"title": "Normal direct chat"},
    )
    db.add_all([session, direct_session])
    await db.flush()
    db.add_all(
        [
            Message(session_id=session.id, role="user", content="Teams ping 1"),
            Message(session_id=session.id, role="assistant", content="Teams reply"),
            Message(session_id=direct_session.id, role="user", content="Direct chat"),
        ]
    )
    await db.commit()

    resp = await client.get("/admin/chat/api/panel/channel-sessions")

    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload) == 1
    row = payload[0]
    assert row["id"] == session.id
    assert row["channel"] == "msteams"
    assert row["channel_name"] == "Octryx Teams"
    assert row["conversation_id"] == "19:abc"
    assert row["project_name"] == project.name
    assert row["message_count"] == 2

    viewer = User(
        username="channel-viewer",
        email="channel-viewer@example.com",
        password_hash=hash_password("testpass123"),
        is_active=True,
    )
    db.add(viewer)
    await db.commit()
    await client.post("/admin/logout")
    viewer_login = await client.post("/admin/login", data={"username": "channel-viewer", "password": "testpass123"})
    assert viewer_login.status_code == 303

    denied = await client.get("/admin/chat/api/panel/channel-sessions")
    assert denied.status_code == 403


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_channel_router_titles_new_channel_session_from_first_message(db):
    from app.services.channel_router_runtime import ChannelMessageRouter

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    router = ChannelMessageRouter()
    session_id = await router._get_or_create_session(
        db,
        channel_id="17",
        channel_key="17:user-123",
        plugin_id="msteams",
        channel_name="Acme Orders Teams Bot",
        sender_id="user-123",
        user_id=admin.id,
        project_id=project.id,
        initial_content="Daily summary for the project please",
    )
    assert session_id is not None

    session = await db.get(Session, session_id)
    assert session is not None
    assert session.project_id == project.id
    assert (session.metadata_ or {}).get("title") == "Daily summary for the project please"
    assert (session.metadata_ or {}).get("channel_id") == "17"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_channel_router_persists_user_message_and_passes_project_to_agent(db, monkeypatch, scripted_turns):  # noqa: F811
    from app.services.channel_router_runtime import ChannelMessageRouter

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()

    scripted_turns["default"] = "Knowledge map answer"

    class DummyPlugin:
        plugin_id = "msteams"
        config = {"__channel_name": "Acme Orders Teams Bot", "__channel_project_id": project.id}
        require_registered_user = False
        sender_mappings = {"user-456": admin.id}  # a linked sender runs as its own user
        allowed_roles = []
        # require_mention=False bypasses the mention-check in
        # _should_ignore_message_without_mention so the message is processed.
        require_mention = False
        thread_followup_policy = "mention_once_per_thread"

        async def send_message(self, target: str, content: str, **kwargs):
            return True

    router = ChannelMessageRouter()

    class SessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    router._session_factory = SessionFactory()

    # Use channel_id "18" so the channel_key is distinct from
    # test_channel_router_titles_new_channel_session_from_first_message which uses
    # channel_id="17". Otherwise _session_cache reuses the prior session and the
    # message count assertion fails when both tests share the same session.
    _channel_id = "18"

    await router._handle_message(
        _channel_id,
        DummyPlugin(),
        {
            "sender_id": "user-456",
            "content": "Erkläre mir report-builder",
            "target": "serviceUrl|conversationId",
        },
    )

    # Look up by channel_key so we get the session this test created, not any
    # stale session from a prior test with the same admin user.
    _channel_key = f"{_channel_id}:user-456"
    session = (
        await db.execute(
            select(Session).where(
                Session.user_id == admin.id,
                Session.metadata_["channel_key"].as_string() == _channel_key,
            )
        )
    ).scalar_one_or_none()
    assert session is not None
    assert session.project_id == project.id
    user_messages = (
        (await db.execute(select(Message).where(Message.session_id == session.id, Message.role == "user")))
        .scalars()
        .all()
    )
    assert len(user_messages) == 1
    assert user_messages[0].content == "Erkläre mir report-builder"
    assert scripted_turns["calls"][-1]["project_id"] == project.id
    assert scripted_turns["calls"][-1]["prompt"] == "Erkläre mir report-builder"
