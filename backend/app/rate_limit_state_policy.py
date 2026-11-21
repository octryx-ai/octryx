"""Bounded retention for the in-memory rate-limit key state.

Both in-memory limiters key their state by validated client address: the API
limiter in ``middleware.security.rate_limit`` and the brute-force limiter in
``services.auth_rate_limit`` (the API limiter keys authenticated users by user id
in a third store). While ``TRUSTED_PROXY_IPS`` is empty every request
is attributed to the ingress peer, so those key spaces are tiny. The moment the
allowlist is configured the keys become real internet client addresses,
and an unbounded ``dict`` of them becomes a memory-growth surface an attacker
controls simply by arriving from many addresses.

This module owns the bound, and nothing else: the limiters keep owning their
window arithmetic, their own lock, and their own limits. What is delegated here
is purely *key lifecycle* — which keys exist, and which stop existing.

Eviction precedence, in order, evaluated on every admission:

1. **Stale retention.** A key whose last counted activity is older than the
   retention horizon is removed. Once the horizon has passed, the key's window
   can no longer contain a single countable timestamp, so dropping it removes
   nothing an active window needed. This is the eviction that does the work in
   normal operation.
2. **Hard cardinality bound.** If the store is still at its configured capacity
   when a new key has to be admitted, the least-recently-active key is dropped.
   This is the backstop that makes the bound hold no matter how the clock or the
   traffic behaves, and it is the only case in which a still-enforcing window can
   be lost.

Why the least-recently-active key and not the newest one: last activity orders
the keys by how close they already are to their own retention horizon, so the
victim is always the key with the least enforcement left to lose. And why evict
at all instead of refusing the new client: refusing would convert an attacker's
address cardinality into a denial of service for every client that arrives after
saturation, which is a strictly worse failure than resetting one nearly-expired
budget. The refusal path a saturated limiter *does* keep is the one that matters
for correctness — an active window is never silently widened, only dropped, and
every drop is counted and (bounded) logged.

Deliberate boundaries of this contract:

- **Not internally synchronized.** Each owner already holds a lock appropriate to
  how it is called (``asyncio.Lock`` for the ASGI middleware, ``threading.Lock``
  for the synchronous auth service) and mutates its store inside it. Adding a
  second lock here would create two authorities over one piece of state for no
  gain.
- **The clock is the caller's.** Every method takes ``now`` from the owner, which
  is what lets a test drive retention deterministically instead of sleeping. The
  clock must be monotonic: the least-recently-active ordering is maintained by
  construction (every touched key moves to the end with a non-decreasing ``now``)
  and a clock that jumps backwards would corrupt that order.
- **Capacity is read per admission**, not captured at construction, so the
  configured value applies to the running process the same way the trusted-proxy
  allowlist does.
- **The bound is per process and per store.** With three stores the process retains
  at most ``3 * max_rate_limit_keys`` keys, and a deployment with several replicas
  multiplies that by the replica count.
- **Nothing here reads a request.** Keys arrive as opaque strings from the
  boundary; this module never parses a header, and never logs or exports a key.
  The only labels it produces are its three fixed store names and its two fixed
  eviction reasons.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

# --- Configured bound -------------------------------------------------------

# One limiter key is a validated address literal plus a scope prefix, holding at
# most ``max_requests`` monotonic timestamps (120 for the widest API scope). The
# default therefore bounds the API limiter at roughly a few tens of MiB in the
# pathological case where every retained client also spent its whole budget, and
# at a small fraction of that in normal operation. It is also far above the
# distinct-client cardinality this platform sees in one 60 second window, so the
# hard bound stays a backstop rather than an operational limit.
DEFAULT_MAX_RATE_LIMIT_KEYS = 20_000

# Below this, the bound would stop being a memory guard and start being the
# limiter: a handful of ordinary concurrent clients — each holding up to one key
# per scope prefix — would evict each other's windows.
MIN_RATE_LIMIT_KEYS = 256

# Above this, the value is no longer a bound in any useful sense; it is rejected
# rather than silently clamped, so an operator who mistyped it sees it at startup
# instead of inheriting a ceiling nobody chose.
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

# A saturated store logs its first capacity eviction and then only every
# ``CAPACITY_WARNING_INTERVAL``-th one: the condition is worth an operator's
# attention, and a line per request under exactly the traffic that causes it
# would be its own resource problem.
CAPACITY_WARNING_INTERVAL = 1000


class RateLimitRetentionConfigError(ValueError):
    """Rejection of a configured rate-limit key bound.

    Carries a fixed, input-free message so startup can surface it verbatim
    without echoing the configured value.
    """


def validate_max_rate_limit_keys(value: object) -> int:
    """Return the configured key bound, or fail closed.

    Rejects non-integers (``bool`` included), values small enough that the bound
    would throttle ordinary concurrent clients, and values large enough that it
    would not bound anything. No "unlimited" sentinel exists and nothing is
    clamped: unbounded limiter state is the defect this setting exists to close.
    """
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


# --- Bounded key state ------------------------------------------------------

StateT = TypeVar("StateT")


@dataclass
class _Entry(Generic[StateT]):
    """One key's limiter state plus the activity timestamp retention reads."""

    state: StateT
    last_active: float


@dataclass(frozen=True)
class RateLimitStateSnapshot:
    """Aggregate, key-free view of one store, for metrics and startup logging."""

    name: str
    current_keys: int
    capacity: int
    retention_seconds: int
    evictions: Mapping[str, int]


class BoundedKeyStateStore(Generic[StateT]):
    """Key lifecycle for one limiter: retention, a hard bound, and counters.

    Ordered by last activity (least-recently-active first), which makes both
    evictions cheap and exact: the stale sweep pops from the front while the
    front is past the horizon, and a capacity eviction pops the front once.
    """

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
        """The state for ``key``, created if absent, with retention applied.

        Refreshes the key's activity timestamp — including for a request the
        caller goes on to refuse. That is deliberate: a client being actively
        limited is the last key that should be dropped, because dropping it is
        exactly what would hand it a fresh budget.
        """
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
        """The state for ``key`` without creating it and without refreshing it.

        For read-only evaluation: an absent key is an empty window, and answering
        that question must not grow the store.
        """
        entry = self._entries.get(key)
        return None if entry is None else entry.state

    def evict_stale(self, *, now: float) -> int:
        """Drop every key whose last activity is past the retention horizon.

        A key is kept while ``now - last_active <= retention_seconds``, matching
        the inclusive boundary the limiters' own window arithmetic uses, so a
        timestamp the limiter would still count can never be evicted first.
        """
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
        """Remove one key without counting it as an eviction.

        Used where the product itself decides the state is finished (a successful
        login clearing its failure window), which is not a retention event.
        """
        self._entries.pop(key, None)

    def clear(self) -> None:
        """Drop all keys and reset the counters. Administrative/test support."""
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
        """Enforce the hard bound before one new key is admitted."""
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


# --- Store registry ---------------------------------------------------------

# Populated when a limiter module is imported. Read only for aggregate reporting;
# it is not a lookup path for limiter state.
_STORES: dict[str, BoundedKeyStateStore] = {}


def _register_store(store: BoundedKeyStateStore) -> None:
    if store.name in _STORES:
        raise ValueError(f"a rate-limit key store named {store.name!r} is already registered")
    _STORES[store.name] = store


def state_snapshots() -> list[RateLimitStateSnapshot]:
    """Aggregate state of every registered store, ordered by store name."""
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
