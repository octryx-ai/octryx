"""The object store can use its own credentials profile, apart from AWS_* env credentials."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.knowledge.objects.config import object_store_config_from_mapping
from app.services.knowledge.objects.errors import KnowledgeObjectInvalidConfigurationError
from app.services.knowledge.objects.transport import build_s3_client

BASE = {
    "OCTRYX_KNOWLEDGE_OBJECT_ENDPOINT_URL": "http://127.0.0.1:8333",
    "OCTRYX_KNOWLEDGE_OBJECT_BUCKET": "octryx-knowledge",
    "OCTRYX_KNOWLEDGE_OBJECT_REGION": "us-east-1",
}


def test_the_client_signs_with_the_profile_not_the_environment(tmp_path: Path, monkeypatch) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "[octryx-knowledge-object]\naws_access_key_id = OBJECTKEY\naws_secret_access_key = OBJECTSECRET\n"
    )
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(credentials))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "absent-config"))
    # What the process holds for Bedrock must never reach the object store.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "BEDROCKKEY")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "BEDROCKSECRET")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "BEDROCKTOKEN")

    config = object_store_config_from_mapping(
        {**BASE, "OCTRYX_KNOWLEDGE_OBJECT_AWS_PROFILE": "octryx-knowledge-object"}
    )
    frozen = build_s3_client(config)._request_signer._credentials.get_frozen_credentials()

    assert (frozen.access_key, frozen.token) == ("OBJECTKEY", None)
    assert "octryx-knowledge-object" not in repr(config)


def test_without_a_profile_the_default_chain_is_unchanged(monkeypatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "DEFAULTKEY")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "DEFAULTSECRET")
    config = object_store_config_from_mapping(BASE)
    assert config.credentials_profile is None
    assert build_s3_client(config)._request_signer._credentials.get_frozen_credentials().access_key == "DEFAULTKEY"


@pytest.mark.parametrize("profile", ["../etc/passwd", "a b", "x" * 65, "$(id)"])
def test_a_profile_name_is_a_bounded_token(profile: str) -> None:
    with pytest.raises(KnowledgeObjectInvalidConfigurationError):
        object_store_config_from_mapping({**BASE, "OCTRYX_KNOWLEDGE_OBJECT_AWS_PROFILE": profile})
