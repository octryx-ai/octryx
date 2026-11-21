---
title: Workspaces
---

A Workspace keeps one customer, team or product apart: its own access, sources, repositories and rules.

### What you do here
- Create a Workspace.
- Open a Workspace to see its essentials in a side panel: default, class, members and their roles, sources, the connections available in it and its problems.
- Open its settings (the panel's "Open settings") to set access, connections, knowledge and models. The settings are grouped: **Overview** (with Diagnostics), **Access**, **Models & agents** (Models, Agents & skills, Coding tools & devices, Voice), **Data** (Connectors, Knowledge, Repositories) and **Rules & monitoring** (Rules, Observability).
- Make it the default, archive or delete it from the row's ⋯ menu.
- Archive a Workspace you no longer use.

### Next steps
- [Add members and roles](/chat?area=admin&tab=users)
- [Open connections](/chat?area=admin&tab=adminConnections)
- [Add a knowledge source](/chat?area=knowledge&tab=workspaceKnowledge)
- [Check the models](/chat?area=admin&tab=providers)
- [Review agents](/chat?area=workflows&tab=agents)

### Data › Connectors
- **Connections** lists the connections available in this Workspace. They are read-only here: set them up, test them and choose where they are available in [Admin › Connections](/chat?area=admin&tab=adminConnections). A row opens the connection there.
- **Connector access** is what only a Workspace sets for each platform connector. A row opens it in a side panel:
  - **Use … in this Workspace** turns the connector on or off for this Workspace. Save access stores this and the limits; it never changes the connection.
  - **Workspace limits** narrow what the connector may reach here (Jira projects, Confluence spaces and pages, Bitbucket repositories, …). Empty: the platform connector's limits apply. Workspace limits override them.
  - **Connection** (Jira, Confluence): use the platform connection, or an own URL and account for this Workspace only.
  - **Named connections**: one account per project, space or repository; everything else uses the default connection.
  - **Effective inherited limits** shows the platform limits in effect.
- "Global setup required": the connector is on here, but cannot run until the platform connector is set up and on, or this Workspace has its own connection.
- The platform connectors themselves are set up under Admin › Connections › Connector settings.
- **MCP servers** are registered, connected and bound to secrets under Admin › Connections › MCP servers. A server is usable in this Workspace only after the Workspace allows it here.

### Good to know
- The default Workspace is protected platform data.
- Whether members' local git checkouts become a knowledge source is set in the Workspace's settings under Repositories ("Allow local snapshots").
