from __future__ import annotations

from typing import Any

from .db import async_session_factory as default_async_session_factory
from .runtime_setup import PlatformRuntime, build_platform_runtime

_platform_runtime: PlatformRuntime | None = None


def get_platform_runtime(session_factory: object | None = None) -> PlatformRuntime:
    """Return the process-wide platform runtime owned outside the FastAPI entrypoint."""
    global _platform_runtime
    if _platform_runtime is None:
        _platform_runtime = build_platform_runtime(session_factory or default_async_session_factory)
    elif session_factory is not None:
        _set_runtime_session_factory(_platform_runtime, session_factory)
    return _platform_runtime


def get_task_scheduler() -> Any:
    """Return the scheduler attached to the process-wide platform runtime."""
    return get_platform_runtime().task_scheduler


def set_runtime_session_factory(session_factory: object) -> PlatformRuntime:
    """Update runtime and scheduler session factories together."""
    runtime = get_platform_runtime()
    _set_runtime_session_factory(runtime, session_factory)
    return runtime


def replace_platform_runtime_for_tests(runtime: PlatformRuntime | None) -> None:
    """Replace the singleton in focused tests without importing the FastAPI app."""
    global _platform_runtime
    _platform_runtime = runtime


def _set_runtime_session_factory(runtime: PlatformRuntime, session_factory: object) -> None:
    runtime.async_session_factory = session_factory
    runtime.task_scheduler.set_session_factory(session_factory)
