"""The egress rule every Source Sync request passes before a credential leaves the pod."""

from __future__ import annotations

import httpx

from ....outbound_egress import egress_transport


def source_egress_transport(
    connection_kind: str, *, inner: httpx.AsyncBaseTransport | None = None, verify: bool = True
) -> httpx.AsyncBaseTransport:
    # The egress check runs before the injected transport in every case.
    return egress_transport(connection_kind, inner=inner, verify=verify)


__all__ = ["source_egress_transport"]
