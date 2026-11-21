"""Fixtures for tests whose connectors pass the outbound URL policy (``services/outbound_url_policy.py``).

The policy resolves every target's hostname before a request; tests never touch real DNS:

- ``public_source_dns``: every hostname resolves to a documentation address the policy treats as
  public (``203.0.113.10``, TEST-NET-3), for fixtures such as ``https://wiki.example.test``;
- ``loopback_stub_exemption_fixture``: the stubbed connection types (Source Sync and the connector tools
  alike) run with the loopback stub exemption for the two pod-loopback stubs
  (``127.0.0.1:8095`` / ``:8096``) on a development profile with loopback origins only. The real gate
  (``app/loopback_stub_policy.py``) decides; nothing here bypasses it.

A test module opts in with ``pytestmark = pytest.mark.usefixtures(...)`` after importing the fixture.
"""

from __future__ import annotations

import ipaddress

import pytest

from app.config import Settings

PUBLIC_TEST_ADDRESS = ipaddress.ip_address("203.0.113.10")
STUB_LOOPBACK_HOSTS = "127.0.0.1:8095,127.0.0.1:8096"
LOOPBACK_ORIGINS = "http://localhost:8090,http://127.0.0.1:8090"


@pytest.fixture
def public_source_dns(monkeypatch):
    async def _resolve(hostname: str, port: int | None):
        return {PUBLIC_TEST_ADDRESS}

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve)


def stub_settings(*, hosts: str = STUB_LOOPBACK_HOSTS, profile: str = "staging", origins: str = LOOPBACK_ORIGINS):
    return Settings.model_construct(
        source_sync_allow_loopback_hosts=hosts, runtime_profile=profile, cors_allowed_origins=origins
    )


@pytest.fixture
def loopback_stub_exemption_fixture(monkeypatch):
    use_stub_settings(monkeypatch, stub_settings())


def use_stub_settings(monkeypatch, settings) -> None:
    """The settings the loopback stub policy reads on every request."""
    monkeypatch.setattr("app.loopback_stub_policy._settings", lambda: settings)


def answer_public_web(monkeypatch, handler):
    """The uncredentialed web fetches keep their pinned check; ``handler(request)`` answers after it.

    ``public_web_client`` builds its transport through ``public_web_transport``; the replacement is
    the real pinned ``public_web`` transport with a recorded-response ``inner``, so every request
    and redirect hop is still checked by the egress rule before the handler sees it.
    """
    import httpx

    from app.services.outbound_egress import CONNECTION_PUBLIC_WEB, PinnedEgressTransport

    monkeypatch.setattr(
        "app.services.outbound_egress.public_web.public_web_transport",
        lambda **_: PinnedEgressTransport(CONNECTION_PUBLIC_WEB, inner=httpx.MockTransport(handler)),
    )
