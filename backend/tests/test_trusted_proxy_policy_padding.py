"""Padded forwarding chains cannot evict the proxy-appended client or scheme, and non-IP peers, unknown schemes, websocket transports and header containers are handled fail-closed."""

from __future__ import annotations

import pytest

import app.trusted_proxy_policy as boundary
from app.trusted_proxy_policy import CLIENT_SOURCE_TRUSTED_PROXY, resolve_client_identity
from tests.trusted_proxy_test_utils import (
    PADDING,
    PROXY_NETWORK,
    PROXY_PEER,
    REAL_CLIENT,
    SECOND_PROXY_PEER,
    identity,
    request,
    settings,
)


def test_padded_x_forwarded_for_cannot_evict_the_proxy_appended_client():
    """Truncation keeps the rightmost hops, so padding cannot pick the client.

    The client sends a pre-filled ``X-Forwarded-For`` longer than the bound; the
    trusted proxy appends the address it actually saw. Keeping the leftmost
    elements would drop that appended evidence and hand the attacker's own last
    entry to the rightmost-wins scan.
    """
    header = ", ".join([*PADDING, REAL_CLIENT])
    resolved = identity(
        request(peer=PROXY_PEER, headers={"x-forwarded-for": header}),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT
    assert resolved.source == CLIENT_SOURCE_TRUSTED_PROXY
    assert resolved.client_address not in PADDING


def test_padded_rfc_forwarded_header_cannot_evict_the_proxy_appended_client():
    """Same guarantee for an RFC 7239 ``Forwarded`` chain."""
    header = ", ".join([*(f"for={entry}" for entry in PADDING), f"for={REAL_CLIENT}"])
    resolved = identity(
        request(peer=PROXY_PEER, headers={"forwarded": header}),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT
    assert resolved.source == CLIENT_SOURCE_TRUSTED_PROXY
    assert resolved.client_address not in PADDING


def test_padded_forwarded_chain_still_skips_trusted_hops():
    """Chain skipping survives truncation: trusted hops on the right are hops."""
    header = ", ".join([*PADDING, REAL_CLIENT, SECOND_PROXY_PEER, PROXY_PEER])
    resolved = identity(
        request(peer=PROXY_PEER, headers={"x-forwarded-for": header}),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT


def test_padded_forwarded_proto_is_still_read_from_the_first_hop():
    """The scheme claim survives padding at its leading end."""
    header = ", ".join(["proto=https", *(f"for={entry}" for entry in PADDING)])
    resolved = identity(
        request(peer=PROXY_PEER, headers={"forwarded": header}),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.scheme == "https"


def test_padded_forwarded_proto_is_still_read_from_the_appended_hop():
    """And at its trailing end: the claim the proxy appended cannot be evicted."""
    header = ", ".join([*(f"for={entry};proto=http" for entry in PADDING), "proto=https"])
    resolved = identity(
        request(peer=PROXY_PEER, headers={"forwarded": header}),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.scheme == "https"


def test_non_ip_peer_is_bounded_and_never_trusted():
    resolved = resolve_client_identity(
        peer_address="/run/octryx/" + "a" * 200 + ".sock",
        transport_scheme="http",
        headers={"x-forwarded-for": REAL_CLIENT},
        settings=settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.via_trusted_proxy is False
    assert resolved.client_address == resolved.peer_address
    assert len(resolved.client_address) <= boundary.MAX_ADDRESS_LENGTH


def test_unknown_forwarded_scheme_is_ignored():
    resolved = identity(
        request(peer=PROXY_PEER, headers={"x-forwarded-proto": "gopher"}),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.scheme == "http"


def test_websocket_transport_keeps_its_scheme_family():
    resolved = resolve_client_identity(
        peer_address=PROXY_PEER,
        transport_scheme="ws",
        headers={"x-forwarded-proto": "https"},
        settings=settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.scheme == "wss"


def test_a_plain_mapping_is_accepted_but_an_arbitrary_object_is_not():
    """The header source is a Headers or a Mapping; anything else is a bug."""
    assert boundary.forwarded_scheme({"x-forwarded-proto": "https"}) == "https"
    assert boundary.forwarded_scheme(None) == ""

    class NotHeaders:
        pass

    with pytest.raises(TypeError):
        boundary.forwarded_scheme(NotHeaders())
