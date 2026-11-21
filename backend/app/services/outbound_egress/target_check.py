"""The connection-aware egress check: the outbound URL policy plus the connection's allowlist.

``check_connection_target`` runs the policy in the connection's scope. When the only refusal
is a private address on an allowlistable connection, it reads that connection type's
admin-governed private-host allowlist (``private_hosts.py``) and checks again with it; the
allowlist is read only then, so public targets never touch the database. The result carries
every checked address, which the pinned transport connects to (``pinned_transport.py``).
"""

from __future__ import annotations

from ..outbound_url_policy import (
    REASON_PRIVATE_ADDRESS_NOT_ALLOWLISTED,
    CheckedTarget,
    OutboundURLPolicyError,
    check_outbound_target,
)
from .connections import EgressConnectionRule
from .private_hosts import REASON_ALLOWLIST_UNAVAILABLE, PrivateHostAllowlistError, private_host_policy_keys


async def _private_host_keys(connection: str) -> frozenset[str]:
    """The connection's allowlist from admin configuration, read in its own short session."""
    from ...db import core as db_core

    try:
        async with db_core.async_session_factory() as db:
            return await private_host_policy_keys(db, connection)
    except PrivateHostAllowlistError as refused:
        raise OutboundURLPolicyError("Private host allowlist unavailable", reason=refused.reason) from None
    except Exception:
        raise OutboundURLPolicyError(
            "Private host allowlist unavailable", reason=REASON_ALLOWLIST_UNAVAILABLE
        ) from None


async def check_connection_target(
    url: str,
    rule: EgressConnectionRule,
    *,
    allow_hosts: frozenset[str] = frozenset(),
) -> CheckedTarget:
    """The admitted target of ``url`` for ``rule``, else :class:`OutboundURLPolicyError`."""
    try:
        return await check_outbound_target(url, scope=rule.scope, allow_hosts=allow_hosts)
    except OutboundURLPolicyError as refused:
        if refused.reason != REASON_PRIVATE_ADDRESS_NOT_ALLOWLISTED or not rule.private_allowlist:
            raise
    private_hosts = await _private_host_keys(rule.connection)
    return await check_outbound_target(url, scope=rule.scope, allow_hosts=allow_hosts, private_hosts=private_hosts)


__all__ = ["check_connection_target"]
