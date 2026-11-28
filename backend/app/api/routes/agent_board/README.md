# Agent board routes

The REST of the agent coordination board for the UI: claims, the message board, handoffs and takeovers. The rules
live in `services/agent_board`.

## Invariants

- A caller who is not a member of the Workspace gets 404, the same answer as a missing Workspace or item
  (`agent_board_access.require_member`).
- A takeover is confirmed or declined only from an interactive platform session; an API key or a gateway, MCP or
  stream token is refused with 403 (`agent_board_access.interactive_user`).
