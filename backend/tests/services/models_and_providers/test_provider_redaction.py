import uuid

from app.models import LLMProvider, ProviderOAuthConfig
from app.services.provider import REDACTED_PROVIDER_SECRET, redact_provider_public_metadata
from app.web._helpers.panel_serializers import _serialize_provider


def test_redact_provider_public_metadata_removes_nested_credentials():
    payload = {
        "profile_home": "/app/data/provider_profiles/demo/home",
        "env": {
            "PATH": "/usr/local/bin",
            "OPENAI_API_KEY": "sk-env-secret",
            "AWS_SECRET_ACCESS_KEY": "aws-secret-value",
        },
        "headers": {"Authorization": "Bearer provider-token"},
        "allowed_repos": [{"project_key": "RIVER", "repo_slug": "service-config"}],
        "api_key_secret_ref": "secret-id-123",
        "refresh_token": "refresh-token-value",
    }

    redacted = redact_provider_public_metadata(payload)

    assert redacted["profile_home"] == "/app/data/provider_profiles/demo/home"
    assert redacted["env"]["PATH"] == "/usr/local/bin"
    assert redacted["env"]["OPENAI_API_KEY"] == REDACTED_PROVIDER_SECRET
    assert redacted["env"]["AWS_SECRET_ACCESS_KEY"] == REDACTED_PROVIDER_SECRET
    assert redacted["headers"]["Authorization"] == REDACTED_PROVIDER_SECRET
    assert redacted["allowed_repos"] == [{"project_key": "RIVER", "repo_slug": "service-config"}]
    assert redacted["api_key_secret_ref"] == REDACTED_PROVIDER_SECRET
    assert redacted["refresh_token"] == REDACTED_PROVIDER_SECRET
    assert "sk-env-secret" not in str(redacted)
    assert "aws-secret-value" not in str(redacted)
    assert "provider-token" not in str(redacted)
    assert "secret-id-123" not in str(redacted)


def test_panel_provider_serializer_redacts_config_and_credential_markers():
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name="openrouter",
        driver="openrouter_api",
        display_name="OpenRouter",
        api_key_secret_ref="secret-id-panel",
        oauth_config=ProviderOAuthConfig(login="alice", residual_json={"refresh_token": "refresh-secret"}),
        config_json={
            "profile_home": "/app/data/provider_profiles/openrouter/home",
            "env": {"OPENAI_API_KEY": "sk-config-secret", "SAFE_FLAG": "1"},
        },
        capabilities_json={"supports_tools": True, "access_token": "capability-token"},
        is_global=True,
        is_active=True,
    )

    payload = _serialize_provider(provider)

    assert payload["has_api_key"] is True
    assert payload["api_key_masked"] == "********"
    assert payload["auth_login"] == "alice"
    assert payload["config_json"]["profile_home"] == "/app/data/provider_profiles/openrouter/home"
    assert payload["config_json"]["env"]["SAFE_FLAG"] == "1"
    assert payload["config_json"]["env"]["OPENAI_API_KEY"] == REDACTED_PROVIDER_SECRET
    assert payload["capabilities_json"]["access_token"] == REDACTED_PROVIDER_SECRET
    payload_text = str(payload)
    assert "sk-legacy-secret" not in payload_text
    assert "secret-id-panel" not in payload_text
    assert "refresh-secret" not in payload_text
    assert "sk-config-secret" not in payload_text
    assert "capability-token" not in payload_text
