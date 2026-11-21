---
title: Plugins
---

Every plugin installed on this Octryx, in every Workspace, and installing one for the whole platform.

### What you do here
- See which plugins are installed, where, by whom and when, and what each one brought.
- Open a plugin to see what it was allowed to do when it was installed, its findings, its source and digests.
- Disable a plugin, or enable it again.
- Install a plugin for the whole platform with **Install plugin**. A Workspace installs its own plugins under
  Workspaces › a Workspace › Access › Plugins.

### Next steps
- [Open Workspaces](/chat?area=admin&tab=projects)

### Installing
1. **Source**: upload the plugin package (a ZIP file, at most 5 MB) or name a Git repository with branch and folder.
   Git hosts must be on the skill catalog's allowed hosts.
2. **What it wants**: Octryx reads the package and shows where it writes, which network targets it may reach, which
   connections it reads, and every skill, workflow, role, function and MCP server it brings. It also shows the
   findings of the skill check and anything that collides with what exists here. A conflict blocks the install.
3. **Confirm**: whoever installs a plugin is responsible for it. There is no second approval; the install is recorded
   in the audit log. If the package changed after you looked at it, Octryx shows what it wants now and asks again.

### Disable and enable
Disabling stops the plugin's skills from being delivered and makes the workflows, roles and MCP servers it created
inactive. Nothing is deleted; enabling turns everything back on.

### Pages and settings
- A plugin can bring its own pages. They appear in the menu of their area (for example Work) under the plugin's name,
  and on the phone under More. A page runs in a closed frame: it cannot reach the network or Octryx on its own and
  asks Octryx for everything it shows, always as the person looking at it, with that person's roles.
- When a page wants to change something (for example create a Confluence page), Octryx asks in its own dialog which
  plugin wants what. Only after you approve does the change happen; the next change asks again.
- A plugin's settings are on its detail. Whoever may install it changes them; everyone else sees them. A secret only
  shows whether it is set; leave its field empty to keep it.

### Good to know
- A plugin's own server comes in a later version of Octryx.
- Nothing a plugin brings is assigned to anyone automatically.
