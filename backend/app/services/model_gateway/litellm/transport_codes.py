"""Fixed mode names, reason codes and limits of the gateway transport trust policy (``transport_policy``)."""

from __future__ import annotations

TLS_MODE_PRIVATE_CA_BUNDLE = "private_ca_bundle"
TLS_MODE_PUBLIC_CA_BUNDLE = "public_ca_bundle"
TLS_MODE_PLAINTEXT_LOOPBACK = "plaintext_loopback"
TLS_MODE_PLAINTEXT_CLUSTER_INTERNAL = "plaintext_cluster_internal"
TLS_MODES = frozenset(
    {
        TLS_MODE_PRIVATE_CA_BUNDLE,
        TLS_MODE_PUBLIC_CA_BUNDLE,
        TLS_MODE_PLAINTEXT_LOOPBACK,
        TLS_MODE_PLAINTEXT_CLUSTER_INTERNAL,
    }
)
PLAINTEXT_TLS_MODES = frozenset({TLS_MODE_PLAINTEXT_LOOPBACK, TLS_MODE_PLAINTEXT_CLUSTER_INTERNAL})

# Node-to-node encryption an operator may attest for ``plaintext_cluster_internal``.
# Deny-by-default: a mechanism not on this list has not been reviewed.
NODE_ENCRYPTION_WIREGUARD = "wireguard"
NODE_ENCRYPTION_MECHANISMS = frozenset({NODE_ENCRYPTION_WIREGUARD})

PROXY_MODE_DIRECT = "direct"
PROXY_MODE_GOVERNED = "governed_proxy"
PROXY_MODES = frozenset({PROXY_MODE_DIRECT, PROXY_MODE_GOVERNED})

TLS_DENIAL_CONTRACT_MISSING = "tls_contract_missing"
TLS_DENIAL_MODE_UNKNOWN = "tls_mode_unknown"
TLS_DENIAL_MODE_CONFLICTS_WITH_ENDPOINT = "tls_mode_conflicts_with_endpoint_scheme"
TLS_DENIAL_PLAINTEXT_OFF_LOOPBACK = "tls_plaintext_not_permitted_off_loopback"
TLS_DENIAL_PLAINTEXT_NOT_CLUSTER_SERVICE = "tls_plaintext_cluster_internal_host_not_cluster_service"
TLS_DENIAL_NODE_ENCRYPTION_NOT_ATTESTED = "tls_node_encryption_not_attested"
TLS_DENIAL_ATTESTATION_REFERENCE_MISSING = "tls_attestation_reference_missing"
TLS_DENIAL_ATTESTED_ON_INVALID = "tls_attested_on_invalid"
TLS_DENIAL_BUNDLE_PATH_MISSING = "tls_ca_bundle_path_not_configured"
TLS_DENIAL_BUNDLE_PATH_NOT_ABSOLUTE = "tls_ca_bundle_path_not_absolute"
TLS_DENIAL_BUNDLE_NOT_A_FILE = "tls_ca_bundle_not_a_file"
TLS_DENIAL_BUNDLE_NOT_READABLE = "tls_ca_bundle_not_readable"
TLS_DENIAL_BUNDLE_TOO_LARGE = "tls_ca_bundle_too_large"
TLS_DENIAL_BUNDLE_NO_CERTIFICATE = "tls_ca_bundle_no_certificate"
TLS_DENIAL_BUNDLE_CONTAINS_PRIVATE_KEY = "tls_ca_bundle_contains_private_key"
TLS_DENIAL_BUNDLE_NOT_LOADABLE = "tls_ca_bundle_not_loadable"
TLS_DENIAL_BUNDLE_MATERIAL_CHANGED = "tls_ca_bundle_material_changed"

PROXY_DENIAL_CONTRACT_MALFORMED = "proxy_contract_malformed"
PROXY_DENIAL_MODE_UNKNOWN = "proxy_mode_unknown"
PROXY_DENIAL_URL_NOT_CONFIGURED = "proxy_url_not_configured"
PROXY_DENIAL_URL_UNPARSABLE = "proxy_url_unparsable"
PROXY_DENIAL_SCHEME_NOT_SUPPORTED = "proxy_scheme_not_supported"
PROXY_DENIAL_USERINFO_PRESENT = "proxy_userinfo_present"
PROXY_DENIAL_QUERY_PRESENT = "proxy_query_present"
PROXY_DENIAL_FRAGMENT_PRESENT = "proxy_fragment_present"
PROXY_DENIAL_UNEXPECTED_PATH = "proxy_unexpected_path"
PROXY_DENIAL_HOST_MISSING = "proxy_host_missing"
PROXY_DENIAL_HOST_ALLOWLIST_NOT_CONFIGURED = "proxy_host_allowlist_not_configured"
PROXY_DENIAL_HOST_ALLOWLIST_INVALID = "proxy_host_allowlist_invalid"
PROXY_DENIAL_HOST_NOT_ALLOWLISTED = "proxy_host_not_allowlisted"
PROXY_DENIAL_PLAINTEXT_REQUIRES_TLS_ENDPOINT = "proxy_plaintext_requires_tls_endpoint"
PROXY_DENIAL_CLUSTER_INTERNAL_REQUIRES_DIRECT = "proxy_not_permitted_with_cluster_internal_plaintext"

# A CA bundle is a small text file. The bound exists so a misconfigured path
# (a log, a device, a database dump) is refused instead of being read into memory.
MAX_CA_BUNDLE_BYTES = 1024 * 1024
