"""Auth-cookie Secure policy: decision matrix and real response headers."""

import pytest
from fastapi import Request, Response
from pydantic import ValidationError

import app.auth_cookie_policy as policy_module
from app.auth_cookie_policy import (
    INSECURE_REASON_LOCAL_DEBUG,
    SECURE_REASON_FAIL_SECURE,
    SECURE_REASON_FORCED,
    SECURE_REASON_HTTPS,
    SECURE_REASON_TRUSTED_PROXY_HTTPS,
    resolve_auth_cookie_policy,
)
from app.config import parse_trusted_proxy_ips
from app.http_security import clear_auth_cookies, set_auth_cookies
from tests.platform.auth_cookie_policy_support import (
    _cookie_attributes,
    _cookie_headers,
    _forced_secure_settings,
    _is_secure,
    _local_debug_settings,
    _settings,
)

LOOPBACK_PEER = ("127.0.0.1", 41234)


REMOTE_PEER = ("203.0.113.5", 41234)


PROXY_PEER = ("10.1.2.3", 41234)


def _request(
    *,
    scheme: str = "http",
    client: tuple[str, int] | None = LOOPBACK_PEER,
    headers: dict[str, str] | None = None,
    host: str = "localhost:8000",
) -> Request:
    raw_headers = [(b"host", host.encode())]
    raw_headers += [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": scheme,
            "path": "/chat/login",
            "raw_path": b"/chat/login",
            "query_string": b"",
            "root_path": "",
            "headers": raw_headers,
            "client": client,
            "server": ("localhost", 8000),
        }
    )


def test_forced_secure_wins_over_plain_http_loopback_request():
    settings = _forced_secure_settings(debug=True)
    decision = resolve_auth_cookie_policy(_request(), settings)

    assert decision.secure is True
    assert decision.secure_reason == SECURE_REASON_FORCED
    assert decision.local_debug_exemption is False


def test_https_request_is_secure_under_local_debug_configuration():
    decision = resolve_auth_cookie_policy(_request(scheme="https"), _local_debug_settings())

    assert decision.secure is True
    assert decision.secure_reason == SECURE_REASON_HTTPS


def test_local_debug_loopback_http_is_the_only_non_secure_case():
    decision = resolve_auth_cookie_policy(_request(), _local_debug_settings())

    assert decision.secure is False
    assert decision.secure_reason == INSECURE_REASON_LOCAL_DEBUG
    assert decision.local_debug_exemption is True


@pytest.mark.parametrize("peer_host", ["::1", "::ffff:127.0.0.1", "127.0.0.7"])
def test_loopback_exemption_covers_ipv6_and_mapped_loopback_peers(peer_host):
    decision = resolve_auth_cookie_policy(_request(client=(peer_host, 5000)), _local_debug_settings())

    assert decision.secure is False
    assert decision.secure_reason == INSECURE_REASON_LOCAL_DEBUG


def test_non_loopback_peer_fails_secure_in_local_debug_mode():
    decision = resolve_auth_cookie_policy(_request(client=REMOTE_PEER), _local_debug_settings())

    assert decision.secure is True
    assert decision.secure_reason == SECURE_REASON_FAIL_SECURE


def test_missing_request_fails_secure():
    decision = resolve_auth_cookie_policy(None, _local_debug_settings())

    assert decision.secure is True
    assert decision.secure_reason == SECURE_REASON_FAIL_SECURE


def test_unknown_peer_address_fails_secure():
    decision = resolve_auth_cookie_policy(_request(client=None), _local_debug_settings())

    assert decision.secure is True
    assert decision.secure_reason == SECURE_REASON_FAIL_SECURE


def test_forwarded_header_from_untrusted_peer_cannot_fake_local_debug():
    decision = resolve_auth_cookie_policy(
        _request(headers={"x-forwarded-for": "127.0.0.1"}),
        _local_debug_settings(),
    )

    assert decision.secure is True
    assert decision.secure_reason == SECURE_REASON_FAIL_SECURE


def test_forwarded_proto_from_untrusted_peer_is_not_trusted_but_fails_secure():
    decision = resolve_auth_cookie_policy(
        _request(client=REMOTE_PEER, headers={"x-forwarded-proto": "https"}),
        _local_debug_settings(),
    )

    assert decision.secure is True
    assert decision.secure_reason == SECURE_REASON_FAIL_SECURE


@pytest.mark.parametrize(
    "headers",
    [
        {"x-forwarded-proto": "https"},
        {"x-forwarded-proto": "https, http"},
        {"forwarded": "for=198.51.100.9;proto=https"},
    ],
)
def test_trusted_proxy_forwarded_https_is_secure(headers):
    decision = resolve_auth_cookie_policy(
        _request(client=PROXY_PEER, headers=headers),
        _local_debug_settings(trusted_proxy_ips="10.0.0.0/8"),
    )

    assert decision.secure is True
    assert decision.secure_reason == SECURE_REASON_TRUSTED_PROXY_HTTPS


def test_trusted_proxy_forwarded_http_never_gets_the_local_debug_exemption():
    decision = resolve_auth_cookie_policy(
        _request(headers={"x-forwarded-proto": "http"}),
        _local_debug_settings(trusted_proxy_ips="127.0.0.1"),
    )

    assert decision.secure is True
    assert decision.secure_reason == SECURE_REASON_FAIL_SECURE


def test_samesite_and_paths_come_from_configuration():
    decision = resolve_auth_cookie_policy(_request(), _local_debug_settings(auth_cookie_samesite="strict"))

    assert decision.samesite == "strict"
    assert decision.access_token_path == "/"
    assert decision.refresh_token_path == "/api/v1/auth"


def test_production_like_configuration_cannot_disable_secure_cookies():
    with pytest.raises(ValidationError) as exc_info:
        _settings(debug=False, force_secure_auth_cookies=False)
    assert "force_secure_auth_cookies" in str(exc_info.value)

    with pytest.raises(ValidationError):
        _settings(
            debug=True,
            force_secure_auth_cookies=False,
            runtime_profile="prod",
            database_url="postgresql+asyncpg://user:pass@db:5432/octryx",
        )


def test_trusted_proxy_ips_are_normalized_and_validated():
    settings = _settings(trusted_proxy_ips=" 10.0.0.0/8 , ::1 , 10.0.0.0/8 ")
    assert parse_trusted_proxy_ips(settings.trusted_proxy_ips) == ["10.0.0.0/8", "::1/128"]

    with pytest.raises(ValidationError) as exc_info:
        _settings(trusted_proxy_ips="not-an-ip")
    assert "trusted_proxy_ips" in str(exc_info.value)


def test_security_defaults_report_exposes_cookie_policy_inputs():
    forced = _forced_secure_settings(trusted_proxy_ips="10.0.0.0/8").security_defaults_report()
    assert forced["force_secure_auth_cookies"] is True
    assert forced["trusted_proxy_ips_configured"] is True

    local_debug = _local_debug_settings().security_defaults_report()
    assert local_debug["force_secure_auth_cookies"] is False
    assert local_debug["trusted_proxy_ips_configured"] is False
    assert local_debug["status"] == "local_only_defaults"
    assert local_debug["production_like"] is False


@pytest.mark.parametrize(
    ("settings_factory", "expected_secure"),
    [(_forced_secure_settings, True), (_local_debug_settings, False)],
)
def test_set_and_clear_use_one_consistent_policy(monkeypatch, settings_factory, expected_secure):
    monkeypatch.setattr(policy_module, "get_settings", settings_factory)
    request = _request()

    set_response = Response()
    set_auth_cookies(set_response, access_token="a", refresh_token="r", request=request)
    clear_response = Response()
    clear_auth_cookies(clear_response, request=request)

    set_cookies = _cookie_headers(set_response)
    clear_cookies = _cookie_headers(clear_response)
    assert set(set_cookies) == set(clear_cookies) == {"access_token", "refresh_token"}
    for raw in list(set_cookies.values()) + list(clear_cookies.values()):
        assert _is_secure(raw) is expected_secure
    for cookies in (set_cookies, clear_cookies):
        assert _cookie_attributes(cookies["access_token"])["path"] == "/"
        assert _cookie_attributes(cookies["refresh_token"])["path"] == "/api/v1/auth"
