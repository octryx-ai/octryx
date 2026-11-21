"""The validated facts an object inventory page carries: one object and one bounded page."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .errors import KnowledgeObjectContractError, KnowledgeObjectOperation
from .keys import content_digest_from_key

MAX_INVENTORY_PAGE_KEYS = 1000
# Widest object an inventory entry may report. The write path bounds a stored object to
# ``MAX_OBJECT_BYTES``; a larger entry is therefore not something the product wrote, so it
# is treated as unrecognized rather than as a candidate.
MAX_INVENTORY_BYTE_SIZE = 8 * 1024 * 1024

_LIST = KnowledgeObjectOperation.LIST_OBJECTS

# The only shape a pagination cursor may have: it is the last key of a page, so it is
# already bounded to this narrow character set by the product's own key derivation.
_CURSOR = re.compile(r"^[a-z0-9][a-z0-9/_-]{0,1023}$")


@dataclass(frozen=True, slots=True)
class InventoryObject:
    """One object of one Workspace as the inventory saw it: address, size, age.

    ``last_modified`` is **naive UTC**, like every persisted timestamp in this codebase
    (``time_utils.utc_now``). The server answers a timezone-aware value; it is converted at
    the boundary below so no caller has to mix the two conventions.
    """

    key: str
    content_sha256: str
    byte_size: int
    last_modified: datetime

    def __post_init__(self) -> None:
        if type(self.key) is not str or content_digest_from_key(self.key) != self.content_sha256:
            raise KnowledgeObjectContractError(_LIST)
        if type(self.byte_size) is not int or not 0 <= self.byte_size <= MAX_INVENTORY_BYTE_SIZE:
            raise KnowledgeObjectContractError(_LIST)
        if type(self.last_modified) is not datetime or self.last_modified.tzinfo is not None:
            raise KnowledgeObjectContractError(_LIST)

    def age_hours(self, now: datetime) -> int:
        """Whole hours between this object's write and naive-UTC ``now``; never negative."""
        if type(now) is not datetime or now.tzinfo is not None:
            raise KnowledgeObjectContractError(_LIST)
        seconds = (now - self.last_modified).total_seconds()
        return int(seconds // 3600) if seconds > 0 else 0


@dataclass(frozen=True, slots=True)
class InventoryPage:
    """One bounded page of a Workspace's object inventory.

    ``unrecognized_count`` are keys under the Workspace prefix that do not match the
    product's derivation. They are counted so an operator can see that something else
    writes into the prefix, and they are never named, returned or deletable.

    ``next_after_key`` is ``None`` when the listing is complete — and also when the server
    reported more results but the last key of the page was not usable as a cursor, in which
    case ``truncated`` stays true so the caller records an incomplete view instead of
    silently treating it as the whole Workspace.

    The cursor is the last key of the page that has the derived shape, so keys *after* it are
    listed again on the next page. For the objects this returns that changes nothing (they are
    deduplicated by key), but an unrecognized key can be counted twice. Counting a stray key
    twice is the acceptable side of that trade: the alternative is carrying foreign key text
    out of this module to use as a cursor.
    """

    objects: tuple[InventoryObject, ...]
    unrecognized_count: int
    truncated: bool
    next_after_key: str | None

    def __post_init__(self) -> None:
        if type(self.unrecognized_count) is not int or self.unrecognized_count < 0:
            raise KnowledgeObjectContractError(_LIST)
        if type(self.truncated) is not bool:
            raise KnowledgeObjectContractError(_LIST)
        if self.next_after_key is not None and not self.truncated:
            raise KnowledgeObjectContractError(_LIST)
