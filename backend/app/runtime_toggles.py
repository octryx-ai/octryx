from __future__ import annotations

import os
from collections.abc import Mapping

SKIP_CHAT_BUILD_ENV = "OCTRYX_SKIP_CHAT_BUILD"
DISABLE_BACKGROUND_WORKERS_ENV = "OCTRYX_DISABLE_BACKGROUND_WORKERS"
DISABLE_KNOWLEDGE_PROJECTION_ENV = "OCTRYX_DISABLE_KNOWLEDGE_PROJECTION"
ENABLE_KNOWLEDGE_SOURCE_SYNC_SCHEDULER_ENV = "OCTRYX_ENABLE_KNOWLEDGE_SOURCE_SYNC_SCHEDULER"
# How many uvicorn processes serve the API. More than one requires the background
# workers to run in their own process (``python -m app.worker_main``), never in every API process.
API_WORKERS_ENV = "OCTRYX_API_WORKERS"
# The admin host terminal (``/api/v1/terminal``): a shell in the api container that reads the database and the disk,
# private Workspaces included. Off unless an operator switches it on for one instance.
ENABLE_HOST_TERMINAL_ENV = "OCTRYX_ENABLE_HOST_TERMINAL"

# Plugins from the image's plugin folder (``services/plugins/image``) are brought in by the API process only; the
# worker process (``app.worker_main``) may not even have the folder mounted, and must never switch them off.
SKIP_IMAGE_PLUGINS_ENV = "OCTRYX_SKIP_IMAGE_PLUGINS"

_TRUE_VALUES = {"1", "true", "yes", "on"}


def env_flag(name: str, *, env: Mapping[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return str(source.get(name) or "").strip().lower() in _TRUE_VALUES


def skip_chat_build_enabled(*, env: Mapping[str, str] | None = None) -> bool:
    return env_flag(SKIP_CHAT_BUILD_ENV, env=env)


def host_terminal_enabled(*, env: Mapping[str, str] | None = None) -> bool:
    return env_flag(ENABLE_HOST_TERMINAL_ENV, env=env)


def background_workers_enabled(*, env: Mapping[str, str] | None = None) -> bool:
    return not env_flag(DISABLE_BACKGROUND_WORKERS_ENV, env=env)


def knowledge_projection_enabled(*, env: Mapping[str, str] | None = None) -> bool:
    return not env_flag(DISABLE_KNOWLEDGE_PROJECTION_ENV, env=env)


def knowledge_source_sync_scheduler_enabled(*, env: Mapping[str, str] | None = None) -> bool:
    return env_flag(ENABLE_KNOWLEDGE_SOURCE_SYNC_SCHEDULER_ENV, env=env)


def api_worker_count(*, env: Mapping[str, str] | None = None) -> int:
    source = os.environ if env is None else env
    raw = str(source.get(API_WORKERS_ENV) or "").strip()
    if not raw:
        return 1
    try:
        count = int(raw)
    except ValueError:
        raise ValueError(f"{API_WORKERS_ENV} must be a positive integer, got {raw!r}") from None
    if count < 1:
        raise ValueError(f"{API_WORKERS_ENV} must be a positive integer, got {raw!r}")
    return count
