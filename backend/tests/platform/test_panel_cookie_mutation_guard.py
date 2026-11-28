"""Active principal and same-origin policy for panel mutations, proven on the pure policy, the ASGI boundary
under the trusted-proxy boundary, and the running application."""

from __future__ import annotations

from starlette.requests import Request

from app.panel_csrf_policy import (
    REASON_BEARER_CLIENT,
    REASON_CONFIGURED_ORIGIN,
    REASON_EFFECTIVE_ORIGIN,
    REASON_FOREIGN_ORIGIN,
    REASON_MISSING_ORIGIN,
    REASON_NO_AUTH_COOKIE,
    REASON_SAFE_METHOD,
    REASON_UNGUARDED_PATH,
    evaluate_panel_mutation,
)
from tests.support.panel_cookie_mutation_support import (
    ALLOWLIST_ORIGIN,
    APP_HOST,
    APP_ORIGIN,
    FOREIGN_ORIGIN,
    PANEL_PATH,
    POLICY_SETTINGS,
)
from tests.support.trusted_proxy_test_utils import REMOTE_PEER


def panel_request(
    *,
    method: str = "POST",
    path: str = PANEL_PATH,
    scheme: str = "http",
    cookie: bool = True,
    headers: list[tuple[str, str]] | None = None,
) -> Request:
    raw = [(b"host", APP_HOST.encode())]
    if cookie:
        raw.append((b"cookie", b"access_token=panel-session-token"))
    raw += [(name.lower().encode(), value.encode()) for name, value in (headers or [])]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": scheme,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": raw,
            "client": (REMOTE_PEER, 44321),
            "server": (APP_HOST, 80),
        }
    )


def decide(**kwargs) -> tuple[bool, str]:
    decision = evaluate_panel_mutation(panel_request(**kwargs), POLICY_SETTINGS)
    return decision.allowed, decision.reason


def test_a_safe_method_is_never_a_guarded_mutation():
    assert decide(method="GET", headers=[("origin", FOREIGN_ORIGIN)]) == (True, REASON_SAFE_METHOD)


def test_a_non_panel_path_is_outside_the_guarded_surface():
    assert decide(path="/admin/chat/api/sessions", headers=[("origin", FOREIGN_ORIGIN)]) == (
        True,
        REASON_UNGUARDED_PATH,
    )


def test_the_root_mounted_panel_path_is_guarded_like_the_admin_one():
    # chat_approvals is mounted under /admin *and* at the root; both are panel.
    assert decide(path="/chat/api/panel/exec-policies", headers=[("origin", FOREIGN_ORIGIN)]) == (
        False,
        REASON_FOREIGN_ORIGIN,
    )


def test_a_same_origin_cookie_mutation_is_allowed():
    assert decide(headers=[("origin", APP_ORIGIN)]) == (True, REASON_EFFECTIVE_ORIGIN)


def test_a_foreign_origin_cookie_mutation_is_refused():
    assert decide(headers=[("origin", FOREIGN_ORIGIN)]) == (False, REASON_FOREIGN_ORIGIN)


def test_a_cookie_mutation_claiming_no_origin_at_all_is_refused():
    assert decide(headers=[]) == (False, REASON_MISSING_ORIGIN)


def test_the_referer_is_the_fallback_only_when_no_origin_header_was_sent():
    assert decide(headers=[("referer", f"{APP_ORIGIN}/admin/panel")]) == (True, REASON_EFFECTIVE_ORIGIN)
    assert decide(headers=[("referer", f"{FOREIGN_ORIGIN}/x")]) == (False, REASON_FOREIGN_ORIGIN)


def test_an_unusable_origin_header_is_a_claim_the_referer_cannot_rescue():
    assert decide(headers=[("origin", "null"), ("referer", f"{APP_ORIGIN}/admin/panel")]) == (
        False,
        REASON_MISSING_ORIGIN,
    )


def test_a_configured_allowed_origin_may_mutate():
    assert decide(headers=[("origin", ALLOWLIST_ORIGIN)]) == (True, REASON_CONFIGURED_ORIGIN)


def test_origin_comparison_ignores_case_and_keeps_the_port():
    assert decide(headers=[("origin", f"HTTP://{APP_HOST.upper()}")]) == (True, REASON_EFFECTIVE_ORIGIN)
    assert decide(headers=[("origin", f"{APP_ORIGIN}:8443")]) == (False, REASON_FOREIGN_ORIGIN)


def test_a_bearer_client_without_a_cookie_is_not_riding_an_ambient_credential():
    # The web resolver falls back to a bearer token only when no auth cookie was
    # sent; that is the one shape the exemption covers.
    assert decide(cookie=False, headers=[("authorization", "Bearer token-value")]) == (
        True,
        REASON_BEARER_CLIENT,
    )


def test_a_bearer_header_buys_no_exemption_while_an_auth_cookie_is_present():
    fake = ("authorization", "Bearer attacker-supplied-value")
    assert decide(headers=[fake]) == (False, REASON_MISSING_ORIGIN)
    assert decide(headers=[fake, ("origin", FOREIGN_ORIGIN)]) == (False, REASON_FOREIGN_ORIGIN)
    # The legitimate browser case is unaffected.
    assert decide(headers=[fake, ("origin", APP_ORIGIN)]) == (True, REASON_EFFECTIVE_ORIGIN)


def test_an_api_key_header_buys_no_exemption_while_an_auth_cookie_is_present():
    fake = ("x-api-key", "attacker-supplied-value")
    assert decide(headers=[fake]) == (False, REASON_MISSING_ORIGIN)
    assert decide(headers=[fake, ("origin", FOREIGN_ORIGIN)]) == (False, REASON_FOREIGN_ORIGIN)
    assert decide(headers=[fake, ("origin", APP_ORIGIN)]) == (True, REASON_EFFECTIVE_ORIGIN)


def test_an_api_key_only_request_carries_no_credential_this_surface_accepts():
    # No cookie, no bearer: the route answers 401 on its own. The policy does
    # not pretend to exempt it.
    assert decide(cookie=False, headers=[("x-api-key", "oek_value")]) == (True, REASON_NO_AUTH_COOKIE)


def test_a_request_without_an_auth_cookie_is_left_to_the_route_to_refuse():
    assert decide(cookie=False, headers=[]) == (True, REASON_NO_AUTH_COOKIE)


def test_a_spoofed_forwarded_host_cannot_move_the_expected_origin():
    spoofed = [
        ("x-forwarded-host", "attacker.example"),
        ("x-forwarded-proto", "https"),
        ("forwarded", "host=attacker.example;proto=https"),
        ("origin", FOREIGN_ORIGIN),
    ]
    assert decide(headers=spoofed) == (False, REASON_FOREIGN_ORIGIN)
    # ...and the real origin still matches while those headers are present.
    assert decide(headers=[*spoofed[:-1], ("origin", APP_ORIGIN)]) == (True, REASON_EFFECTIVE_ORIGIN)
