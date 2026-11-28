"""The platform's pet state (contract ``pet_v1``); :func:`parse` never raises.
Wrong types fall back to empty values; links are kept only as root-relative paths or http(s) URLs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

STATES = ("resting", "working", "needs_you", "done", "problem")
UNKNOWN = "unknown"
MAX_ITEMS = 5
MAX_TITLE = 80
_CODE = re.compile(r"^[a-z0-9_]{1,64}$")
_ID = re.compile(r"^[\x21-\x7e]{1,160}$")


@dataclass(frozen=True)
class PetItem:
    id: str
    kind: str
    title: str
    url: str | None


@dataclass(frozen=True)
class PetState:
    state: str
    reason: str | None = None
    since: str | None = None
    headline: str = ""
    count: int = 0
    items: tuple[PetItem, ...] = ()
    panel_url: str = "/chat"
    poll_after_seconds: int | None = None
    quiet_active: bool = False
    quiet_until: str | None = None


def _text(value: Any, limit: int = MAX_TITLE) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, (str, int, float)) else ""


def _link(value: Any) -> str | None:
    text = str(value) if isinstance(value, str) else ""
    if text.startswith("/") and not text.startswith("//"):
        return text
    return text if text.startswith(("https://", "http://")) else None


def _code(value: Any) -> str | None:
    return value if isinstance(value, str) and _CODE.match(value) else None


def _item(value: Any) -> PetItem | None:
    if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not _ID.match(value["id"]):
        return None
    return PetItem(id=value["id"], kind=_code(value.get("kind")) or "", title=_text(value.get("title")),
                   url=_link(value.get("url")))


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def parse(body: Any) -> PetState:
    if not isinstance(body, dict):
        return PetState(UNKNOWN)
    state = body.get("state") if body.get("state") in STATES else UNKNOWN
    raw_items = body.get("items") if isinstance(body.get("items"), list) else []
    items = tuple(item for item in map(_item, raw_items[:MAX_ITEMS]) if item is not None)
    quiet = body.get("quiet") if isinstance(body.get("quiet"), dict) else {}
    poll = body.get("poll_after_seconds")
    return PetState(
        state=state,
        reason=_code(body.get("reason")) if state == "problem" else None,
        since=_text(body.get("since"), 40) or None,
        headline=_text(body.get("headline")),
        count=max(_count(body.get("count")), len(items)),
        items=items,
        panel_url=_link(body.get("panel_url")) or "/chat",
        poll_after_seconds=poll if isinstance(poll, int) and not isinstance(poll, bool) and poll > 0 else None,
        quiet_active=quiet.get("active") is True,
        quiet_until=_text(quiet.get("until"), 40) or None if quiet.get("active") is True else None,
    )


__all__ = ["MAX_ITEMS", "STATES", "UNKNOWN", "PetItem", "PetState", "parse"]
