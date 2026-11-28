"""GitHub knowledge sources: every hostname resolves public (``203.0.113.10``) and no private host is allowlisted."""

from __future__ import annotations

import ipaddress

import pytest


@pytest.fixture
def dns(monkeypatch):
    async def _resolve(hostname: str, port: int | None):
        return {ipaddress.ip_address("203.0.113.10")}

    async def _no_allowlist(connection: str) -> frozenset[str]:
        return frozenset()

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve)
    monkeypatch.setattr("app.services.outbound_egress.target_check._private_host_keys", _no_allowlist)
