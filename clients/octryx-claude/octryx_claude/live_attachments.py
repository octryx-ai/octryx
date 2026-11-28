"""Pictures the phone attaches to a live message: joined from their chunks, checked (size, hash, real PNG, JPEG or
WebP) and written to the user's own inbox folder for the session to read (mixed into ``live_bridge.LiveBridge``)."""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
MAX_ATTACHMENT_PARTS = 32
MAX_PENDING_ATTACHMENTS = 9
INBOX_KEEP_SECONDS = 7 * 24 * 3600
_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def picture_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def inbox_dir() -> Path:
    # Outside octryx's state, which octryx's sessions may not read.
    return Path(tempfile.gettempdir()) / "octryx-inbox"


class AttachmentInbox:
    def _attachment(self, body: dict[str, Any]) -> None:
        attachment_id, message_id = str(body.get("attachment_id") or ""), str(body.get("message_id") or "")
        index, total = body.get("index"), body.get("total")
        if not (MESSAGE_ID.match(attachment_id) and MESSAGE_ID.match(message_id) and isinstance(index, int)
                and isinstance(total, int) and 0 <= index < total <= MAX_ATTACHMENT_PARTS):
            return
        try:
            data = base64.b64decode(str(body.get("data") or ""), validate=True)
        except (binascii.Error, ValueError):
            return
        entry = self._parts.get(attachment_id)
        if entry is None:
            while len(self._parts) >= MAX_PENDING_ATTACHMENTS:
                self._parts.pop(next(iter(self._parts)))  # the oldest half-received picture goes
            entry = self._parts[attachment_id] = {"message_id": message_id, "total": total, "parts": {}, "size": 0}
        if entry["message_id"] != message_id or entry["total"] != total or index in entry["parts"]:
            return
        if entry["size"] + len(data) > MAX_ATTACHMENT_BYTES:
            self._parts.pop(attachment_id, None)
            return
        entry["parts"][index] = data
        entry["size"] += len(data)

    def _store(self, message_id: str, named: list[Any]) -> list[Path] | None:
        pictures: list[tuple[str, bytes]] = []
        for item in named:
            item = item if isinstance(item, dict) else {}
            entry = self._parts.pop(str(item.get("id") or ""), None)
            if entry is None or entry["message_id"] != message_id or len(entry["parts"]) != entry["total"]:
                return None
            data = b"".join(entry["parts"][index] for index in range(entry["total"]))
            media_type = picture_type(data)
            if (len(data) != item.get("size") or hashlib.sha256(data).hexdigest() != item.get("sha256")
                    or not media_type or media_type != item.get("media_type")):
                return None
            pictures.append((media_type, data))
        folder = inbox_dir()
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        self._clean_inbox(folder)
        paths = []
        for number, (media_type, data) in enumerate(pictures, start=1):
            path = folder / f"{message_id}-{number}{_EXTENSIONS[media_type]}"
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
            paths.append(path)
        return paths

    @staticmethod
    def _clean_inbox(folder: Path) -> None:
        cutoff = time.time() - INBOX_KEEP_SECONDS
        for old in folder.glob("*"):
            with contextlib.suppress(OSError):
                if old.is_file() and old.stat().st_mtime < cutoff:
                    old.unlink()

