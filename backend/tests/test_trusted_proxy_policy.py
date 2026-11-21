"""Trusted-proxy boundary: configuration contract and identity decision matrix.

Covers ``app.trusted_proxy_policy`` and the ``app.config`` allowlist validation in
isolation. The ASGI boundary lives in ``test_trusted_proxy_middleware.py``; repeated
headers, rate-limit bucketing, and audit attribution in
``test_trusted_proxy_attribution.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import app.trusted_proxy_policy as boundary
from app.config import forwarded_header_trust_mode, parse_trusted_proxy_ips
from app.trusted_proxy_policy import log_boundary_configuration, uvicorn_forwarded_header_options
from tests.trusted_proxy_test_utils import PRODUCTION_LIKE, PROXY_NETWORK, settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


# Every launch path that starts uvicorn from a file rather than from
# ``uvicorn_forwarded_header_options()``.
LAUNCH_PATH_TOKENS = {
    "dev-start.sh": "--no-proxy-headers",
    "frontend/chat/scripts/run-admin-e2e-server.sh": "proxy_headers=False",
}


# --- Configuration contract -------------------------------------------------


@pytest.mark.parametrize("raw", ["*", "0.0.0.0/0", "::/0", "not-an-ip", "10.0.0.0/8, nope"])
def test_trust_all_and_malformed_allowlists_fail_closed(raw):
    with pytest.raises(ValueError):
        parse_trusted_proxy_ips(raw)
    with pytest.raises(ValidationError) as exc_info:
        settings(trusted_proxy_ips=raw)
    assert "trusted_proxy_ips" in str(exc_info.value)


@pytest.mark.parametrize(
    "raw",
    [
        "0.0.0.0/1, 128.0.0.0/1",
        "128.0.0.0/1, 0.0.0.0/1",
        "0.0.0.0/2, 64.0.0.0/2, 128.0.0.0/1",
        "::/1, 8000::/1",
        "10.0.0.0/8, ::/1, 8000::/1",
    ],
)
def test_composite_trust_all_allowlists_fail_closed(raw):
    """A set of entries must not add up to a whole address family."""
    with pytest.raises(ValueError, match="entire IPv"):
        parse_trusted_proxy_ips(raw)
    with pytest.raises(ValidationError) as exc_info:
        settings(trusted_proxy_ips=raw)
    assert "trusted_proxy_ips" in str(exc_info.value)
    assert "entire IPv" in str(exc_info.value)


@pytest.mark.parametrize(
    "raw",
    [
        "10.0.0.0/8",
        "10.1.2.3, 10.1.2.4",
        # Adjacent networks that merge but stay far from full coverage.
        "10.0.0.0/9, 10.128.0.0/9",
        "192.168.0.0/16, 172.16.0.0/12, 10.0.0.0/8",
        "::1, 2001:db8::/32",
        # Half of each family is wide, but not trust-all. Accepted deliberately;
        # see the residual risk in the architecture doc.
        "0.0.0.0/1",
        "::/1",
    ],
)
def test_ordinary_narrow_allowlists_are_accepted(raw):
    assert parse_trusted_proxy_ips(raw)
    assert settings(trusted_proxy_ips=raw).trusted_proxy_ips


def test_allowlist_is_normalized_to_networks():
    assert parse_trusted_proxy_ips(" 10.1.2.3 , 10.0.0.0/8 , ::1 ") == ["10.1.2.3/32", "10.0.0.0/8", "::1/128"]


def test_forwarded_header_trust_mode_is_reported_on_health():
    assert forwarded_header_trust_mode("") == "disabled"
    assert forwarded_header_trust_mode(PROXY_NETWORK) == "explicit_allowlist"
    assert settings().security_defaults_report()["forwarded_header_trust"] == "disabled"
    report = settings(trusted_proxy_ips=PROXY_NETWORK).security_defaults_report()
    assert report["forwarded_header_trust"] == "explicit_allowlist"
    assert report["trusted_proxy_ips_configured"] is True


# --- Entrypoint -------------------------------------------------------------


def test_entrypoint_never_trusts_forwarded_headers_at_the_transport_layer():
    assert uvicorn_forwarded_header_options() == {"proxy_headers": False, "forwarded_allow_ips": []}


@pytest.mark.parametrize(("relative_path", "token"), sorted(LAUNCH_PATH_TOKENS.items()))
def test_every_file_launched_uvicorn_disables_transport_level_proxy_headers(relative_path, token):
    launcher = REPOSITORY_ROOT / relative_path
    assert launcher.is_file(), f"launch path moved: {relative_path}"
    contents = launcher.read_text(encoding="utf-8")
    assert "uvicorn" in contents, f"no longer a uvicorn launch path: {relative_path}"
    assert token in contents, f"{relative_path} must disable transport-level forwarded headers"


# --- Startup reporting ------------------------------------------------------


def test_startup_warns_when_a_production_like_runtime_names_no_proxy(caplog):
    """The empty allowlist is valid but is the known ingress misconfiguration."""
    with caplog.at_level("WARNING", logger=boundary.logger.name):
        mode = log_boundary_configuration(settings(**PRODUCTION_LIKE, trusted_proxy_ips=""))
    assert mode == "disabled"
    assert "TRUSTED_PROXY_IPS is empty" in caplog.text


def test_startup_does_not_warn_for_a_configured_or_local_boundary(caplog):
    with caplog.at_level("WARNING", logger=boundary.logger.name):
        assert log_boundary_configuration(settings(**PRODUCTION_LIKE, trusted_proxy_ips=PROXY_NETWORK)) == (
            "explicit_allowlist"
        )
        assert log_boundary_configuration(settings(trusted_proxy_ips="")) == "disabled"
    assert caplog.text == ""


def test_startup_warns_that_a_transport_level_allowlist_variable_is_inert(caplog, monkeypatch):
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    with caplog.at_level("WARNING", logger=boundary.logger.name):
        log_boundary_configuration(settings(trusted_proxy_ips=PROXY_NETWORK))
    assert "FORWARDED_ALLOW_IPS" in caplog.text
