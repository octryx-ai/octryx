"""Canonical execution runtime package surface."""

from .config import (
    ALLOWED_EXECUTION_RUNTIME_NETWORK_MODES,
    ALLOWED_EXECUTION_RUNTIME_PROVIDERS,
    ALLOWED_EXECUTION_RUNTIME_SANDBOX_MODES,
    DEFAULT_EXECUTION_RUNTIME_DOCKER_IMAGE,
    DEFAULT_EXECUTION_RUNTIME_DOCKER_MEMORY_MB,
    DEFAULT_EXECUTION_RUNTIME_DOCKER_PIDS_LIMIT,
    DEFAULT_EXECUTION_RUNTIME_NETWORK_MODE,
    DEFAULT_EXECUTION_RUNTIME_PROVIDER,
    DEFAULT_EXECUTION_RUNTIME_SANDBOX_MODE,
    ExecutionRuntimeConfig,
    resolve_execution_runtime_config,
)
from .contracts import ExecutionRuntimeMount, ExecutionRuntimeResult, workspace_mount_for_path
from .service import ExecutionRuntimeUnavailableError, execute_with_runtime

__all__ = [
    "ALLOWED_EXECUTION_RUNTIME_NETWORK_MODES",
    "ALLOWED_EXECUTION_RUNTIME_PROVIDERS",
    "ALLOWED_EXECUTION_RUNTIME_SANDBOX_MODES",
    "DEFAULT_EXECUTION_RUNTIME_DOCKER_IMAGE",
    "DEFAULT_EXECUTION_RUNTIME_DOCKER_MEMORY_MB",
    "DEFAULT_EXECUTION_RUNTIME_DOCKER_PIDS_LIMIT",
    "DEFAULT_EXECUTION_RUNTIME_NETWORK_MODE",
    "DEFAULT_EXECUTION_RUNTIME_PROVIDER",
    "DEFAULT_EXECUTION_RUNTIME_SANDBOX_MODE",
    "ExecutionRuntimeConfig",
    "ExecutionRuntimeMount",
    "ExecutionRuntimeResult",
    "ExecutionRuntimeUnavailableError",
    "execute_with_runtime",
    "resolve_execution_runtime_config",
    "workspace_mount_for_path",
]
