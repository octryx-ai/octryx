"""Web Push: a platform with a fresh VAPID key configured; ``configured`` returns that key."""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import get_settings


@pytest.fixture
def configured(monkeypatch):
    vapid_key = ec.generate_private_key(ec.SECP256R1())
    raw = vapid_key.private_numbers().private_value.to_bytes(32, "big")
    monkeypatch.setattr(get_settings(), "mobile_vapid_private_key", base64.urlsafe_b64encode(raw).decode().rstrip("="))
    monkeypatch.setattr(get_settings(), "mobile_vapid_subject", "https://octryx.example.test")
    return vapid_key
