# Workspace routes

A Workspace's settings: connections and their deviations, content handling, models, repositories, members, code
style, web search sources, MCP servers and settings sections with their own editor.

## Invariants

- A Workspace admin or owner may only narrow a platform setting; loosening one answers 403 `platform_admin_required`
  (`services/workspace_settings/bounds.py`).
- An unknown Workspace and one the caller is no member of are the same 404 `project_not_found` for a Workspace's
  connections (`workspace_connections.py`, `services/access_control.require_visible_workspace`).
