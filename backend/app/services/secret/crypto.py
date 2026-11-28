"""Fernet encryption of stored secret values and blobs with the instance ``encryption_key``. Only the sites
``tests/guards/test_secret_decryption.py`` lists decrypt."""

from __future__ import annotations

import base64
import hashlib

from ...config import get_settings

_FERNET_PREFIX = "fernet:"


def _fernet():
    from cryptography.fernet import Fernet

    key = hashlib.sha256(get_settings().encryption_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: str) -> str:
    token = _fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{_FERNET_PREFIX}{token}"


def decrypt_secret(value: str) -> str:
    if not value.startswith(_FERNET_PREFIX):
        raise ValueError("Unknown secret format")
    return _fernet().decrypt(value[len(_FERNET_PREFIX) :].encode("utf-8")).decode("utf-8")


def encrypt_bytes(value: bytes) -> bytes:
    return _fernet().encrypt(value)


def decrypt_bytes(value: bytes) -> bytes:
    return _fernet().decrypt(value)


__all__ = ["decrypt_bytes", "decrypt_secret", "encrypt_bytes", "encrypt_secret"]
