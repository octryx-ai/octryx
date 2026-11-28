"""Fixtures for tests whose connectors pass the outbound URL policy (``services/outbound_url_policy.py``)."""

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
    monkeypatch.setattr("app.loopback_stub_policy._settings", lambda: settings)


def answer_public_web(monkeypatch, handler):
    import httpx

    from app.services.outbound_egress import CONNECTION_PUBLIC_WEB, PinnedEgressTransport

    monkeypatch.setattr(
        "app.services.outbound_egress.public_web.public_web_transport",
        lambda **_: PinnedEgressTransport(CONNECTION_PUBLIC_WEB, inner=httpx.MockTransport(handler)),
    )
