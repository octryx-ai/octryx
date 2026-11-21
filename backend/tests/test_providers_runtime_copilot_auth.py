"""Copilot client token discovery, auth sessions, supported models, API base URL and HTTP errors."""

import httpx
import pytest

from app.agent.providers import CopilotClient, get_provider
from app.agent.providers.copilot import COPILOT_API_MODEL_IDS


def test_copilot_factory_uses_env_token(monkeypatch):
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "env-token")
    client = get_provider("copilot", driver="copilot_api")
    assert isinstance(client, CopilotClient)
    assert client.access_token == "env-token"


def test_copilot_factory_auth_session_mode_discovers_local_session(monkeypatch):
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(
        "app.agent.providers.CopilotClient.read_cli_login_state",
        staticmethod(lambda: {"login": "alice-example", "host": "https://github.com"}),
    )
    monkeypatch.setattr(
        "app.agent.providers.CopilotClient.read_macos_keychain_token",
        staticmethod(lambda account=None: "session-token"),
    )
    client = get_provider("copilot", driver="copilot_api", auth_mode="auth_session")
    assert isinstance(client, CopilotClient)
    assert client.access_token == "session-token"


def test_copilot_detect_auth_session_reports_cli_source(monkeypatch):
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(
        "app.agent.providers.CopilotClient.read_cli_login_state",
        staticmethod(lambda: {"login": "alice-example", "host": "https://github.com", "model": "gpt-5.3-codex"}),
    )
    monkeypatch.setattr(
        "app.agent.providers.CopilotClient.discover_access_token", staticmethod(lambda: "session-token")
    )

    state = CopilotClient.detect_auth_session()

    assert state["available"] is True
    assert state["source"] == "copilot-cli"
    assert state["auth_type"] == "oauth"
    assert state["model"] == "gpt-5.3-codex"


def test_copilot_missing_token(monkeypatch):
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr("app.agent.providers.CopilotClient.read_cli_login_state", staticmethod(lambda: {}))
    monkeypatch.setattr(
        "app.agent.providers.CopilotClient.read_macos_keychain_token", staticmethod(lambda account=None: None)
    )
    with pytest.raises(ValueError, match="Copilot provider requires"):
        get_provider("copilot", driver="copilot_api")


def test_copilot_static_fallback_models_are_supported_chat_models():
    assert "gpt-4o" in COPILOT_API_MODEL_IDS
    assert "gpt-4o-mini" in COPILOT_API_MODEL_IDS
    assert all("codex" not in model_id and not model_id.startswith("gpt-5") for model_id in COPILOT_API_MODEL_IDS)


def test_copilot_client_accepts_configured_api_base_url():
    client = CopilotClient("test-token", base_url="https://api.individual.githubcopilot.com/")

    assert client.api_url == "https://api.individual.githubcopilot.com"
    assert str(client.client.base_url).rstrip("/") == "https://api.individual.githubcopilot.com"


def test_copilot_http_error_includes_api_detail():
    request = httpx.Request("POST", "https://api.githubcopilot.com/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={
            "error": {
                "code": "model_not_supported",
                "message": "The requested model is not supported.",
            }
        },
    )
    client = CopilotClient("test-token")

    with pytest.raises(RuntimeError, match="model_not_supported: The requested model is not supported"):
        client._raise_for_status(response)
