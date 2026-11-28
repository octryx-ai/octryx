"""Padded forwarding chains cannot evict the proxy-appended client or scheme, and non-IP peers, unknown schemes, websocket transports and header containers are handled fail-closed."""

from __future__ import annotations

import pytest

import app.trusted_proxy_policy as boundary
from app.trusted_proxy_policy import CLIENT_SOURCE_TRUSTED_PROXY, resolve_client_identity
from tests.support.trusted_proxy_test_utils import (
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
    header = ", ".join([*PADDING, REAL_CLIENT])
    resolved = identity(
        request(peer=PROXY_PEER, headers={"x-forwarded-for": header}),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT
    assert resolved.source == CLIENT_SOURCE_TRUSTED_PROXY
    assert resolved.client_address not in PADDING


def test_padded_rfc_forwarded_header_cannot_evict_the_proxy_appended_client():
    header = ", ".join([*(f"for={entry}" for entry in PADDING), f"for={REAL_CLIENT}"])
    resolved = identity(
        request(peer=PROXY_PEER, headers={"forwarded": header}),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT
    assert resolved.source == CLIENT_SOURCE_TRUSTED_PROXY
    assert resolved.client_address not in PADDING


def test_padded_forwarded_chain_still_skips_trusted_hops():
    header = ", ".join([*PADDING, REAL_CLIENT, SECOND_PROXY_PEER, PROXY_PEER])
    resolved = identity(
        request(peer=PROXY_PEER, headers={"x-forwarded-for": header}),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT


def test_padded_forwarded_proto_is_still_read_from_the_first_hop():
    header = ", ".join(["proto=https", *(f"for={entry}" for entry in PADDING)])
    resolved = identity(
        request(peer=PROXY_PEER, headers={"forwarded": header}),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.scheme == "https"


def test_padded_forwarded_proto_is_still_read_from_the_appended_hop():
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
    assert boundary.forwarded_scheme({"x-forwarded-proto": "https"}) == "https"
    assert boundary.forwarded_scheme(None) == ""

    class NotHeaders:
        pass

    with pytest.raises(TypeError):
        boundary.forwarded_scheme(NotHeaders())
