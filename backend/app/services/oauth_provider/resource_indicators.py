"""RFC 8707 resource indicators accepted by the platform OAuth server.

The JWT audience of an access token is derived from the requested
``resource``. Only resources that a platform resource server actually
verifies are accepted; anything else is refused with ``invalid_target``
instead of minting a token for an audience nobody checks.

Closed set:
- absent or blank: no explicit resource (the minted audience defaults to
  ``octryx-mcp``);
- ``octryx-mcp``, ``octryx-model-gateway`` and ``octryx-device`` (the device channel,
  minted for device grants only): minted as-is;
- the MCP resource URLs accepted by the MCP verifier
  (``acceptable_mcp_audiences``): minted as-is;
- the MCP resource URL advertised by ``/.well-known/oauth-protected-resource``
  (``{issuer}{mount}{streamable}``, what VS Code Copilot sends): minted as the
  canonical MCP audience ``octryx-mcp`` when the verifier does not
  list that URL itself (public hostnames), so the token stays usable without
  widening the verifier's accepted audiences.
"""

from __future__ import annotations

from ..agent_gateway.contract import GATEWAY_AUDIENCE
from ..devices.contract import DEVICE_AUDIENCE
from .flows import OAuthFlowError
from .resource import acceptable_mcp_audiences
from .tokens import DEFAULT_RESOURCE_AUDIENCE

INVALID_TARGET = "invalid_target"
_INVALID_TARGET_DESCRIPTION = "The requested resource is not served by this platform"


def _mcp_resource_paths() -> tuple[str, str]:
    from ..mcp_knowledge_protocol import KNOWLEDGE_MCP_MOUNT_PATH, KNOWLEDGE_MCP_STREAMABLE_PATH

    return KNOWLEDGE_MCP_MOUNT_PATH, KNOWLEDGE_MCP_STREAMABLE_PATH


def resolve_resource_indicator(raw: str | None, *, issuer: str) -> str | None:
    """Return the audience to mint for ``raw``; None when no resource was requested.

    Raises ``OAuthFlowError("invalid_target", ...)`` for any other value. The
    raw value is never echoed in the error.
    """
    value = (raw or "").strip()
    if not value:
        return None
    if value in (DEFAULT_RESOURCE_AUDIENCE, GATEWAY_AUDIENCE, DEVICE_AUDIENCE):
        return value
    mount_path, streamable_path = _mcp_resource_paths()
    mcp_audiences = acceptable_mcp_audiences(mount_path=mount_path, streamable_path=streamable_path)
    if value in mcp_audiences:
        return value
    if value == f"{issuer.rstrip('/')}{mount_path}{streamable_path}":
        return DEFAULT_RESOURCE_AUDIENCE
    raise OAuthFlowError(INVALID_TARGET, _INVALID_TARGET_DESCRIPTION)
