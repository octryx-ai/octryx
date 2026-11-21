"""Where any outbound client may reach a loopback target at all: local stubs on a development stack only.

The outbound URL policy refuses loopback, link-local, private and metadata addresses
(``services/outbound_url_policy.py``). A local development stack may run stubs of the source systems
(Confluence, Jira, a GitHub or Bitbucket fake, a REST API under development) on its own loopback.
``OCTRYX_SOURCE_SYNC_ALLOW_LOOPBACK_HOSTS`` names exactly those ``host:port`` pairs, and nothing else can
exempt a target.

This module is the one owner of that exemption. The pinned egress transport
(``services/outbound_egress/pinned_transport.py``) asks it on every request and redirect hop,
so Source Sync, the chat connector tools and the connection tests of the stubbed connection
types (:data:`LOOPBACK_STUB_CONNECTIONS`: Confluence, Jira, GitHub, Bitbucket and Custom REST) all see the same
exemption, and every other connection type never does. With a GitHub or Bitbucket fake on loopback, a whole
team-delivery run (branch, push, pull request) can be tested locally before any shared deployment. The variable
keeps its original name: it is one exemption with one switch; a second variable for the tool path would be a
second switch that could drift from the first.

The exemption is gated exactly like the four-eyes development exception
(``app.four_eyes_dev_policy``): startup refuses it unless the runtime profile is a named
non-production profile and every configured browser origin is loopback, and the transport
re-checks the same condition before every request. Every entry must be a literal loopback
address with an explicit port; a hostname (``localhost`` included), a non-loopback address
or a missing port is a startup refusal, never a silent drop. A listed literal address is the
only address the transport pins, so a listed pair connects to exactly itself.

Only fixed values are inspected; nothing here is logged or echoed.
"""

from __future__ import annotations

import ipaddress

from .four_eyes_dev_policy import dev_self_approval_environment_permitted
from .settings_validation_policy import SettingsFieldError

#: The connection types whose local stubs may run on the loopback. Literal names, because
#: ``config`` imports this module before any service; ``services/outbound_egress/connections.py``
#: owns the same names (a contract test pins the equality).
# ``custom_rest`` is included as well: a REST API under development on the Mac's loopback is reachable from Custom
# REST only through this same switch; on shared deployments and prod the switch cannot be set
# (startup refusal), so loopback, link-local and metadata addresses stay refused there.
LOOPBACK_STUB_CONNECTIONS = frozenset({"bitbucket", "confluence", "custom_rest", "github", "jira"})


class LoopbackAllowlistError(ValueError):
    """An allowlist entry is not a literal loopback ``host:port``; carries no entry value."""


def _parse_entry(entry: str) -> str:
    host, separator, port_text = entry.rpartition(":")
    host = host.strip().removeprefix("[").removesuffix("]")
    if not separator or not host or not port_text.isdigit():
        raise LoopbackAllowlistError("entry_not_host_port")
    port = int(port_text)
    if not 0 < port < 65536:
        raise LoopbackAllowlistError("entry_port_out_of_range")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise LoopbackAllowlistError("entry_not_literal_address") from None
    if not address.is_loopback:
        raise LoopbackAllowlistError("entry_not_loopback")
    return f"{address.compressed}:{port}"


def parse_loopback_allowlist(raw: str | None) -> frozenset[str]:
    """The normalized ``host:port`` entries, or :class:`LoopbackAllowlistError`."""
    entries = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    return frozenset(_parse_entry(entry) for entry in entries)


def loopback_allowlist_environment_permitted(runtime_profile: str | None, cors_allowed_origins: str | None) -> bool:
    """True only when production is positively excluded (the four-eyes development condition)."""
    return dev_self_approval_environment_permitted(runtime_profile, cors_allowed_origins)


def validate_loopback_allowlist_setting(
    raw: str | None, runtime_profile: str | None, cors_allowed_origins: str | None
) -> None:
    """Startup check: raise ``SettingsFieldError`` for a malformed or non-development allowlist."""
    if not str(raw or "").strip():
        return
    fields = ("source_sync_allow_loopback_hosts", "runtime_profile", "cors_allowed_origins")
    if not loopback_allowlist_environment_permitted(runtime_profile, cors_allowed_origins):
        raise SettingsFieldError(
            "loopback_stub_exemption_outside_development",
            "The loopback stub exemption is development-only. Unset it, or run a "
            "non-production runtime_profile whose cors_allowed_origins are all loopback.",
            fields,
        )
    try:
        parse_loopback_allowlist(raw)
    except LoopbackAllowlistError as invalid:
        raise SettingsFieldError(
            "loopback_stub_exemption_invalid",
            "Every loopback stub exemption entry must be a literal loopback address with a port "
            f"({invalid}).",
            fields[:1],
        ) from None


def effective_loopback_allowlist(settings: object) -> frozenset[str]:
    """The exemption in force for ``settings``: empty unless configured, valid and permitted."""
    raw = getattr(settings, "source_sync_allow_loopback_hosts", "") or ""
    if not str(raw).strip():
        return frozenset()
    if not loopback_allowlist_environment_permitted(
        getattr(settings, "runtime_profile", None), getattr(settings, "cors_allowed_origins", None)
    ):
        return frozenset()
    try:
        return parse_loopback_allowlist(str(raw))
    except LoopbackAllowlistError:
        return frozenset()


def _settings() -> object:
    from .config import get_settings

    return get_settings()


def loopback_stub_exemption(connection: str) -> frozenset[str]:
    """The exact ``host:port`` pairs ``connection`` may reach on loopback for this request.

    Empty for every connection type without a local stub, and empty whenever the
    exemption is unset, malformed or outside a local development stack. Settings are re-read
    and re-gated on every call.
    """
    if connection not in LOOPBACK_STUB_CONNECTIONS:
        return frozenset()
    return effective_loopback_allowlist(_settings())


__all__ = [
    "LOOPBACK_STUB_CONNECTIONS",
    "LoopbackAllowlistError",
    "loopback_stub_exemption",
    "effective_loopback_allowlist",
    "loopback_allowlist_environment_permitted",
    "parse_loopback_allowlist",
    "validate_loopback_allowlist_setting",
]
