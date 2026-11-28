"""Octryx Mobile "live" limits and checks: what a device may report about its sessions and which pictures a
message may carry (``devices.live``)."""

from __future__ import annotations

import base64
import binascii
import re
from datetime import timedelta
from typing import Any

from ..agent_gateway.engine_keys import ENGINE_CLAUDE_CODE, ENGINES

LIVE_MESSAGE_TYPES = frozenset({"live_sessions", "live_incoming", "live_delivery", "live_progress"})
PEER = re.compile(r"^uds:/[A-Za-z0-9_./-]{1,280}\.sock$")
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,99}$")
MAX_TEXT = 8000
MAX_SESSIONS = 40
MAX_PER_MINUTE = 20
MAX_OPEN = 10
MAX_INCOMING_PER_MINUTE = 60
FRESH_FOR = timedelta(minutes=3)
SENT_TIMEOUT = timedelta(minutes=3)
KEEP_DAYS = 30
SETTLED = frozenset({"delivered", "altered", "failed"})
DELIVERY_REASONS = frozenset({"", "live_off", "session_gone", "invalid", "relay_failed", "relay_changed_text",
                              "attachment_missing"})
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 2 * 1024 * 1024
CHUNK_BYTES = 150 * 1024  # base64 of a chunk plus the envelope stays well below the channel's 256 KiB
IMAGE_TEXT = "(picture)"


def image_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def decode_images(raw: Any) -> list[tuple[str, bytes]]:
    if raw in (None, []):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_IMAGES:
        raise LiveError("images_invalid", 422)
    images = []
    for item in raw:
        data_b64 = item.get("data") if isinstance(item, dict) else None
        if not isinstance(data_b64, str) or len(data_b64) > (MAX_IMAGE_BYTES * 4) // 3 + 8:
            raise LiveError("image_too_large", 413)
        try:
            data = base64.b64decode(data_b64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise LiveError("images_invalid", 422) from error
        media_type = image_type(data)
        if not media_type:
            raise LiveError("image_type_refused", 415)
        if len(data) > MAX_IMAGE_BYTES:
            raise LiveError("image_too_large", 413)
        images.append((media_type, data))
    return images


class LiveError(Exception):
    def __init__(self, reason: str, status: int = 409) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


def _text(value: Any, limit: int) -> str:
    return str(value or "").replace("\x00", "")[:limit]


def _model(value: Any) -> str:
    return value if isinstance(value, str) and MODEL_ID.match(value) else ""


def normalize_sessions(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        peer = _text(item.get("peer"), 300)
        if not PEER.match(peer) or peer in seen:
            continue
        seen.add(peer)
        pid = item.get("pid")
        updated = item.get("updated_at")
        out.append({
            "peer": peer,
            "profile": re.sub(r"[^a-z0-9_-]", "", _text(item.get("profile"), 40).lower())[:8],
            "pid": pid if type(pid) is int and 0 < pid < 10**9 else 0,
            "session_id": _text(item.get("session_id"), 64),
            "name": _text(item.get("name"), 120),
            "cwd": _text(item.get("cwd"), 500),
            "status": _text(item.get("status"), 20),
            "kind": _text(item.get("kind"), 20),
            # The coding engine of the session (Claude Code or Codex); the launcher's scan of Claude Code's own session
            # registry (``live_sessions``) names none, so a session without one is Claude Code.
            "engine": engine if (engine := _text(item.get("engine"), 20)) in ENGINES else ENGINE_CLAUDE_CODE,
            # The model the session runs on, when the device reports one (a narrow id; anything else: "").
            "model": _model(item.get("model")),
            "updated_at": updated if type(updated) is int and updated >= 0 else 0,
        })
        if len(out) >= MAX_SESSIONS:
            break
    return out

