"""What a non-admin sees of the Workspace-bound config families."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException

from ..project.private_workspace import outside_foreign_private
from ..tool_config.url_userinfo import carries_userinfo

MASK = "***"
SECRET_MARKERS = ("credential", "secret", "token", "password", "passwd", "private", "hmac")
AUTH_WORDS = {"auth", "authorization", "authentication", "basicauth", "apikey"}
# ``<word>_key`` names an identifier, not a secret, after these words.
IDENTIFIER_KEY_WORDS = {
    "board", "cache", "epic", "field", "group", "idempotency", "issue", "item", "jira", "job", "lookup", "parent",
    "partition", "pr", "primary", "project", "public", "row", "sort", "source", "space", "stage", "state", "work",
}
URL_FIELDS = ("base_url", "repository_url")


def is_secret_field(key: object) -> bool:
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key)).lower()
    if any(marker in name for marker in SECRET_MARKERS):
        return True
    words = [word for word in re.split(r"[^a-z0-9]+", name) if word]
    if AUTH_WORDS & set(words):
        return True
    return any(word == "key" and (index == 0 or words[index - 1] not in IDENTIFIER_KEY_WORDS)
               for index, word in enumerate(words))


def _mask_secret(value: Any) -> Any:
    if value in (None, "", [], {}) or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, list):
        return [_mask_secret(entry) for entry in value]
    return MASK


def _mask_userinfo(value: str) -> str:
    if not carries_userinfo(value):
        return value
    try:
        parts = urlsplit(value)
    except ValueError:
        return MASK
    host = parts.netloc.rpartition("@")[2]
    if "@" not in parts.netloc or not host:
        return MASK  # hidden by whitespace or look-alike characters: nothing safe to show
    return urlunsplit(parts._replace(netloc=f"{MASK}@{host}"))


def mask_field(key: object, value: Any) -> Any:
    if is_secret_field(key):
        return _mask_secret(value)
    if key in URL_FIELDS and isinstance(value, str):
        return _mask_userinfo(value)
    return _masked(value)


def _masked(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: mask_field(key, entry) for key, entry in value.items()}
    if isinstance(value, list):
        return [_masked(entry) for entry in value]
    return value


def _restore(key: object, sent: Any, stored: Any) -> Any:
    if sent == stored:
        return sent
    if sent == mask_field(key, stored):
        return stored  # left as listed: unchanged
    if isinstance(sent, dict) and isinstance(stored, dict):
        return unmasked(sent, stored)
    if isinstance(sent, list) and isinstance(stored, list):
        restored = [_restore(key, entry, stored[index]) if index < len(stored) else entry
                    for index, entry in enumerate(sent)]
        return [entry for entry in restored if entry != MASK]  # an unmatched mask is dropped
    return sent


def unmasked(payload: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    return {key: _restore(key, value, stored[key]) if key in stored else value for key, value in payload.items()}


def refuse_userinfo(value: Any, field: str) -> Any:
    # Credentials belong in ``credential_ref``, never in URL userinfo.
    if carries_userinfo(value):
        raise HTTPException(status_code=422, detail=f"{field} must not carry credentials (user:password@)")
    return value


def scope_filter(model: Any, project_scope: set[str] | None, viewer_id: str) -> Any:
    if project_scope is None:
        return outside_foreign_private(model.project_id, viewer_id)
    return model.project_id.in_(project_scope) | model.project_id.is_(None)


def visible_rows(items: Iterable[dict[str, Any]], project_scope: set[str] | None) -> list[dict[str, Any]]:
    if project_scope is None:
        return list(items)
    return [{**_masked(item), "read_only": item.get("project_id") is None} for item in items]


__all__ = ["MASK", "is_secret_field", "mask_field", "refuse_userinfo", "scope_filter", "unmasked", "visible_rows"]
