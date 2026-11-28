"""The per-session hook key: proof that a PreToolUse call came from the launcher's own hook."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ...models import Session
from ..secret.crypto import decrypt_secret, encrypt_secret

HOOK_KEY_METADATA = "hook_key_enc"
STATE_ROOT_METADATA = "launcher_state_root"
MAX_STATE_ROOT_CHARS = 1024
HOOK_KEY_BYTES = 32
PROOF_WINDOW_SECONDS = 60
PROOF_VERSION = "v1"
# The proof's verb names the tool it is for: a confirmation proof never passes as a decision proof.
VERB_CONFIRM = "confirm"
VERB_DECIDE = "decide"

REASON_HOOK_KEY_ALREADY_REGISTERED = "hook_key_already_registered"
REASON_HOOK_KEY_INVALID = "hook_key_invalid"
REASON_HOOK_KEY_MISSING = "hook_key_not_registered"
REASON_PROOF_MISSING = "confirmation_proof_missing"
REASON_PROOF_INVALID = "confirmation_proof_invalid"
REASON_PROOF_EXPIRED = "confirmation_proof_expired"

_NONCE = re.compile(r"^[0-9a-f]{32}$")
_MAC = re.compile(r"^[0-9a-f]{64}$")
_TOOL_USE_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_APPROVAL_ID = re.compile(r"^[A-Za-z0-9\-]{1,36}$")


@dataclass(frozen=True, slots=True)
class ConfirmationProof:
    tool_use_id: str
    approval_id: str
    nonce: str


def _decoded_key(raw: object) -> bytes | None:
    if type(raw) is not str or not 0 < len(raw) <= 64:
        return None
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (binascii.Error, ValueError):
        return None
    return key if len(key) == HOOK_KEY_BYTES else None


def _state_root(raw: object) -> str | None:
    if type(raw) is not str or not raw.startswith("/") or len(raw) > MAX_STATE_ROOT_CHARS or not raw.isprintable():
        return None
    return raw.rstrip("/") or None


async def register_hook_key(
    db: AsyncSession, *, session: Session, raw_key: object, raw_state_root: object
) -> str | None:
    key = _decoded_key(raw_key)
    state_root = _state_root(raw_state_root)
    if key is None or state_root is None:
        return REASON_HOOK_KEY_INVALID
    metadata = dict(session.metadata_ or {})
    # Set once: a later caller cannot replace the launcher's key.
    if metadata.get(HOOK_KEY_METADATA):
        return REASON_HOOK_KEY_ALREADY_REGISTERED
    metadata[HOOK_KEY_METADATA] = encrypt_secret(base64.b64encode(key).decode("ascii"))
    # Joins the self-protection rules, so a moved state directory stays protected.
    metadata[STATE_ROOT_METADATA] = state_root
    session.metadata_ = metadata
    flag_modified(session, "metadata_")
    await db.flush()
    return None


def launcher_state_root(session: Session) -> str | None:
    metadata = session.metadata_ if isinstance(session.metadata_, dict) else {}
    return _state_root(metadata.get(STATE_ROOT_METADATA))


def _stored_key(session: Session) -> bytes | None:
    metadata = session.metadata_ if isinstance(session.metadata_, dict) else {}
    stored = metadata.get(HOOK_KEY_METADATA)
    if type(stored) is not str or not stored:
        return None
    try:
        key = base64.b64decode(decrypt_secret(stored))
    except (binascii.Error, ValueError, RuntimeError):
        return None
    return key if len(key) == HOOK_KEY_BYTES else None


def proof_message(session_key: str, tool_use_id: str, approval_id: str, nonce: str, ts: int,
                  verb: str = VERB_CONFIRM) -> str:
    return f"{PROOF_VERSION}|{verb}|{session_key}|{tool_use_id}|{approval_id}|{nonce}|{ts}"


def verify_confirmation_proof(
    session: Session, *, session_key: str, hook_input: dict[str, Any], now: float | None = None
) -> ConfirmationProof | str:
    return _verified(session, session_key=session_key, hook_input=hook_input, now=now, verb=VERB_CONFIRM,
                     field="approval_id")


def verify_decision_proof(
    session: Session, *, session_key: str, hook_input: dict[str, Any], now: float | None = None
) -> ConfirmationProof | str:
    return _verified(session, session_key=session_key, hook_input=hook_input, now=now, verb=VERB_DECIDE,
                     field="run_id")


def _verified(
    session: Session, *, session_key: str, hook_input: dict[str, Any], now: float | None, verb: str, field: str
) -> ConfirmationProof | str:
    key = _stored_key(session)
    if key is None:
        return REASON_HOOK_KEY_MISSING
    proof = hook_input.get("confirmation_proof")
    if not isinstance(proof, dict):
        return REASON_PROOF_MISSING
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    tool_use_id = hook_input.get("tool_use_id")
    approval_id = tool_input.get(field)
    nonce, ts, mac = proof.get("nonce"), proof.get("ts"), proof.get("mac")
    if (
        type(tool_use_id) is not str
        or not _TOOL_USE_ID.fullmatch(tool_use_id)
        or type(approval_id) is not str
        or not _APPROVAL_ID.fullmatch(approval_id)
        or type(nonce) is not str
        or not _NONCE.fullmatch(nonce)
        or type(ts) is not int
        or type(mac) is not str
        or not _MAC.fullmatch(mac)
    ):
        return REASON_PROOF_INVALID
    current = time.time() if now is None else now
    if abs(current - ts) > PROOF_WINDOW_SECONDS:
        return REASON_PROOF_EXPIRED
    message = proof_message(session_key, tool_use_id, approval_id, nonce, ts, verb)
    expected = hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, mac):
        return REASON_PROOF_INVALID
    return ConfirmationProof(tool_use_id=tool_use_id, approval_id=approval_id, nonce=nonce)


__all__ = [
    "HOOK_KEY_METADATA",
    "PROOF_WINDOW_SECONDS",
    "REASON_HOOK_KEY_ALREADY_REGISTERED",
    "REASON_HOOK_KEY_INVALID",
    "REASON_HOOK_KEY_MISSING",
    "REASON_PROOF_EXPIRED",
    "REASON_PROOF_INVALID",
    "REASON_PROOF_MISSING",
    "ConfirmationProof",
    "launcher_state_root",
    "proof_message",
    "register_hook_key",
    "verify_confirmation_proof",
    "verify_decision_proof",
]
