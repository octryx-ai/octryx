"""Unit tests for channel plugins and channel config service."""

import json


# Test ChannelPlugin ABC
def test_telegram_plugin_instantiation():
    from app.plugins.channels.telegram import TelegramPlugin

    p = TelegramPlugin("telegram", {"bot_token": "test:TOKEN", "enabled": True})
    assert p.plugin_id == "telegram"
    assert p.bot_token == "test:TOKEN"
    assert p.enabled is True


def test_email_plugin_instantiation():
    from app.plugins.channels.email_plugin import EmailPlugin

    p = EmailPlugin("email", {"smtp_host": "smtp.example.com", "smtp_username": "u", "smtp_password": "p"})
    assert p.smtp_host == "smtp.example.com"
    assert p.from_address == "u"


def test_teams_plugin_instantiation():
    from app.plugins.channels.teams_plugin import TeamsPlugin

    p = TeamsPlugin("msteams", {"app_id": "abc", "app_password": "secret"})
    assert p.app_id == "abc"


def test_matrix_plugin_instantiation():
    from app.plugins.channels.matrix_plugin import MatrixPlugin

    p = MatrixPlugin("matrix", {"homeserver": "https://matrix.org", "username": "@bot:matrix.org"})
    assert p.homeserver == "https://matrix.org"


def test_slack_plugin_instantiation():
    from app.plugins.channels.slack_plugin import SlackPlugin

    p = SlackPlugin("slack", {"bot_token": "xoxb-test", "signing_secret": "abc123"})
    assert p.bot_token == "xoxb-test"


def test_plugin_manager_registers_all():
    from app.plugins import plugin_manager

    ids = plugin_manager.get_known_plugin_ids()
    assert "telegram" in ids
    assert "email" in ids
    assert "msteams" in ids
    assert "matrix" in ids
    assert "slack" in ids


def test_plugin_info_has_required_fields():
    from app.plugins import plugin_manager

    for pid in plugin_manager.get_known_plugin_ids():
        info = plugin_manager.get_plugin_info(pid)
        assert "name" in info
        assert "config_fields" in info
        assert isinstance(info["config_fields"], list)


def test_rbac_sender_mappings_parsed():
    from app.plugins.channels.telegram import TelegramPlugin

    mappings = {"123456": "user-uuid-abc"}
    p = TelegramPlugin("telegram", {"sender_mappings": json.dumps(mappings)})
    assert p.sender_mappings == mappings


def test_rbac_require_registered_user():
    from app.plugins.channels.email_plugin import EmailPlugin

    p = EmailPlugin("email", {"require_registered_user": True})
    assert p.require_registered_user is True


# Test ChannelConfig schema
def test_channel_config_schema():
    from app.schemas.comms.channel_config import ChannelConfigUpdate

    u = ChannelConfigUpdate(enabled=True, config={"key": "val"})
    assert u.enabled is True
    assert u.config == {"key": "val"}


# Test allowed_roles on all plugins
def test_allowed_roles_field():
    from app.plugins.channels.email_plugin import EmailPlugin
    from app.plugins.channels.matrix_plugin import MatrixPlugin
    from app.plugins.channels.slack_plugin import SlackPlugin
    from app.plugins.channels.teams_plugin import TeamsPlugin
    from app.plugins.channels.telegram import TelegramPlugin

    t = TelegramPlugin("telegram", {"allowed_roles": "admin,manager"})
    assert t.allowed_roles == "admin,manager"

    s = SlackPlugin("slack", {"bot_token": "x", "signing_secret": "x", "allowed_roles": ["admin"]})
    assert s.allowed_roles == ["admin"]

    m = MatrixPlugin("matrix", {"homeserver": "http://x", "user_id": "@b:x", "allowed_roles": ""})
    assert m.allowed_roles == ""

    te = TeamsPlugin("msteams", {"app_id": "x", "app_password": "x"})
    assert te.allowed_roles == []  # default

    e = EmailPlugin("email", {"smtp_host": "x", "allowed_roles": "user"})
    assert e.allowed_roles == "user"


# Test allowed_roles appears in config_fields for each plugin
def test_allowed_roles_in_config_fields():
    from app.plugins import plugin_manager

    for pid in plugin_manager.get_known_plugin_ids():
        info = plugin_manager.get_plugin_info(pid)
        field_names = [f["name"] for f in info["config_fields"]]
        assert "allowed_roles" in field_names, f"{pid} missing allowed_roles config field"


# Test approval regex patterns
def test_approval_regex():
    from app.services.channel_router_runtime import _APPROVE_RE, _REJECT_RE

    m = _APPROVE_RE.match("approve abc12345-def6-7890-abcd-ef1234567890")
    assert m is not None
    assert m.group(1) == "abc12345-def6-7890-abcd-ef1234567890"

    assert _APPROVE_RE.match("approve short") is None  # too short

    m2 = _REJECT_RE.match("reject abc12345-def6-7890-abcd-ef1234567890 not ready yet")
    assert m2 is not None
    assert m2.group(2) == "not ready yet"

    m3 = _REJECT_RE.match("REJECT abc12345-def6-7890-abcd-ef1234567890")
    assert m3 is not None
    assert m3.group(2) is None
