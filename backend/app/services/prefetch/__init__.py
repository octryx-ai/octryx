"""Canonical package for tool prefetching (worker and cache; no prompt-regex planner)."""

from .cache import (
    build_prefetch_params_hash,
    lookup_prefetch_cache,
    select_prefetch_cache_ttl_seconds,
    store_prefetch_cache_result,
)
from .worker import (
    PrefetchJob,
    PrefetchRequest,
    PrefetchWorker,
    prefetch_worker,
)

__all__ = [
    "PrefetchJob",
    "PrefetchRequest",
    "PrefetchWorker",
    "build_prefetch_params_hash",
    "lookup_prefetch_cache",
    "prefetch_worker",
    "select_prefetch_cache_ttl_seconds",
    "store_prefetch_cache_result",
]
