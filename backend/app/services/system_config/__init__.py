"""Helpers for DB-backed global system configuration."""

from __future__ import annotations

from . import constants as _impl
from .runtime_settings import get_agent_runtime_settings as get_agent_runtime_settings
from .tool_domains import (
    get_agent_tool_domain_config as get_agent_tool_domain_config,
)
from .tool_domains import (
    get_default_agent_tool_domain_config as get_default_agent_tool_domain_config,
)
from .tool_domains import (
    normalize_agent_tool_domain_config as normalize_agent_tool_domain_config,
)
from .values import (
    bounded_int as _bounded_int,
)
from .values import (
    get_agent_default_model as get_agent_default_model,
)
from .values import (
    get_system_config_value as get_system_config_value,
)
from .values import (
    get_worker_trust_deltas as get_worker_trust_deltas,
)
from .values import (
    set_system_config_value as set_system_config_value,
)

_constant_exports = getattr(_impl, "__all__", [name for name in dir(_impl) if not name.startswith("_")])
globals().update({name: getattr(_impl, name) for name in _constant_exports})


def __getattr__(name: str):  # noqa: N807
    if name == "DEFAULT_AGENT_TOOL_DOMAIN_CONFIG":
        from .tool_domains import DEFAULT_AGENT_TOOL_DOMAIN_CONFIG
        return DEFAULT_AGENT_TOOL_DOMAIN_CONFIG
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    *_constant_exports,
    "_bounded_int",
    "DEFAULT_AGENT_TOOL_DOMAIN_CONFIG",
    "get_system_config_value",
    "set_system_config_value",
    "get_agent_default_model",
    "get_worker_trust_deltas",
    "get_agent_runtime_settings",
    "get_agent_tool_domain_config",
    "get_default_agent_tool_domain_config",
    "normalize_agent_tool_domain_config",
]
