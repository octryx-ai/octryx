"""Where a connection came from (``config["connection_origin"]``).

Connections created through the connections API carry ``{"kind": "connections_api"}``; an update keeps the stored
origin (``services/connections/writes.py``). It is provenance only, never read for a secret.
"""

from __future__ import annotations

CONNECTION_ORIGIN_KEY = "connection_origin"


__all__ = ["CONNECTION_ORIGIN_KEY"]
