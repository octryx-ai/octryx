"""Trusted-proxy boundary: repeated headers, rate-limit buckets, audit rows.

Two things are asserted here. First, that *every* occurrence of a forwarded
header is combined in wire order before anything is selected: a client can send
its own field line and let the proxy append a second one, and reading only the
first occurrence would hand the attribution decision to the client. Second, that
the surfaces which consume the decision — the API limiter, the auth brute-force
limiter, and the audit log — follow it.
"""

from __future__ import annotations

import app.trusted_proxy_policy as boundary
from app.services.auth.audit import client_ip_from_request
from app.trusted_proxy_policy import CLIENT_SOURCE_TRUSTED_PROXY, rate_limit_client_key
from tests.trusted_proxy_test_utils import (
    PADDING,
    PROXY_NETWORK,
    PROXY_PEER,
    REAL_CLIENT,
    REMOTE_PEER,
    SECOND_PROXY_PEER,
    identity,
    request,
    settings,
)

CLIENT_SUPPLIED = "192.0.2.66"


# --- Repeated header fields -------------------------------------------------


def test_a_second_x_forwarded_for_field_line_is_appended_not_ignored():
    """Client-supplied first line, proxy-appended second line: the proxy wins.

    HTTP treats the two field lines as one list in the order received, which is
    what a proxy relies on when it adds its own header instead of extending the
    client's. Reading only the first occurrence would return the client's own
    ``X-Forwarded-For`` and let it choose its rate-limit bucket and audit row.
    """
    resolved = identity(
        request(
            peer=PROXY_PEER,
            headers=[("x-forwarded-for", CLIENT_SUPPLIED), ("x-forwarded-for", REAL_CLIENT)],
        ),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT
    assert resolved.source == CLIENT_SOURCE_TRUSTED_PROXY


def test_a_second_rfc_forwarded_field_line_is_appended_not_ignored():
    """Same guarantee for an RFC 7239 ``Forwarded`` chain split over two lines."""
    resolved = identity(
        request(
            peer=PROXY_PEER,
            headers=[("forwarded", f"for={CLIENT_SUPPLIED}"), ("forwarded", f"for={REAL_CLIENT}")],
        ),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT
    assert resolved.source == CLIENT_SOURCE_TRUSTED_PROXY


def test_repeated_field_lines_still_skip_trusted_hops():
    """Combining must feed the chain scan, not bypass it."""
    resolved = identity(
        request(
            peer=PROXY_PEER,
            headers=[
                ("x-forwarded-for", CLIENT_SUPPLIED),
                ("x-forwarded-for", f"{REAL_CLIENT}, {SECOND_PROXY_PEER}"),
                ("x-forwarded-for", PROXY_PEER),
            ],
        ),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT


def test_padding_spread_over_many_field_lines_cannot_evict_the_appended_client():
    """The bound applies to the combined chain, not per field line."""
    resolved = identity(
        request(
            peer=PROXY_PEER,
            headers=[*((("x-forwarded-for", entry)) for entry in PADDING), ("x-forwarded-for", REAL_CLIENT)],
        ),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REAL_CLIENT
    assert resolved.client_address not in PADDING


def test_a_client_supplied_insecure_proto_line_cannot_suppress_the_appended_secure_one():
    """Fail-secure scheme resolution across repeated field lines."""
    resolved = identity(
        request(
            peer=PROXY_PEER,
            headers=[
                ("x-forwarded-proto", "http"),
                ("x-forwarded-for", REAL_CLIENT),
                ("x-forwarded-proto", "https"),
            ],
        ),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.scheme == "https"
    assert resolved.forwarded_scheme_applied is True


def test_repeated_secure_proto_still_cannot_downgrade_a_secure_transport():
    """The other direction stays closed: https transport, http claims, still https."""
    resolved = identity(
        request(
            peer=PROXY_PEER,
            scheme="https",
            headers=[("x-forwarded-proto", "http"), ("x-forwarded-proto", "http")],
        ),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.scheme == "https"
    assert resolved.forwarded_scheme_applied is False


def test_repeated_headers_from_an_untrusted_peer_are_still_ignored():
    resolved = identity(
        request(
            peer=REMOTE_PEER,
            headers=[("x-forwarded-for", CLIENT_SUPPLIED), ("x-forwarded-for", REAL_CLIENT)],
        ),
        settings(trusted_proxy_ips=PROXY_NETWORK),
    )
    assert resolved.client_address == REMOTE_PEER
    assert resolved.scheme == "http"


def test_repeated_headers_choose_neither_bucket_nor_audit_row(monkeypatch):
    """The consuming surfaces inherit the combined-chain decision."""
    monkeypatch.setattr(boundary, "get_settings", lambda: settings(trusted_proxy_ips=PROXY_NETWORK))
    proxied = request(
        peer=PROXY_PEER,
        headers=[("x-forwarded-for", CLIENT_SUPPLIED), ("x-forwarded-for", REAL_CLIENT)],
    )
    assert rate_limit_client_key(proxied) == REAL_CLIENT
    assert client_ip_from_request(proxied) == REAL_CLIENT
