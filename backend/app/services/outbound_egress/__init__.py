"""Outbound egress: one rule per connection type, an admin-governed on-prem allowlist, and pinned connects.

- ``connections.py``: the closed table of connection types and their rules;
- ``private_hosts.py``: the admin-governed private ``host:port`` allowlist;
- ``target_check.py``: the policy check with the connection's allowlist;
- ``pinned_transport.py``: the ``httpx`` transport that connects only to checked addresses;
- ``public_web.py``: the pinned client of the uncredentialed web fetches, proxy only when named.
"""

from __future__ import annotations

from .connections import *  # noqa: F403 - the connection constants are this package's vocabulary
from .connections import __all__ as _connection_names
from .pinned_transport import EgressRefusedError, PinnedEgressTransport, egress_transport

__all__ = [*_connection_names, "EgressRefusedError", "PinnedEgressTransport", "egress_transport"]
