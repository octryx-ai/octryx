"""Forwarded client and scheme are applied only from a trusted peer, trusted hops are skipped, address and scheme shapes are normalized, and X-Forwarded-For wins over the Forwarded header."""

from __future__ import annotations

import pytest

from app.trusted_proxy_policy import CLIENT_SOURCE_TRANSPORT_PEER, CLIENT_SOURCE_TRUSTED_PROXY
from tests.trusted_proxy_test_utils import (
    PROXY_NETWORK,
    PROXY_PEER,
    REAL_CLIENT,
    REMOTE_PEER,
    SECOND_PROXY_PEER,
    identity,
    request,
    settings,
)

# --- Identity decision matrix ----------------------------------------------


def test_untrusted_peer_forwarded_headers_are_ignored():
    resolved = identity(
        request(
            peer=REMOTE_PEER,
            headers={"x-forwarded-for": REAL_CLIENT, "x-forwarded-proto": "https"},
        ),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REMOTE_PEER
    assert resolved.peer_address == REMOTE_PEER
    assert resolved.scheme == "http"
    assert resolved.via_trusted_proxy is False
    assert resolved.source == CLIENT_SOURCE_TRANSPORT_PEER
    assert resolved.forwarded_headers_present is True


def test_empty_allowlist_trusts_nothing():
    resolved = identity(
        request(peer=PROXY_PEER, headers={"x-forwarded-for": REAL_CLIENT, "x-forwarded-proto": "https"}),
        settings(trusted_proxy_ips=""),
    )
    assert resolved.client_address == PROXY_PEER
    assert resolved.scheme == "http"
    assert resolved.via_trusted_proxy is False


def test_trusted_peer_forwarded_client_and_scheme_are_applied():
    resolved = identity(
        request(peer=PROXY_PEER, headers={"x-forwarded-for": REAL_CLIENT, "x-forwarded-proto": "https"}),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT
    assert resolved.peer_address == PROXY_PEER
    assert resolved.scheme == "https"
    assert resolved.via_trusted_proxy is True
    assert resolved.source == CLIENT_SOURCE_TRUSTED_PROXY
    assert resolved.forwarded_scheme_applied is True


def test_trusted_chain_skips_trusted_hops_and_takes_the_client():
    resolved = identity(
        request(
            peer=PROXY_PEER,
            headers={"x-forwarded-for": f"{REAL_CLIENT}, {SECOND_PROXY_PEER}, {PROXY_PEER}"},
        ),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT


def test_trusted_peer_without_usable_forwarded_address_stays_attributed_to_the_proxy():
    for headers in ({"x-forwarded-for": "not-an-ip"}, {"x-forwarded-proto": "https"}, {}):
        resolved = identity(
            request(peer=PROXY_PEER, headers=headers),
            settings(trusted_proxy_ips=PROXY_NETWORK),
        )
        assert resolved.client_address == PROXY_PEER
        assert resolved.source == CLIENT_SOURCE_TRANSPORT_PEER


def test_forwarded_address_shapes_are_normalized():
    resolved_settings = settings(trusted_proxy_ips=PROXY_NETWORK)
    cases = {
        f"{REAL_CLIENT}:51344": REAL_CLIENT,
        "[2001:db8::1]:51344": "2001:db8::1",
        "::ffff:198.51.100.7": REAL_CLIENT,
    }
    for raw, expected in cases.items():
        resolved = identity(request(peer=PROXY_PEER, headers={"x-forwarded-for": raw}), resolved_settings)
        assert resolved.client_address == expected


def test_trusted_proxy_never_downgrades_a_secure_transport():
    resolved = identity(
        request(peer=PROXY_PEER, scheme="https", headers={"x-forwarded-proto": "http"}),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.scheme == "https"
    assert resolved.forwarded_scheme_applied is False


@pytest.mark.parametrize(
    "headers",
    [
        {"forwarded": "proto=https"},
        {"forwarded": 'for=198.51.100.7;proto="https"'},
        {"x-forwarded-proto": "https, http"},
        # Fail-secure: a client-supplied insecure first element must not suppress
        # the secure claim the proxy appended to the same header.
        {"x-forwarded-proto": "http, https"},
        {"x-forwarded-proto": "http, http, https"},
        {"forwarded": "proto=http, proto=https"},
        # An insecure X-Forwarded-Proto must not shadow a secure Forwarded element.
        {"x-forwarded-proto": "http", "forwarded": "proto=https"},
    ],
)
def test_forwarded_scheme_variants_are_accepted_from_a_trusted_peer(headers):
    resolved = identity(request(peer=PROXY_PEER, headers=headers), settings(trusted_proxy_ips=PROXY_NETWORK))
    assert resolved.scheme == "https"


@pytest.mark.parametrize(
    "headers",
    [
        {"x-forwarded-proto": "http"},
        {"x-forwarded-proto": "http, http"},
        {"forwarded": "proto=http, proto=http"},
        {"x-forwarded-proto": "gopher, http"},
    ],
)
def test_an_all_insecure_scheme_chain_stays_insecure(headers):
    """Fail-secure raises a claim; it must never invent one."""
    resolved = identity(request(peer=PROXY_PEER, headers=headers), settings(trusted_proxy_ips=PROXY_NETWORK))
    assert resolved.scheme == "http"
    assert resolved.forwarded_scheme_applied is False


def test_forwarded_for_parameter_is_read_when_no_x_forwarded_for_exists():
    """An RFC 7239-only proxy must not collapse all its clients into one bucket."""
    resolved = identity(
        request(peer=PROXY_PEER, headers={"forwarded": f"for={REAL_CLIENT};proto=https"}),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT
    assert resolved.scheme == "https"


def test_multi_element_forwarded_header_is_parsed_per_element():
    resolved = identity(
        request(
            peer=PROXY_PEER,
            headers={"forwarded": f"for={REAL_CLIENT};proto=https, for={PROXY_PEER};proto=http"},
        ),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT
    assert resolved.scheme == "https"


def test_x_forwarded_for_wins_over_the_forwarded_header():
    resolved = identity(
        request(
            peer=PROXY_PEER,
            headers={"x-forwarded-for": REAL_CLIENT, "forwarded": "for=192.0.2.77"},
        ),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT
