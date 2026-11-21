"""Endpoint validation for the governed LiteLLM gateway client.

The endpoint is validated *before* any HTTP client is constructed, so a rejected
endpoint can never produce a request. Denials are fixed reason codes: the raw
URL is never echoed back, because an operator can paste credentials into it.

Plain ``http`` is admitted in exactly two shapes:

- a loopback host (local fixture / dev), and
- a Kubernetes cluster-internal Service name (``<svc>.<ns>.svc.cluster.local``),
  and only when the caller says the gateway section *declares* the
  ``plaintext_cluster_internal`` transport mode. The transport policy then
  re-checks the host and requires the operator's node-encryption attestation;
  this module only refuses to let any other plaintext origin through.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit

# Fixed denial reasons. These are audit codes, not messages: they never carry
# any fragment of the configured URL.
ENDPOINT_DENIAL_NOT_CONFIGURED = "endpoint_not_configured"
ENDPOINT_DENIAL_UNPARSABLE = "endpoint_unparsable"
ENDPOINT_DENIAL_SCHEME_NOT_SUPPORTED = "endpoint_scheme_not_supported"
ENDPOINT_DENIAL_INSECURE_OFF_LOOPBACK = "endpoint_insecure_off_loopback"
ENDPOINT_DENIAL_USERINFO_PRESENT = "endpoint_userinfo_present"
ENDPOINT_DENIAL_QUERY_PRESENT = "endpoint_query_present"
ENDPOINT_DENIAL_FRAGMENT_PRESENT = "endpoint_fragment_present"
ENDPOINT_DENIAL_UNEXPECTED_PATH = "endpoint_unexpected_path"
ENDPOINT_DENIAL_HOST_MISSING = "endpoint_host_missing"
ENDPOINT_DENIAL_HOST_ALLOWLIST_NOT_CONFIGURED = "endpoint_host_allowlist_not_configured"
ENDPOINT_DENIAL_HOST_ALLOWLIST_INVALID = "endpoint_host_allowlist_invalid"
ENDPOINT_DENIAL_HOST_NOT_ALLOWLISTED = "endpoint_host_not_allowlisted"

_SUPPORTED_SCHEMES = frozenset({"https", "http"})
# A LiteLLM OpenAI-compatible base URL is either the bare origin or the pinned
# ``/v1`` prefix. Anything else is an unexpected path and stays denied, so a
# misconfigured provider cannot silently address a different upstream surface.
_ALLOWED_BASE_PATHS = frozenset({"", "/", "/v1"})
_LOOPBACK_HOST_NAMES = frozenset({"localhost"})
# The one suffix a cluster-internal plaintext endpoint may carry: a fully
# qualified Kubernetes Service name. Not the ``.svc`` short form (resolved through
# the pod's search path, so it names whatever the resolver config makes it), not
# a pod or node name, not another cluster domain, and never an IP address.
CLUSTER_INTERNAL_SERVICE_SUFFIX = ".svc.cluster.local"
_DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class GatewayEndpoint:
    """A validated gateway origin that is safe to build a client for."""

    base_url: str
    scheme: str
    host: str
    port: int | None
    base_path: str
    loopback: bool
    # True when the host is a fully qualified cluster-internal Service name.
    # Recorded for every scheme; only ``plaintext_cluster_internal`` relies on it.
    cluster_internal: bool = False

    def evidence(self) -> dict[str, object]:
        return {
            "endpoint_scheme": self.scheme,
            "endpoint_host": self.host,
            "endpoint_port": self.port,
            "endpoint_base_path": self.base_path,
            "endpoint_loopback": self.loopback,
            "endpoint_cluster_internal": self.cluster_internal,
        }


@dataclass(frozen=True, slots=True)
class EndpointValidation:
    endpoint: GatewayEndpoint | None
    denial_reason: str

    @property
    def accepted(self) -> bool:
        return self.endpoint is not None


def normalize_host_allowlist(value: object) -> tuple[tuple[str, ...], str]:
    """Normalize the configured host allowlist, or return a fixed denial code."""

    if not isinstance(value, (list, tuple)):
        return (), ENDPOINT_DENIAL_HOST_ALLOWLIST_NOT_CONFIGURED
    hosts: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return (), ENDPOINT_DENIAL_HOST_ALLOWLIST_INVALID
        host = item.strip().lower()
        if not host:
            return (), ENDPOINT_DENIAL_HOST_ALLOWLIST_INVALID
        # An allowlist entry is a bare host. Accepting a scheme, port, path, or
        # wildcard here would turn the allowlist into a pattern matcher.
        if any(token in host for token in ("/", ":", "@", "?", "#", "*", " ")):
            return (), ENDPOINT_DENIAL_HOST_ALLOWLIST_INVALID
        hosts.append(host)
    if not hosts:
        return (), ENDPOINT_DENIAL_HOST_ALLOWLIST_NOT_CONFIGURED
    return tuple(sorted(set(hosts))), ""


def _is_loopback_host(host: str) -> bool:
    if host in _LOOPBACK_HOST_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_cluster_internal_service_host(host: object) -> bool:
    """True only for a fully qualified ``<service>.<namespace>.svc.cluster.local``.

    Exact suffix match on the already lowercased host, at least a service and a
    namespace label in front of it, every label a plain DNS label. An IP literal
    can never match, and neither can a trailing-dot FQDN, a wildcard, or a host
    that merely contains the suffix somewhere in the middle.
    """

    if not isinstance(host, str) or host != host.strip().lower():
        return False
    if not host.endswith(CLUSTER_INTERNAL_SERVICE_SUFFIX):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    prefix = host[: -len(CLUSTER_INTERNAL_SERVICE_SUFFIX)]
    labels = prefix.split(".") if prefix else []
    if len(labels) < 2:
        return False
    return all(_DNS_LABEL_RE.match(label) for label in labels)


def _url_shape_denial(parts: SplitResult, scheme: str) -> str:
    """The first fixed denial of the URL's scheme, userinfo, query or fragment; ``""`` when none."""

    if scheme not in _SUPPORTED_SCHEMES:
        return ENDPOINT_DENIAL_SCHEME_NOT_SUPPORTED
    if parts.username or parts.password:
        return ENDPOINT_DENIAL_USERINFO_PRESENT
    if parts.query:
        return ENDPOINT_DENIAL_QUERY_PRESENT
    if parts.fragment:
        return ENDPOINT_DENIAL_FRAGMENT_PRESENT
    return ""


def validate_gateway_endpoint(
    raw_url: object,
    *,
    allowed_hosts: object,
    cluster_internal_plaintext_declared: bool = False,
) -> EndpointValidation:
    """Validate a configured gateway endpoint against the required host allowlist.

    ``cluster_internal_plaintext_declared`` is the caller's statement that the
    gateway section declares the ``plaintext_cluster_internal`` transport mode
    (``transport_policy.declares_cluster_internal_plaintext``). Without it, plain
    ``http`` stays loopback-only.
    """

    hosts, allowlist_denial = normalize_host_allowlist(allowed_hosts)
    if allowlist_denial:
        return EndpointValidation(None, allowlist_denial)

    candidate = raw_url.strip() if isinstance(raw_url, str) else ""
    if not candidate:
        return EndpointValidation(None, ENDPOINT_DENIAL_NOT_CONFIGURED)
    try:
        parts = urlsplit(candidate)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return EndpointValidation(None, ENDPOINT_DENIAL_UNPARSABLE)

    scheme = parts.scheme.strip().lower()
    shape_denial = _url_shape_denial(parts, scheme)
    if shape_denial:
        return EndpointValidation(None, shape_denial)
    if not host:
        return EndpointValidation(None, ENDPOINT_DENIAL_HOST_MISSING)

    normalized_host = host.strip().lower()
    base_path = parts.path.rstrip("/")
    if parts.path not in _ALLOWED_BASE_PATHS and base_path not in _ALLOWED_BASE_PATHS:
        return EndpointValidation(None, ENDPOINT_DENIAL_UNEXPECTED_PATH)

    loopback = _is_loopback_host(normalized_host)
    cluster_internal = is_cluster_internal_service_host(normalized_host)
    if scheme == "http" and not loopback and not (cluster_internal and cluster_internal_plaintext_declared):
        return EndpointValidation(None, ENDPOINT_DENIAL_INSECURE_OFF_LOOPBACK)
    if normalized_host not in hosts:
        return EndpointValidation(None, ENDPOINT_DENIAL_HOST_NOT_ALLOWLISTED)

    authority = normalized_host if port is None else f"{normalized_host}:{port}"
    return EndpointValidation(
        GatewayEndpoint(
            base_url=f"{scheme}://{authority}{base_path}",
            scheme=scheme,
            host=normalized_host,
            port=port,
            base_path=base_path,
            loopback=loopback,
            cluster_internal=cluster_internal,
        ),
        "",
    )


__all__ = [
    "CLUSTER_INTERNAL_SERVICE_SUFFIX",
    "ENDPOINT_DENIAL_FRAGMENT_PRESENT",
    "ENDPOINT_DENIAL_HOST_ALLOWLIST_INVALID",
    "ENDPOINT_DENIAL_HOST_ALLOWLIST_NOT_CONFIGURED",
    "ENDPOINT_DENIAL_HOST_MISSING",
    "ENDPOINT_DENIAL_HOST_NOT_ALLOWLISTED",
    "ENDPOINT_DENIAL_INSECURE_OFF_LOOPBACK",
    "ENDPOINT_DENIAL_NOT_CONFIGURED",
    "ENDPOINT_DENIAL_QUERY_PRESENT",
    "ENDPOINT_DENIAL_SCHEME_NOT_SUPPORTED",
    "ENDPOINT_DENIAL_UNEXPECTED_PATH",
    "ENDPOINT_DENIAL_UNPARSABLE",
    "ENDPOINT_DENIAL_USERINFO_PRESENT",
    "EndpointValidation",
    "GatewayEndpoint",
    "is_cluster_internal_service_host",
    "normalize_host_allowlist",
    "validate_gateway_endpoint",
]
