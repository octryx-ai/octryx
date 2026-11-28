"""Contract: an admin-governed private-host allowlist opens on-prem connections, and nothing else."""

from __future__ import annotations

import inspect
import ipaddress
import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, Role, User, UserRole
from app.services.auth.tokens import create_access_token, hash_password
from app.services.outbound_egress import (
    CONNECTION_CONFLUENCE,
    CONNECTION_JIRA,
    connection_rule,
    private_hosts,
    target_check,
)
from app.services.outbound_egress.private_hosts import (
    AUDIT_ACTION_UPDATED,
    PrivateHostAllowlistError,
    parse_private_host_entry,
)
from app.services.outbound_egress.target_check import check_connection_target
from app.services.outbound_url_policy import OutboundURLPolicyError
from tests.conftest import ADMIN_PASSWORD

ROUTE = "/admin/chat/api/panel/egress/private-hosts"


@pytest.mark.parametrize(
    ("raw", "display"),
    [
        ("Jira.Corp.Example:8443", "jira.corp.example:8443"),
        ("10.20.0.5:443", "10.20.0.5:443"),
        ("[FD12::5]:443", "[fd12::5]:443"),
        ("gitlab:80", "gitlab:80"),
    ],
)
def test_an_entry_is_an_exact_host_and_port(raw, display):
    assert parse_private_host_entry(raw).display == display


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("127.0.0.1:443", "entry_pod_local_refused"),
        ("[::1]:443", "entry_pod_local_refused"),
        ("169.254.169.254:80", "entry_pod_local_refused"),
        ("[fd00:ec2::254]:80", "entry_pod_local_refused"),
        ("[::ffff:127.0.0.1]:80", "entry_pod_local_refused"),
        ("0.0.0.0:80", "entry_pod_local_refused"),
        ("localhost:8080", "entry_pod_local_refused"),
        ("api.localhost:8080", "entry_pod_local_refused"),
        ("metadata.google.internal:80", "entry_pod_local_refused"),
        ("jira.corp.example", "entry_port_required"),
        ("8.8.8.8:443", "entry_not_private"),
        ("*.corp.example:443", "entry_malformed"),
        ("10.0.0.0/8:443", "entry_malformed"),
        ("jira.corp.example:0", "entry_malformed"),
        ("https://jira.corp.example:443", "entry_malformed"),
    ],
)
def test_an_entry_never_names_the_pod_or_metadata_and_is_never_vague(raw, reason):
    with pytest.raises(PrivateHostAllowlistError) as refused:
        parse_private_host_entry(raw)
    assert refused.value.reason == reason


async def _viewer(db) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=str(uuid.uuid4()),
        username=f"viewer-{suffix}",
        email=f"viewer-{suffix}@example.com",
        password_hash=hash_password("viewer-Test-Pw-123"),
        display_name="viewer",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    viewer_role = (await db.execute(select(Role).where(Role.name == "viewer"))).scalar_one()
    db.add(UserRole(user_id=user.id, role_id=viewer_role.id))
    await db.commit()
    return user


@pytest.fixture
def onprem_dns(monkeypatch):
    async def _resolve(hostname: str, port: int | None):
        if hostname == "pod.corp.example":
            return {ipaddress.ip_address("127.0.0.1")}
        if hostname.endswith(".corp.example"):
            return {ipaddress.ip_address("10.20.0.5")}
        return {ipaddress.ip_address("203.0.113.10")}

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve)


async def _reason(url: str, connection: str) -> str | None:
    try:
        await check_connection_target(url, connection_rule(connection))
    except OutboundURLPolicyError as refused:
        return refused.reason
    return None


@pytest.mark.asyncio
async def test_only_an_admin_opens_an_onprem_host_and_the_change_is_audited(client, db, onprem_dns):
    jira = "https://jira.corp.example:8443/rest/api/2/myself"
    assert await _reason(jira, CONNECTION_JIRA) == "private_address_not_allowlisted"

    viewer = await _viewer(db)
    client.cookies.set("access_token", create_access_token(viewer.id))
    assert (await client.get(ROUTE)).status_code == 403
    denied = await client.put(f"{ROUTE}/jira", json={"entries": ["jira.corp.example:8443"]})
    assert denied.status_code == 403
    client.cookies.clear()

    login = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login.status_code == 303
    refused = await client.put(f"{ROUTE}/jira", json={"entries": ["jira.corp.example:8443", "127.0.0.1:443"]})
    assert refused.status_code == 400
    assert refused.json()["detail"] == {
        "state": "private_host_entry_refused",
        "reason": "entry_pod_local_refused",
        "entry_index": 1,
    }
    wrong_type = await client.put(f"{ROUTE}/private_network_integration", json={"entries": ["10.0.0.9:443"]})
    assert wrong_type.json()["detail"]["reason"] == "connection_not_allowlistable"
    assert await _reason(jira, CONNECTION_JIRA) == "private_address_not_allowlisted"  # nothing was stored

    saved = await client.put(f"{ROUTE}/jira", json={"entries": ["Jira.Corp.Example:8443", "pod.corp.example:443"]})
    assert saved.status_code == 200
    assert saved.json() == {"connection": "jira", "entries": ["jira.corp.example:8443", "pod.corp.example:443"]}
    listed = (await client.get(ROUTE)).json()
    assert listed["connections"]["jira"] == ["jira.corp.example:8443", "pod.corp.example:443"]
    assert listed["connections"]["confluence"] == []

    # Not a development exemption: neither the allowlist nor the check reads a runtime profile.
    for module in (private_hosts, target_check):
        source = inspect.getsource(module)
        assert "get_settings" not in source and "runtime_profile" not in source
    assert await _reason(jira, CONNECTION_JIRA) is None
    assert await _reason("https://jira.corp.example:443/", CONNECTION_JIRA) == "private_address_not_allowlisted"
    assert await _reason("https://jira.corp.example:8443/", CONNECTION_CONFLUENCE) == "private_address_not_allowlisted"
    assert await _reason("https://pod.corp.example/", CONNECTION_JIRA) == "blocked_address"

    await db.rollback()
    rows = (await db.execute(select(AuditLog).where(AuditLog.action == AUDIT_ACTION_UPDATED))).scalars().all()
    assert len(rows) == 1
    assert rows[0].resource_id == "jira"
    assert rows[0].details["before"] == {"entries": []}
    assert rows[0].details["after"] == {"entries": ["jira.corp.example:8443", "pod.corp.example:443"]}
