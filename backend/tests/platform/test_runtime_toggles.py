from __future__ import annotations

from app.runtime_toggles import (
    DISABLE_BACKGROUND_WORKERS_ENV,
    DISABLE_KNOWLEDGE_PROJECTION_ENV,
    SKIP_CHAT_BUILD_ENV,
    background_workers_enabled,
    env_flag,
    knowledge_projection_enabled,
    skip_chat_build_enabled,
)


def test_env_flag_recognizes_truthy_values() -> None:
    assert env_flag("FLAG", env={"FLAG": "1"}) is True
    assert env_flag("FLAG", env={"FLAG": " true "}) is True
    assert env_flag("FLAG", env={"FLAG": "YES"}) is True
    assert env_flag("FLAG", env={"FLAG": "on"}) is True


def test_runtime_toggles_preserve_default_enabled_fallbacks() -> None:
    assert skip_chat_build_enabled(env={}) is False
    assert background_workers_enabled(env={}) is True
    assert knowledge_projection_enabled(env={}) is True


def test_runtime_toggles_respect_disable_flags() -> None:
    assert skip_chat_build_enabled(env={SKIP_CHAT_BUILD_ENV: "1"}) is True
    assert background_workers_enabled(env={DISABLE_BACKGROUND_WORKERS_ENV: "1"}) is False
    assert knowledge_projection_enabled(env={DISABLE_KNOWLEDGE_PROJECTION_ENV: "1"}) is False
