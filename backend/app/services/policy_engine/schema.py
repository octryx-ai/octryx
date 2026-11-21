"""The Cedar schema and its fixed vocabulary.

The schema text is versioned in this package (``octryx.cedarschema``); :data:`SCHEMA_VERSION` changes
with it, and every stored policy-set version and decision-log row records the version it was checked against.
Entity types, actions and the policy-id namespaces below are the only names the translator, the enforcement
points and the editor use.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

SCHEMA_VERSION = "2026-10-08.2"
SCHEMA_PATH = Path(__file__).with_name("octryx.cedarschema")

ENTITY_USER = "User"
ENTITY_AGENT_SESSION = "AgentSession"
ENTITY_ROLE = "Role"
ENTITY_GROUP = "Group"
ENTITY_WORKSPACE = "Workspace"
ENTITY_CONNECTOR_FAMILY = "ConnectorFamily"
ENTITY_TOOL = "Tool"
ENTITY_MODEL_ALIAS = "ModelAlias"
ENTITY_REMOTE_MODEL = "RemoteModel"
ENTITY_COMMAND = "Command"
ENTITY_PATH = "Path"
ENTITY_DEVICE = "Device"

ACTION_USE_SEAT = "use_seat"
ACTION_CALL_MODEL = "call_model"
ACTION_USE_RERANKER = "use_reranker"
ACTION_USE_REMOTE_EMBEDDINGS = "use_remote_embeddings"
ACTION_CALL_TOOL = "call_tool"
ACTION_READ_CONNECTOR = "read_connector"
ACTION_WRITE_CONNECTOR = "write_connector"
ACTION_RUN_COMMAND = "run_command"
ACTION_READ_PATH = "read_path"
ACTION_WRITE_PATH = "write_path"
ACTION_RECEIVE_TOOL_RESULT = "receive_tool_result"
ACTION_RUN_ON_DEVICE = "run_on_device"
ACTIONS: tuple[str, ...] = (
    ACTION_USE_SEAT,
    ACTION_CALL_MODEL,
    ACTION_READ_CONNECTOR,
    ACTION_WRITE_CONNECTOR,
    ACTION_CALL_TOOL,
    ACTION_RUN_COMMAND,
    ACTION_READ_PATH,
    ACTION_WRITE_PATH,
    ACTION_USE_RERANKER,
    ACTION_USE_REMOTE_EMBEDDINGS,
    ACTION_RECEIVE_TOOL_RESULT,
    ACTION_RUN_ON_DEVICE,
)

# ``context.route`` of ``call_model``.
ROUTE_SEAT = "seat"
ROUTE_GOVERNED = "governed"
# ``context.origin`` of ``receive_tool_result``.
ORIGIN_CONNECTOR = "connector"
ORIGIN_MCP = "mcp"
ORIGIN_CLIENT = "client"
SEAT_MODEL_PREFIX = "seat:"
CLIENT_TOOL_PREFIX = "client:"

# ``context.point`` of the client-tool actions: the gateway's PreToolUse check, or Claude Code's own rules.
POINT_GATEWAY = "gateway"
POINT_CLIENT = "client"

# Policy-id namespaces. Generated ids start with one of these; a hand-written (custom) policy may not.
ID_PLATFORM = "platform:"
ID_CLASSIFICATION = "classification:"
ID_WORKSPACE = "workspace:"
RESERVED_ID_PREFIXES: tuple[str, ...] = (ID_PLATFORM, ID_CLASSIFICATION, ID_WORKSPACE)

UNKNOWN_ID = "unknown"


@lru_cache(maxsize=1)
def schema_text() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


__all__ = [
    "ACTIONS",
    "ACTION_CALL_MODEL",
    "ACTION_CALL_TOOL",
    "ACTION_READ_CONNECTOR",
    "ACTION_READ_PATH",
    "ACTION_RECEIVE_TOOL_RESULT",
    "ACTION_RUN_ON_DEVICE",
    "ACTION_RUN_COMMAND",
    "ACTION_USE_REMOTE_EMBEDDINGS",
    "ACTION_USE_RERANKER",
    "ACTION_USE_SEAT",
    "ACTION_WRITE_CONNECTOR",
    "ACTION_WRITE_PATH",
    "CLIENT_TOOL_PREFIX",
    "ORIGIN_CLIENT",
    "ORIGIN_CONNECTOR",
    "ORIGIN_MCP",
    "ROUTE_GOVERNED",
    "ROUTE_SEAT",
    "SEAT_MODEL_PREFIX",
    "ENTITY_AGENT_SESSION",
    "ENTITY_COMMAND",
    "ENTITY_CONNECTOR_FAMILY",
    "ENTITY_DEVICE",
    "ENTITY_GROUP",
    "ENTITY_MODEL_ALIAS",
    "ENTITY_PATH",
    "ENTITY_REMOTE_MODEL",
    "ENTITY_ROLE",
    "ENTITY_TOOL",
    "ENTITY_USER",
    "ENTITY_WORKSPACE",
    "ID_CLASSIFICATION",
    "ID_PLATFORM",
    "ID_WORKSPACE",
    "POINT_CLIENT",
    "POINT_GATEWAY",
    "RESERVED_ID_PREFIXES",
    "SCHEMA_PATH",
    "SCHEMA_VERSION",
    "UNKNOWN_ID",
    "schema_text",
]
