---
title: Connector settings
---

The built-in connectors and private hosts. Open it from Connections ("Connector settings"); "← Connections" leads back.

### What you do here
- **Set up a built-in connector** (beside the page name) picks a built-in connector from the catalog; fill in its setup in the side panel that opens. A new system to connect is added with **Add connection** on Connections.
- Open a connector's row to check its health and tools. **Pause**/**Resume** is at the bottom of its panel; **Remove…** is in its ⋯ menu.
- Allow private hosts for on-premises systems.

### Next steps
- [Open connections](/chat?area=admin&tab=adminConnections)
- [Open MCP servers](/chat?area=admin&tab=mcp)

### A connector's panel
- **Connection**: the base URL. Atlassian Cloud is `https://your-site.atlassian.net` (Confluence adds `/wiki`); for Server or Data Center use the base URL including any context path.
- **Authentication**: where the system runs (Atlassian Cloud, signed in with an account email and an API token, or your own Server / Data Center instance) and how an own instance signs in: username and password, a personal access token, or OpenID Connect client credentials (the token URL of your identity provider, a client id and secret; scope and audience only when your identity provider requires them, sent as entered). Hover a choice to see what it means.
- **Saved:** says which sign-in is stored. Saving does not verify it: **Test saved connection** (bottom right, beside **Save**) checks the saved URL and account only, not unsaved changes and not access to the listed projects, spaces or tables.
- **Named connections**: a connection serves the keys bound to it (spaces, projects, tables, accounts …) with its own account; every other key uses the default connection. Global connections apply in every Workspace whose connector is on, unless the Workspace binds the key itself. **Copy ID** copies a connection's id, which never changes.
- **Health checks** lists the last five checks; **Tools** lists what the connector adds for agents.

### The connector catalog
The catalog is listed alphabetically. Each entry shows which secrets it stores and how many tools it adds.

### Private hosts (on-premises systems)
Connectors normally reach public addresses only. List the exact host:port of an on-premises instance (IPv6 in brackets) to allow it for that connection type. Pod-local and metadata addresses are always refused; every change is audited. Forms appear for configured connectors that support an on-prem edition.
