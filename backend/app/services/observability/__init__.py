"""Service helper package: observability."""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "_DB_CONCURRENCY_COUNTER": "..db_concurrency_observability",
    "record_db_concurrency_event": "..db_concurrency_observability",
    "reset_db_concurrency_events": "..db_concurrency_observability",
    "JsonLogFormatter": ".logging",
    "configure_json_logging": ".logging",
    "_HTTP_REQUEST_COUNTER": ".request_metrics",
    "recent_request_summary": ".request_metrics",
    "record_request_counter": ".request_metrics",
    "render_prometheus_metrics": ".metrics_render",
    "run_platform_health_checks": ".health_checks",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value
