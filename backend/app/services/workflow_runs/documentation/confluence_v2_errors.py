"""Errors of the bounded Confluence Cloud v2 adapter (``confluence_v2``): closed kinds and whether a write was sent."""

from __future__ import annotations

from typing import Any

SENT_NO = "no"
SENT_REFUSED = "refused"
SENT_UNKNOWN = "unknown"

KIND_CONFLICT = "conflict"
KIND_PERMISSION = "permission"
KIND_NOT_FOUND = "not_found"
KIND_REJECTED = "rejected"
KIND_UNAVAILABLE = "unavailable"
KIND_TRANSPORT = "transport"
KIND_MALFORMED = "malformed"


class V2ProfileRefusalError(ValueError):
    pass


class V2Error(Exception):
    def __init__(self, kind: str, message: str, *, status_code: int | None = None, sent: str = SENT_NO) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.sent = sent

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "status_code": self.status_code, "sent": self.sent, "message": str(self)[:300]}


def _malformed(what: str, *, sent: str = SENT_NO) -> V2Error:
    return V2Error(KIND_MALFORMED, f"malformed Confluence v2 answer: {what}", sent=sent)
