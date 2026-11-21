"""The admin-governed private-host allowlist for on-prem connections.

A credentialed SaaS connection (``connections.py``) runs in the ``public_only`` scope, so an
on-prem Jira, Confluence, Bitbucket, GitHub Enterprise, GitLab or ServiceNow on a private
address is refused with ``private_address_not_allowlisted``. An admin opens exactly such a
target by listing its ``host:port`` for that connection type:

* entries are exact ``host:port`` pairs (``jira.corp.example:443``, ``10.20.0.5:8443``,
  ``[fd12::5]:443``); the port is required, nothing is a wildcard or a range;
* an entry never names the pod or a metadata service: loopback, link-local, unspecified and
  the AWS IPv6 metadata literals, ``localhost`` and the named metadata hosts are refused
  (``entry_pod_local_refused``), and at request time a listed hostname that resolves to any
  pod-local address is still refused (``blocked_address``);
* a public IP literal needs no entry and is refused (``entry_not_private``);
* the allowlist lives in admin configuration (``system_config`` key
  :data:`PRIVATE_HOST_ALLOWLIST_KEY`), applies in every runtime profile including
  production, and every change is audited (``egress.private_hosts.updated``, before and
  after entries, the acting admin).

A stored allowlist that no longer validates (edited by hand) is not partially applied: the
connection answers ``private_host_allowlist_unavailable`` until an admin saves a valid one.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..admin.governance.admin_config_audit_service import record_admin_config_audit
from ..outbound_url_policy import ADDRESS_CLASS_POD_LOCAL, ADDRESS_CLASS_PUBLIC, classify_address, is_blocked_hostname
from .connections import ALLOWLISTABLE_CONNECTIONS

PRIVATE_HOST_ALLOWLIST_KEY = "egress.private_host_allowlist"
AUDIT_ACTION_UPDATED = "egress.private_hosts.updated"
AUDIT_RESOURCE_TYPE = "egress_private_host_allowlist"
MAX_ENTRIES_PER_CONNECTION = 50

REASON_CONNECTION_NOT_ALLOWLISTABLE = "connection_not_allowlistable"
REASON_ENTRY_MALFORMED = "entry_malformed"
REASON_ENTRY_PORT_REQUIRED = "entry_port_required"
REASON_ENTRY_POD_LOCAL_REFUSED = "entry_pod_local_refused"
REASON_ENTRY_NOT_PRIVATE = "entry_not_private"
REASON_TOO_MANY_ENTRIES = "too_many_entries"
REASON_ALLOWLIST_UNAVAILABLE = "private_host_allowlist_unavailable"

_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_BRACKETED = re.compile(r"^\[([0-9a-f:.]+)\]:(\d{1,5})$")
_PLAIN = re.compile(r"^([^:\[\]]+):(\d{1,5})$")


class PrivateHostAllowlistError(ValueError):
    """An allowlist change or a stored allowlist was refused; ``reason`` is a fixed code."""

    def __init__(self, reason: str, *, entry_index: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.entry_index = entry_index

    def detail(self) -> dict[str, object]:
        payload: dict[str, object] = {"state": "private_host_entry_refused", "reason": self.reason}
        if self.entry_index is not None:
            payload["entry_index"] = self.entry_index
        return payload


@dataclass(frozen=True, order=True)
class PrivateHostEntry:
    host: str
    port: int

    @property
    def display(self) -> str:
        return f"[{self.host}]:{self.port}" if ":" in self.host else f"{self.host}:{self.port}"

    @property
    def policy_key(self) -> str:
        """The ``hostname:port`` form the outbound URL policy compares against."""
        return f"{self.host}:{self.port}"


def _checked_hostname(host: str) -> str:
    if len(host) > 253 or not all(_LABEL.match(label) for label in host.split(".")):
        raise PrivateHostAllowlistError(REASON_ENTRY_MALFORMED)
    if is_blocked_hostname(host):
        raise PrivateHostAllowlistError(REASON_ENTRY_POD_LOCAL_REFUSED)
    return host


def _checked_literal(ip: ipaddress._BaseAddress) -> str:
    address_class = classify_address(ip)
    if address_class == ADDRESS_CLASS_POD_LOCAL:
        raise PrivateHostAllowlistError(REASON_ENTRY_POD_LOCAL_REFUSED)
    if address_class == ADDRESS_CLASS_PUBLIC:
        raise PrivateHostAllowlistError(REASON_ENTRY_NOT_PRIVATE)
    return str(ip)


def parse_private_host_entry(raw: object) -> PrivateHostEntry:
    """One validated entry, or :class:`PrivateHostAllowlistError` with a fixed reason."""
    text = str(raw or "").strip().lower()
    match = _BRACKETED.match(text)
    if match is not None:
        host_text, port_text = match.groups()
        try:
            host = _checked_literal(ipaddress.IPv6Address(host_text))
        except ipaddress.AddressValueError:
            raise PrivateHostAllowlistError(REASON_ENTRY_MALFORMED) from None
    else:
        match = _PLAIN.match(text)
        if match is None:
            reason = REASON_ENTRY_PORT_REQUIRED if text and ":" not in text else REASON_ENTRY_MALFORMED
            raise PrivateHostAllowlistError(reason)
        host_text, port_text = match.groups()
        host_text = host_text.rstrip(".")
        try:
            literal = ipaddress.ip_address(host_text)
        except ValueError:
            host = _checked_hostname(host_text)
        else:
            host = _checked_literal(literal)
    port = int(port_text)
    if not 1 <= port <= 65535:
        raise PrivateHostAllowlistError(REASON_ENTRY_MALFORMED)
    return PrivateHostEntry(host, port)


def _checked_connection(connection: str) -> str:
    if connection not in ALLOWLISTABLE_CONNECTIONS:
        raise PrivateHostAllowlistError(REASON_CONNECTION_NOT_ALLOWLISTABLE)
    return connection


def normalize_private_host_entries(raw_entries: object) -> list[PrivateHostEntry]:
    if not isinstance(raw_entries, list):
        raise PrivateHostAllowlistError(REASON_ENTRY_MALFORMED)
    entries: set[PrivateHostEntry] = set()
    for index, raw in enumerate(raw_entries):
        try:
            entries.add(parse_private_host_entry(raw))
        except PrivateHostAllowlistError as refused:
            raise PrivateHostAllowlistError(refused.reason, entry_index=index) from None
    if len(entries) > MAX_ENTRIES_PER_CONNECTION:
        raise PrivateHostAllowlistError(REASON_TOO_MANY_ENTRIES)
    return sorted(entries)


def _decode_stored(value: str | None) -> dict[str, list[PrivateHostEntry]]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except ValueError:
        raise PrivateHostAllowlistError(REASON_ALLOWLIST_UNAVAILABLE) from None
    if not isinstance(payload, dict):
        raise PrivateHostAllowlistError(REASON_ALLOWLIST_UNAVAILABLE)
    decoded: dict[str, list[PrivateHostEntry]] = {}
    for connection, raw_entries in payload.items():
        try:
            decoded[_checked_connection(str(connection))] = normalize_private_host_entries(raw_entries)
        except PrivateHostAllowlistError:
            raise PrivateHostAllowlistError(REASON_ALLOWLIST_UNAVAILABLE) from None
    return decoded


async def read_private_host_allowlist(db: AsyncSession) -> dict[str, list[str]]:
    """Every allowlistable connection type with its entries (display form), for the admin view."""
    from ..system_config import get_system_config_value

    stored = _decode_stored(await get_system_config_value(db, PRIVATE_HOST_ALLOWLIST_KEY))
    return {name: [entry.display for entry in stored.get(name, [])] for name in ALLOWLISTABLE_CONNECTIONS}


async def private_host_policy_keys(db: AsyncSession, connection: str) -> frozenset[str]:
    """The policy keys of one connection type; raises ``private_host_allowlist_unavailable`` if corrupt."""
    from ..system_config import get_system_config_value

    stored = _decode_stored(await get_system_config_value(db, PRIVATE_HOST_ALLOWLIST_KEY))
    return frozenset(entry.policy_key for entry in stored.get(_checked_connection(connection), []))


async def replace_private_host_entries(
    db: AsyncSession,
    *,
    connection: str,
    entries: object,
    actor_user_id: str,
) -> list[str]:
    """Validate and store the entries of one connection type, audited; the caller commits."""
    from ..system_config import get_system_config_value, set_system_config_value

    connection = _checked_connection(connection)
    normalized = normalize_private_host_entries(entries)
    try:
        stored = _decode_stored(await get_system_config_value(db, PRIVATE_HOST_ALLOWLIST_KEY))
    except PrivateHostAllowlistError:
        stored = {}  # A corrupt stored value is replaced by the admin's validated one, and audited.
    before = [entry.display for entry in stored.get(connection, [])]
    after = [entry.display for entry in normalized]
    stored[connection] = normalized
    payload = {name: [entry.display for entry in items] for name, items in sorted(stored.items()) if items}
    await set_system_config_value(
        db,
        key=PRIVATE_HOST_ALLOWLIST_KEY,
        value=json.dumps(payload, sort_keys=True) if payload else None,
        description="Admin-governed private host:port allowlist per on-prem connection type.",
        updated_by=actor_user_id,
        change_source="egress_private_hosts",
        record_prompt_revision=False,
    )
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action=AUDIT_ACTION_UPDATED,
        resource_type=AUDIT_RESOURCE_TYPE,
        resource_id=connection,
        before={"entries": before},
        after={"entries": after},
    )
    return after


__all__ = [
    "AUDIT_ACTION_UPDATED",
    "MAX_ENTRIES_PER_CONNECTION",
    "PRIVATE_HOST_ALLOWLIST_KEY",
    "PrivateHostAllowlistError",
    "PrivateHostEntry",
    "REASON_ALLOWLIST_UNAVAILABLE",
    "parse_private_host_entry",
    "private_host_policy_keys",
    "read_private_host_allowlist",
    "replace_private_host_entries",
]
