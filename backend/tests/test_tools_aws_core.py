from __future__ import annotations

import pytest

from app.tools.connectors import aws_core
from app.tools.connectors.aws_core import _aws_credential_kwargs, _aws_env, _aws_json, _get_boto_session
from app.tools.context import ToolContext


def _context(project_config: dict | None = None) -> ToolContext:
    return ToolContext(
        user_id="user-1",
        project_ids=["project-1"],
        roles=["admin"],
        session_id="session-1",
        project_config=project_config or {"aws_region": "eu-central-1"},
    )


@pytest.mark.asyncio
async def test_eks_describe_cluster_uses_lowercase_boto_name_param(monkeypatch):
    calls = []

    class FakeClient:
        def describe_cluster(self, **kwargs):
            calls.append(kwargs)
            return {"cluster": {"name": kwargs["name"]}}

    class FakeSession:
        def client(self, service):
            assert service == "eks"
            return FakeClient()

    async def fake_assume_role_if_needed(context, session):
        return session

    monkeypatch.setattr(aws_core, "_get_boto_session", lambda context: FakeSession())
    monkeypatch.setattr(aws_core, "_assume_role_if_needed", fake_assume_role_if_needed)

    result = await _aws_json(_context(), "eks", ["describe-cluster", "--name", "nonprod"])

    assert result["cluster"]["name"] == "nonprod"
    assert calls == [{"name": "nonprod"}]


def test_static_aws_credentials_must_be_configured_as_pair():
    with pytest.raises(ValueError, match="must be configured together"):
        _aws_credential_kwargs({"aws_access_key_id": "access-only"})

    with pytest.raises(ValueError, match="must be configured together"):
        _aws_credential_kwargs({"aws_secret_access_key": "secret-only"})


def test_boto_session_uses_static_connector_credentials_without_profile_lookup():
    context = _context(
        {
            "aws_region": "eu-central-1",
            "aws_profile": "missing-local-profile",
            "aws_access_key_id": "test-access-key",
            "aws_secret_access_key": "test-secret-key",
            "aws_session_token": "test-session-token",
        }
    )

    session = _get_boto_session(context)
    credentials = session.get_credentials().get_frozen_credentials()

    assert session.region_name == "eu-central-1"
    assert credentials.access_key == "test-access-key"
    assert credentials.secret_key == "test-secret-key"
    assert credentials.token == "test-session-token"


@pytest.mark.asyncio
async def test_aws_env_uses_static_connector_credentials_before_irsa_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "env-access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "env-secret-key")
    monkeypatch.setenv("AWS_WEB_IDENTITY_TOKEN_FILE", "/var/run/secrets/eks/token")
    monkeypatch.setenv("AWS_ROLE_ARN", "arn:aws:iam::123456789012:role/IrsaRole")
    context = _context(
        {
            "aws_region": "eu-central-1",
            "aws_access_key_id": "connector-access-key",
            "aws_secret_access_key": "connector-secret-key",
        }
    )

    env = await _aws_env(context)

    assert env["AWS_REGION"] == "eu-central-1"
    assert env["AWS_DEFAULT_REGION"] == "eu-central-1"
    assert env["AWS_ACCESS_KEY_ID"] == "connector-access-key"
    assert env["AWS_SECRET_ACCESS_KEY"] == "connector-secret-key"
    assert "AWS_WEB_IDENTITY_TOKEN_FILE" not in env
    assert "AWS_ROLE_ARN" not in env


@pytest.mark.asyncio
async def test_aws_env_falls_back_to_irsa_when_static_credentials_are_absent(monkeypatch):
    monkeypatch.setenv("AWS_WEB_IDENTITY_TOKEN_FILE", "/var/run/secrets/eks/token")
    monkeypatch.setenv("AWS_ROLE_ARN", "arn:aws:iam::123456789012:role/IrsaRole")

    env = await _aws_env(_context({"aws_region": "eu-central-1"}))

    assert env["AWS_REGION"] == "eu-central-1"
    assert env["AWS_WEB_IDENTITY_TOKEN_FILE"] == "/var/run/secrets/eks/token"
    assert env["AWS_ROLE_ARN"] == "arn:aws:iam::123456789012:role/IrsaRole"
