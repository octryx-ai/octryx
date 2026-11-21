"""The egress rule every Source Sync request passes before a credential leaves the pod.

A connection's URL comes from a tool configuration, so it may name any host. Every request (the
Confluence, Jira and ServiceNow reads and the ServiceNow token grant) goes through the pinned
egress transport of its connection type (``services/outbound_egress``): the target is checked
after one DNS resolution with the same rule the chat tools use for that connection
(``public_only`` plus the admin-governed on-prem allowlist), and the request connects only to
the checked address. A refusal is the fixed reason ``egress_refused``; nothing is sent.
Source Sync never follows a redirect (``http.py``), so no second hop exists.

The only other exemption is the loopback stub allowlist of the stubbed connection
types (``app/loopback_stub_policy.py``), which the pinned transport itself re-reads and
re-gates on every request; Source Sync passes nothing of its own.
"""

from __future__ import annotations

import httpx

from ....outbound_egress import egress_transport


def source_egress_transport(
    connection_kind: str, *, inner: httpx.AsyncBaseTransport | None = None, verify: bool = True
) -> httpx.AsyncBaseTransport:
    """The pinned transport of a Source Sync connection kind (``confluence``/``jira``/``servicenow``/``kubernetes``).

    ``inner`` is the reader's injected transport (tests, the local stubs); the egress check runs
    before it in every case. ``verify`` is the connection's own TLS setting (a Kubernetes connection
    may turn it off, as its tools do); every other connection verifies.
    """
    return egress_transport(connection_kind, inner=inner, verify=verify)


__all__ = ["source_egress_transport"]
