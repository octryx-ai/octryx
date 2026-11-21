"""Execution runtime entry points, read from their defining modules at call time so a test replaces them there."""

from __future__ import annotations

from ...services.execution_runtime import config as _runtime_config
from ...services.execution_runtime import service as _runtime_service


def _resolve_runtime_execution_config():
    return _runtime_config.resolve_execution_runtime_config


def _resolve_execute_with_runtime():
    return _runtime_service.execute_with_runtime
