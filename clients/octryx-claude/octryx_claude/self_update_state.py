"""What self-update remembers between starts: the cached release, failed and rolled-back versions
and the pending health check of a switched version."""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

import httpx

from . import update_check
from .self_update_layout import (
    Layout,
    switch,
)
from .state import LocalState, read_json, write_private_json

CACHE_NAME = ".self-update.json"

CACHE_SECONDS = 60

FAILED_RETRY_SECONDS = 60 * 60

PENDING_NAME = ".pending-health.json"

MAX_START_ATTEMPTS = 3

ROLLED_BACK_RETRY_SECONDS = 24 * 60 * 60

FLIP_FLOP_SECONDS = 60 * 60

CHECK_TIMEOUT_SECONDS = 2.0

CACHED_FAILURE = "cached_failure"

# What survives a fresh version check in the cache file: failures, rollbacks and the version just left.
_KEPT_KEYS = ("failed_version", "failed_at", "rolled_back_version", "rolled_back_at", "left_version", "left_at")

def _cached_release(state: LocalState, base_url: str, now: float, http: httpx.Client,
                    timeout: float = CHECK_TIMEOUT_SECONDS) -> update_check.Release:
    cache_path = state.root / CACHE_NAME
    cache = read_json(cache_path)
    fresh = cache.get("base_url") == base_url and 0 <= now - float(cache.get("checked_at") or 0) < CACHE_SECONDS
    if fresh:
        release = cache.get("release")
        if isinstance(release, dict):
            with contextlib.suppress(TypeError):
                return update_check.Release(**release)
        raise update_check.ReleaseUnavailableError(CACHED_FAILURE)  # warned when it happened
    entry = {key: cache[key] for key in _KEPT_KEYS if key in cache}
    entry.update(base_url=base_url, checked_at=now)
    try:
        release = update_check.served_release(http, base_url, timeout=timeout)
    except update_check.ReleaseUnavailableError as exc:
        write_private_json(cache_path, {**entry, "error": exc.code})
        raise
    write_private_json(cache_path, {**entry, "release": release.__dict__})
    return release

def _recently_failed(state: LocalState, version: str, now: float) -> bool:
    cache = read_json(state.root / CACHE_NAME)
    return cache.get("failed_version") == version and now - float(cache.get("failed_at") or 0) < FAILED_RETRY_SECONDS

def _remember_failure(state: LocalState, version: str, now: float) -> None:
    cache = read_json(state.root / CACHE_NAME)
    write_private_json(state.root / CACHE_NAME, {**cache, "failed_version": version, "failed_at": now})

def _remember(state: LocalState, **entries: object) -> None:
    cache = read_json(state.root / CACHE_NAME)
    write_private_json(state.root / CACHE_NAME, {**cache, **entries})

def _held_back(state: LocalState, version: str, now: float) -> bool:
    cache = read_json(state.root / CACHE_NAME)
    try:
        if cache.get("rolled_back_version") == version and \
                now - float(cache.get("rolled_back_at") or 0) < ROLLED_BACK_RETRY_SECONDS:
            return True
        return cache.get("left_version") == version and now - float(cache.get("left_at") or 0) < FLIP_FLOP_SECONDS
    except (TypeError, ValueError):
        return False

def _pending_path(layout: Layout) -> Path:
    return layout.venvs / PENDING_NAME

def mark_pending(layout: Layout, version: str, previous: str, now: float) -> None:
    write_private_json(_pending_path(layout), {"version": version, "previous": previous, "attempts": 0,
                                               "switched_at": now})

def start_attempt(state: LocalState, layout: Layout, running: str, *, now: float | None = None) -> str:
    pending = read_json(_pending_path(layout))
    if not running or pending.get("version") != running:
        return ""
    moment = time.time() if now is None else now
    try:
        attempts = int(pending.get("attempts") or 0) + 1
    except (TypeError, ValueError):
        attempts = 1
    previous = str(pending.get("previous") or "")
    if attempts > MAX_START_ATTEMPTS and previous and previous != running and (layout.venvs / previous).is_dir():
        switch(layout, previous)
        _remember(state, rolled_back_version=running, rolled_back_at=moment)
        with contextlib.suppress(FileNotFoundError):
            _pending_path(layout).unlink()
        return previous
    write_private_json(_pending_path(layout), {**pending, "attempts": attempts})
    return ""

def confirm_healthy(layout: Layout, running: str) -> None:
    if read_json(_pending_path(layout)).get("version") == running:
        with contextlib.suppress(FileNotFoundError):
            _pending_path(layout).unlink()
