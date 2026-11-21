"""ACL keys: the one vocabulary shared by the ledger, the projection and retrieval.

Every projected span carries a non-empty list of ACL keys, and every query admits a list of them;
a span is returned only when the two lists intersect (``acl_keys && :principals``, inside the
index statement). Three key shapes, closed:

- ``public``: the span's source has no restriction. Every query admits it.
- ``restricted``: the span's source is restricted. **No query ever admits it**, so a restricted
  span is visible only through a principal key next to it, and a restricted source whose principal
  list is empty is visible to nobody. It also keeps a restricted span's list non-empty, so it can
  never be mistaken for an unmarked span.
- ``u.<40 hex>``: one principal, the SHA-256 of a normalized email address. The address itself is
  never stored in the projection or the ACL tables.

Principal mapping (the explanation of *who* a key is). A source system reports its users and
groups; the connector expands them to email addresses at sync time, bounded. A platform user holds
the key of their own email address when they are an **active human** account: registration is
admin-only and OIDC/LDAP accounts carry the identity provider's address, so the address on the
account is the one the platform vouches for. Technical and system accounts, and callers without a
user (background jobs, evaluation), hold no principal key and therefore see public spans only.
"""

from __future__ import annotations

import hashlib
import re

PUBLIC_ACL_KEY = "public"
RESTRICTED_ACL_KEY = "restricted"
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
    """The comparison form of an email address, or ``None`` when it is not one."""
    if type(value) is not str:
        return None
    email = value.strip().lower()
    if len(email) > 254 or not _EMAIL.fullmatch(email):
        return None
    return email


def principal_key_for_email(value: object) -> str | None:
    email = normalize_email(value)
    if email is None:
        return None
    return _KEY_PREFIX + hashlib.sha256((_KEY_NAMESPACE + email).encode("utf-8")).hexdigest()[:40]


def is_principal_key(value: object) -> bool:
    return type(value) is str and bool(_PRINCIPAL_KEY.fullmatch(value))


def is_acl_key(value: object) -> bool:
    return value in (PUBLIC_ACL_KEY, RESTRICTED_ACL_KEY) or is_principal_key(value)


def reader_principal_keys(user: object) -> tuple[str, ...]:
    """The principal keys a platform user reads with: their own address, for an active human account."""
    if user is None or not getattr(user, "is_active", False):
        return ()
    if getattr(user, "account_type", None) != _READER_ACCOUNT_TYPE:
        return ()
    key = principal_key_for_email(getattr(user, "email", None))
    return (key,) if key is not None else ()


def query_acl_keys(principal_keys: tuple[str, ...]) -> tuple[str, ...]:
    """What one query admits: every public span, plus the reader's own principals."""
    return (PUBLIC_ACL_KEY, *principal_keys)


def span_acl_keys(principal_keys: tuple[str, ...] | None) -> tuple[str, ...]:
    """The marker one projected span carries. ``None`` means its source is not restricted."""
    if principal_keys is None:
        return (PUBLIC_ACL_KEY,)
    return (RESTRICTED_ACL_KEY, *sorted(principal_keys))


__all__ = [
    "MAX_READER_KEYS",
    "MAX_SOURCE_PRINCIPALS",
    "PUBLIC_ACL_KEY",
    "RESTRICTED_ACL_KEY",
    "is_acl_key",
    "is_principal_key",
    "normalize_email",
    "principal_key_for_email",
    "query_acl_keys",
    "reader_principal_keys",
    "span_acl_keys",
]
