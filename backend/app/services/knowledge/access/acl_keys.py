"""ACL keys: the one vocabulary shared by the ledger, the projection and retrieval. A span is returned only when its
keys intersect the query's; no query admits ``restricted``."""

from __future__ import annotations

import hashlib
import re
from typing import Literal, TypeAlias

# public: every query admits it. restricted: no query admits it, so a restricted span is visible only through a
# principal key next to it, and the span's key list is never empty.
MarkerKey: TypeAlias = Literal["public", "restricted"]
# u.<40 hex>: the first 40 hex of the SHA-256 of a namespaced, normalized email address; the address is never stored.
PrincipalKey: TypeAlias = str
AclKey: TypeAlias = MarkerKey | PrincipalKey

PUBLIC_ACL_KEY: MarkerKey = "public"
RESTRICTED_ACL_KEY: MarkerKey = "restricted"
_KEY_PREFIX = "u."
_KEY_NAMESPACE = "octryx-knowledge-acl-v1:"
# One restricted source admits at most this many expanded principals; more is not determinable.
MAX_SOURCE_PRINCIPALS = 200
# A reader holds at most this many principal keys (today: one, their own address).
MAX_READER_KEYS = 4

_PRINCIPAL_KEY = re.compile(r"^u\.[0-9a-f]{40}$")
_EMAIL = re.compile(r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9-]{1,63})+$")
_READER_ACCOUNT_TYPE = "human"


def normalize_email(value: object) -> str | None:
    if type(value) is not str:
        return None
    email = value.strip().lower()
    if len(email) > 254 or not _EMAIL.fullmatch(email):
        return None
    return email


def principal_key_for_email(value: object) -> PrincipalKey | None:
    email = normalize_email(value)
    if email is None:
        return None
    return _KEY_PREFIX + hashlib.sha256((_KEY_NAMESPACE + email).encode("utf-8")).hexdigest()[:40]


def is_principal_key(value: object) -> bool:
    return type(value) is str and bool(_PRINCIPAL_KEY.fullmatch(value))


def is_acl_key(value: object) -> bool:
    return value in (PUBLIC_ACL_KEY, RESTRICTED_ACL_KEY) or is_principal_key(value)


def reader_principal_keys(user: object) -> tuple[PrincipalKey, ...]:
    if user is None or not getattr(user, "is_active", False):
        return ()
    # Only an active human account's address is one the platform vouches for (admin-only registration, or the identity
    # provider's address); technical accounts and callers without a user see public spans only.
    if getattr(user, "account_type", None) != _READER_ACCOUNT_TYPE:
        return ()
    key = principal_key_for_email(getattr(user, "email", None))
    return (key,) if key is not None else ()


def query_acl_keys(principal_keys: tuple[PrincipalKey, ...]) -> tuple[AclKey, ...]:
    return (PUBLIC_ACL_KEY, *principal_keys)


def span_acl_keys(principal_keys: tuple[PrincipalKey, ...] | None) -> tuple[AclKey, ...]:
    if principal_keys is None:
        return (PUBLIC_ACL_KEY,)
    return (RESTRICTED_ACL_KEY, *sorted(principal_keys))


__all__ = [
    "MAX_READER_KEYS",
    "MAX_SOURCE_PRINCIPALS",
    "PUBLIC_ACL_KEY",
    "RESTRICTED_ACL_KEY",
    "AclKey",
    "MarkerKey",
    "PrincipalKey",
    "is_acl_key",
    "is_principal_key",
    "normalize_email",
    "principal_key_for_email",
    "query_acl_keys",
    "reader_principal_keys",
    "span_acl_keys",
]
