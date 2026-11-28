"""The one bcrypt salt of the platform: its work factor comes from ``Settings.auth_bcrypt_rounds``."""

from __future__ import annotations

import bcrypt

from .config import get_settings


def bcrypt_salt() -> bytes:
    return bcrypt.gensalt(rounds=get_settings().auth_bcrypt_rounds)


__all__ = ["bcrypt_salt"]
