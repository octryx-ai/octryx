from datetime import timedelta

import jwt
import pytest
from fastapi import HTTPException

from app.config import Settings, get_settings
from app.services.auth import (
    JWT_ALGORITHM,
    create_access_token,
    create_session_stream_token,
    decode_session_stream_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_create_and_decode_token_use_fixed_algorithm():
    token = create_access_token("user-123", expires_delta=timedelta(minutes=5))

    payload = jwt.get_unverified_header(token)
    assert payload["alg"] == JWT_ALGORITHM
    assert decode_token(token) == "user-123"


def test_decode_token_rejects_non_whitelisted_algorithm():
    settings = get_settings()
    token = jwt.encode({"sub": "user-123"}, settings.jwt_secret, algorithm="HS384")

    with pytest.raises(HTTPException):
        decode_token(token)


def test_create_and_decode_session_stream_token():
    token = create_session_stream_token(
        user_id="user-123",
        session_id="session-456",
        expires_delta=timedelta(minutes=5),
    )

    user_id, session_id = decode_session_stream_token(token)
    assert user_id == "user-123"
    assert session_id == "session-456"


def test_bcrypt_keeps_cost_12_by_default_and_hashes_at_the_configured_cost(monkeypatch):
    assert Settings.model_fields["auth_bcrypt_rounds"].default == 12
    monkeypatch.setattr(get_settings(), "auth_bcrypt_rounds", 5)

    hashed = hash_password("correct horse")

    assert hashed.startswith("$2b$05$")
    assert verify_password("correct horse", hashed) and not verify_password("wrong", hashed)
