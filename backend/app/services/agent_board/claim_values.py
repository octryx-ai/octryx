"""Claim constants and the pure rules of a claim: lease bounds, path normalisation, liveness and holder."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from ...models import WorkItemClaim

KIND_GATEWAY_SESSION = "gateway_session"
KIND_MCP_SESSION = "mcp_session"
# A chat session of the platform (chat-client parity): the chat claims, posts and hands off as its
# own agent, so a chat never acts as another agent's session or grant. Its lease is never renewed by presence.
KIND_CHAT_SESSION = "chat_session"
HOLDER_KINDS = frozenset({KIND_GATEWAY_SESSION, KIND_MCP_SESSION, KIND_CHAT_SESSION})

DEFAULT_LEASE_SECONDS = 900
MIN_LEASE_SECONDS = 60
MAX_LEASE_SECONDS = 7200
MAX_PATHS = 50
MAX_PATH_CHARS = 300
LIST_LIMIT = 200

RELEASE_RELEASED = "released"
RELEASE_EXPIRED = "expired"
RELEASE_TAKEN_OVER = "taken_over"
RELEASE_ADMIN = "admin_released"
RELEASE_SESSION_STOPPED = "session_stopped"
ADMIN_RELEASE_AUDIT_ACTION = "agent_board.claim.admin_released"


def iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value is not None else None


def lease_seconds_from(value: Any) -> int:
    if value is None or value == "":
        return DEFAULT_LEASE_SECONDS
    if type(value) is not int:
        raise HTTPException(status_code=422, detail="lease_seconds must be an integer")
    return min(max(value, MIN_LEASE_SECONDS), MAX_LEASE_SECONDS)


def normalize_path(value: str) -> str:
    text = value.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def paths_from(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_PATHS:
        raise HTTPException(status_code=422, detail=f"paths must be a list of at most {MAX_PATHS} entries")
    paths: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip() or len(entry) > MAX_PATH_CHARS:
            raise HTTPException(status_code=422, detail=f"each path must be 1 to {MAX_PATH_CHARS} characters")
        normalized = normalize_path(entry)
        if normalized and normalized not in paths:
            paths.append(normalized)
    return paths


def paths_overlap(claimed: Iterable[str], wanted: Iterable[str]) -> bool:
    wanted_paths = [normalize_path(path) for path in wanted if isinstance(path, str) and normalize_path(path)]
    return any(own.startswith(path) or path.startswith(own) for own in claimed for path in wanted_paths)


def is_live(claim: WorkItemClaim, now: datetime) -> bool:
    return claim.released_at is None and claim.lease_until > now


def is_holder(claim: WorkItemClaim, *, kind: str, ref_hash: str, user_id: str) -> bool:
    return claim.holder_kind == kind and claim.holder_ref_hash == ref_hash and claim.holder_user_id == user_id
