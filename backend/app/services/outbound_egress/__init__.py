"""Outbound egress: one rule per connection type, an admin-governed on-prem allowlist, and pinned connects."""

from __future__ import annotations

from .connections import *  # noqa: F403 - the connection constants are this package's vocabulary
from .connections import __all__ as _connection_names
from .pinned_transport import EgressRefusedError, PinnedEgressTransport, egress_transport

__all__ = [*_connection_names, "EgressRefusedError", "PinnedEgressTransport", "egress_transport"]
