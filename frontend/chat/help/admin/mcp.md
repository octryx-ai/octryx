---
title: MCP servers
---

MCP servers add tools for agents, per Workspace.

### What you do here
- Choose the Workspace whose servers you manage with the Workspace switch at the top of the app; the page follows it.
- Install an approved preset from the catalog, or add a custom MCP server for cases the catalog does not cover.
- Open a server to see its details; connect, disconnect, edit or remove it, and allow it for agents.

### Next steps
- [Open Workspaces](/chat?area=admin&tab=projects)
- [Open connections](/chat?area=admin&tab=adminConnections)

### Catalog and custom servers
Approved MCP presets and custom MCP servers are managed in one place. Catalog installs use curated startup defaults; custom MCPs stay available for advanced cases. New registrations start inactive.

### Workspace scope
The list shows platform servers plus the selected Workspace's servers. Installs and custom servers belong to that Workspace.

### Allowing a server
Registering a server does not let agents use it yet: each Workspace must allow the server under its MCP capabilities (deny by default). Installing registers the server for the selected Workspace; its tools reach agents only after the Workspace allows it.

### The server table
- **Source**: *Catalog* for an approved preset (its preset is shown in the server's panel), *Custom* for a server added by hand.
- **Scope**: *Platform* servers are available to every Workspace; *Workspace* servers belong to the selected Workspace.
- **State**: *Connected* while the server exposes tools, *Not connected* until you connect it, *Inactive* for a registration that is switched off.
- **Tools**: how many tools the connected server exposes; unknown until it is connected.
- **Allowed in**: in how many Workspaces agents may use the server. *Not allowed* means no agent can use it yet.

### The server panel
A row opens the server: its description, address, vendor, preset and whether it starts on its own. The path from
registered over connected and allowed to tools visible to agents shows what is still missing; "Allow in Workspaces"
chooses the Workspaces and which of the server's tools they see. Edit changes the preset settings (custom servers
cannot be edited yet). The "⋯" menu opens the server's source and removes it; removing asks for confirmation.
