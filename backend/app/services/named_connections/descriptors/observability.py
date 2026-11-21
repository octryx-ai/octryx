"""Grafana, Loki and Prometheus: one named connection per instance, bound to instance labels.

The tools of these connectors name no account or cluster of their own, so a connection is bound to free
instance labels (``prod-eu``, ``risk``) and a call names one with ``instance`` (or the ``connection``). Without
either and with named connections, a call is refused with the candidates. Grafana's connection is its URL and
API token; Loki and Prometheus are a URL. A named connection without them is refused before the call.
"""

from __future__ import annotations

from ..descriptor import (
    CASE_LOWER,
    UNSCOPED_SINGLE,
    Binding,
    ConnectorDescriptor,
    Field,
    UnitIncompleteError,
    require_fields,
)

INSTANCE_BINDING = Binding(
    "instance", "Instances", r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", CASE_LOWER, "instance-1, instance-2"
)
INSTANCE_PARAM = {"instance": {
    "type": "string",
    "description": "Optional: the instance (a label of its connection, e.g. prod-eu) to query.",
}}


def _instance_keys(tool_name: str, params: dict) -> tuple[str, ...]:
    instance = params.get("instance")
    return (instance.strip(),) if isinstance(instance, str) and instance.strip() else ()


def _instance(connector: str, label: str, url_field: str, secret: str | None = None) -> ConnectorDescriptor:
    required = (url_field, secret) if secret else (url_field,)

    def complete(config: dict) -> None:
        require_fields(config, *required)

    def guard(config: dict) -> None:
        if not all(str(config.get(name) or "").strip() for name in required):
            raise UnitIncompleteError("named_connection_credential_unavailable",
                                      "its URL or token is not available.")

    fields = [Field(url_field, f"{label} URL", kind="url", required=True)]
    if secret:
        fields.append(Field(secret, "API token", kind="secret", required=True))
    return ConnectorDescriptor(
        connector=connector,
        label=label,
        binding=INSTANCE_BINDING,
        fields=tuple(fields),
        usable_field=url_field,
        request_keys=_instance_keys,
        request_params=INSTANCE_PARAM,
        unscoped=UNSCOPED_SINGLE,
        complete=complete,
        runtime_guard=guard,
        testable=False,
    )


GRAFANA = _instance("grafana", "Grafana", "grafana_url", "grafana_token")
LOKI = _instance("loki", "Loki", "loki_url")
PROMETHEUS = _instance("prometheus", "Prometheus", "prometheus_url")

__all__ = ["GRAFANA", "LOKI", "PROMETHEUS"]
