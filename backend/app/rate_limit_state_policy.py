"""Bounded retention for the in-memory rate-limit key state."""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

# Bounds the API limiter at a few tens of MiB worst case, yet far above the distinct clients seen in one
# window, so the hard bound stays a backstop rather than an operational limit.
DEFAULT_MAX_RATE_LIMIT_KEYS = 20_000

# Below this the bound would become the limiter: a handful of ordinary concurrent clients
# would evict each other's windows.
MIN_RATE_LIMIT_KEYS = 256

# Rejected rather than silently clamped, so a mistyped value surfaces at startup.
MAX_RATE_LIMIT_KEYS = 200_000

# Store identities. Fixed literals, safe as metric labels and log fields.
STORE_API = "api"
# Authenticated users' buckets live apart from address buckets, so no number of client addresses can
# evict (reset) a user's window, and a user's own keys never displace an address window.
STORE_API_USER = "api_user"
STORE_AUTH = "auth"

EVICTION_REASON_STALE = "stale"
EVICTION_REASON_CAPACITY = "capacity"
EVICTION_REASONS = (EVICTION_REASON_STALE, EVICTION_REASON_CAPACITY)

# Only every N-th capacity eviction is logged: a line per request under exactly the traffic
# that causes it would be its own resource problem.
CAPACITY_WARNING_INTERVAL = 1000


class RateLimitRetentionConfigError(ValueError):
    pass


def validate_max_rate_limit_keys(value: object) -> int:
    if type(value) is not int:
        raise RateLimitRetentionConfigError("max_rate_limit_keys must be an integer number of keys")
    if value < MIN_RATE_LIMIT_KEYS:
        raise RateLimitRetentionConfigError(
            f"max_rate_limit_keys must be at least {MIN_RATE_LIMIT_KEYS}; a smaller bound would evict "
            "the windows of ordinary concurrent clients instead of bounding memory"
        )
    if value > MAX_RATE_LIMIT_KEYS:
        raise RateLimitRetentionConfigError(
            f"max_rate_limit_keys must not exceed {MAX_RATE_LIMIT_KEYS}; a higher value is not a bound"
        )
    return value


StateT = TypeVar("StateT")


@dataclass
class _Entry(Generic[StateT]):
    state: StateT
    last_active: float


@dataclass(frozen=True)
class RateLimitStateSnapshot:
    name: str
    current_keys: int
    capacity: int
    retention_seconds: int
    evictions: Mapping[str, int]


class BoundedKeyStateStore(Generic[StateT]):
    def __init__(
        self,
        name: str,
        *,
        retention_seconds: int,
        capacity_provider: Callable[[], int],
        new_state: Callable[[], StateT],
        register: bool = True,
    ) -> None:
        self.name = name
        self.retention_seconds = int(retention_seconds)
        # Public on purpose: the bound is resolved per admission from current
        # configuration, and that indirection is part of the contract.
        self.capacity_provider = capacity_provider
        self._new_state = new_state
        self._entries: OrderedDict[str, _Entry[StateT]] = OrderedDict()
        self._evictions: dict[str, int] = dict.fromkeys(EVICTION_REASONS, 0)
        if register:
            _register_store(self)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def touch(self, key: str, *, now: float) -> StateT:
        self.evict_stale(now=now)
        entry = self._entries.get(key)
        if entry is not None:
            entry.last_active = now
            self._entries.move_to_end(key)
            return entry.state
        self._make_room()
        state = self._new_state()
        self._entries[key] = _Entry(state=state, last_active=now)
        return state

    def peek(self, key: str) -> StateT | None:
        entry = self._entries.get(key)
        return None if entry is None else entry.state

    def evict_stale(self, *, now: float) -> int:
        horizon = now - self.retention_seconds
        evicted = 0
        while self._entries:
            key, entry = next(iter(self._entries.items()))
            if entry.last_active >= horizon:
                break
            del self._entries[key]
            evicted += 1
        if evicted:
            self._evictions[EVICTION_REASON_STALE] += evicted
        return evicted

    def discard(self, key: str) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()
        self._evictions = dict.fromkeys(EVICTION_REASONS, 0)

    def snapshot(self) -> RateLimitStateSnapshot:
        return RateLimitStateSnapshot(
            name=self.name,
            current_keys=len(self._entries),
            capacity=int(self.capacity_provider()),
            retention_seconds=self.retention_seconds,
            evictions=dict(self._evictions),
        )

    def _make_room(self) -> None:
        capacity = int(self.capacity_provider())
        while self._entries and len(self._entries) >= capacity:
            self._entries.popitem(last=False)
            self._evictions[EVICTION_REASON_CAPACITY] += 1
            self._log_capacity_eviction(capacity)

    def _log_capacity_eviction(self, capacity: int) -> None:
        total = self._evictions[EVICTION_REASON_CAPACITY]
        if total != 1 and total % CAPACITY_WARNING_INTERVAL != 0:
            return
        logger.warning(
            "Rate-limit key state reached its configured bound; the least-recently-active key was dropped "
            "(store=%s max_rate_limit_keys=%s capacity_evictions_total=%s)",
            self.name,
            capacity,
            total,
        )


# Read only for aggregate reporting; it is not a lookup path for limiter state.
_STORES: dict[str, BoundedKeyStateStore] = {}


def _register_store(store: BoundedKeyStateStore) -> None:
    if store.name in _STORES:
        raise ValueError(f"a rate-limit key store named {store.name!r} is already registered")
    _STORES[store.name] = store


def state_snapshots() -> list[RateLimitStateSnapshot]:
    return [store.snapshot() for _, store in sorted(_STORES.items())]


__all__ = [
    "CAPACITY_WARNING_INTERVAL",
    "DEFAULT_MAX_RATE_LIMIT_KEYS",
    "EVICTION_REASONS",
    "EVICTION_REASON_CAPACITY",
    "EVICTION_REASON_STALE",
    "MAX_RATE_LIMIT_KEYS",
    "MIN_RATE_LIMIT_KEYS",
    "STORE_API",
    "STORE_API_USER",
    "STORE_AUTH",
    "BoundedKeyStateStore",
    "RateLimitRetentionConfigError",
    "RateLimitStateSnapshot",
    "state_snapshots",
    "validate_max_rate_limit_keys",
]
