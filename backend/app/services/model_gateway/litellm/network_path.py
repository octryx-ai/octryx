"""The least-privilege network path of the governed LiteLLM gateway client.

An operator opening firewall or NetworkPolicy egress for this client should not
have to read the adapter to learn what it needs. The path is derived from the
already-validated endpoint, transport policy and probe contract, so the contract
cannot drift from what the client actually does:

- egress only: the client never listens, and nothing calls back into it;
- one destination: the validated gateway host, or the governed proxy hop when one
  is configured (the gateway then becomes a proxy ACL entry, not a firewall rule);
- two request paths and two methods: ``GET`` on the pinned probe path and ``POST``
  on ``/chat/completions``;
- no redirects, so the destination set cannot grow at runtime;
- no ambient environment trust, so the destination set cannot be changed by a
  process variable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import CHAT_COMPLETIONS_PATH
from .config import ProbeContract
from .endpoint import GatewayEndpoint
from .proxy_admission import default_port_for_scheme
from .transport_decisions import TransportPolicy

DIRECTION_EGRESS_ONLY = "egress_only"

# Hop roles. ``direct_egress`` and ``proxy_egress`` are firewall rules; a
# ``tunneled_destination`` is an ACL entry on the governed proxy, because the
# client never opens a socket to it itself.
HOP_ROLE_DIRECT_EGRESS = "direct_egress"
HOP_ROLE_PROXY_EGRESS = "proxy_egress"
HOP_ROLE_TUNNELED_DESTINATION = "tunneled_destination"

ALLOWED_METHODS = ("GET", "POST")


@dataclass(frozen=True, slots=True)
class NetworkHop:
    role: str
    scheme: str
    host: str
    port: int

    def rule(self) -> str:
        return f"{self.role}:{self.scheme}:{self.host}:{self.port}"


@dataclass(frozen=True, slots=True)
class NetworkPathContract:
    direction: str
    hops: tuple[NetworkHop, ...]
    allowed_methods: tuple[str, ...]
    allowed_request_paths: tuple[str, ...]
    tls_mode: str
    proxy_mode: str
    follows_redirects: bool
    trusts_ambient_environment: bool

    def egress_rules(self) -> tuple[str, ...]:
        """Deterministic, sorted rule strings for a firewall or proxy ACL."""

        return tuple(sorted(hop.rule() for hop in self.hops))

    def evidence(self) -> dict[str, Any]:
        return {
            "network_path_direction": self.direction,
            "network_path_hops": list(self.egress_rules()),
            "network_path_allowed_methods": list(self.allowed_methods),
            "network_path_allowed_request_paths": list(self.allowed_request_paths),
            "network_path_follows_redirects": self.follows_redirects,
            "network_path_trusts_ambient_environment": self.trusts_ambient_environment,
        }


def _endpoint_port(endpoint: GatewayEndpoint) -> int:
    if endpoint.port is not None:
        return endpoint.port
    # The endpoint validator admits only http/https, so a default always exists.
    return default_port_for_scheme(endpoint.scheme) or 0


def build_network_path_contract(
    *,
    endpoint: GatewayEndpoint,
    transport: TransportPolicy,
    probe: ProbeContract,
) -> NetworkPathContract:
    """Derive the least-privilege network path from the validated configuration."""

    gateway_port = _endpoint_port(endpoint)
    if transport.proxy.governed:
        hops = (
            NetworkHop(
                HOP_ROLE_PROXY_EGRESS,
                transport.proxy.scheme,
                transport.proxy.host,
                int(transport.proxy.port or default_port_for_scheme(transport.proxy.scheme) or 0),
            ),
            NetworkHop(HOP_ROLE_TUNNELED_DESTINATION, endpoint.scheme, endpoint.host, gateway_port),
        )
    else:
        hops = (NetworkHop(HOP_ROLE_DIRECT_EGRESS, endpoint.scheme, endpoint.host, gateway_port),)
    base = endpoint.base_path
    return NetworkPathContract(
        direction=DIRECTION_EGRESS_ONLY,
        hops=hops,
        allowed_methods=ALLOWED_METHODS,
        allowed_request_paths=(f"{base}{probe.models_path}", f"{base}{CHAT_COMPLETIONS_PATH}"),
        tls_mode=transport.tls.mode,
        proxy_mode=transport.proxy.mode,
        # Both are structural properties of the client (see ``client.py``), stated
        # here so the contract records them instead of leaving them implicit.
        follows_redirects=False,
        trusts_ambient_environment=False,
    )


__all__ = [
    "ALLOWED_METHODS",
    "DIRECTION_EGRESS_ONLY",
    "HOP_ROLE_DIRECT_EGRESS",
    "HOP_ROLE_PROXY_EGRESS",
    "HOP_ROLE_TUNNELED_DESTINATION",
    "NetworkHop",
    "NetworkPathContract",
    "build_network_path_contract",
]
