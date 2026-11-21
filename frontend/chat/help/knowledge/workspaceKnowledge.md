---
title: Sources
---

The systems Knowledge learns from for this Workspace, and whether each one is up to date.

### What you do here
- Add a source: a Confluence space, Jira project, ServiceNow knowledge base or records, a Git repository or a Kubernetes cluster.
- Sync a source now; pause, edit or remove it from its ⋯ menu.
- Open Details for the last sync, how fresh the source is and the items it handled.

### Next steps
- [Open connectors](/chat?area=admin&tab=connectors)
- [Open documents](/chat?area=knowledge&tab=knowledgeSources)
- [Ask a question in Search](/chat?area=knowledge&tab=knowledgeLibrary)

### States
- **Up to date**: the last sync finished cleanly and a schedule keeps the source current.
- **Synced**: the last sync finished cleanly, but no schedule keeps the source current (synced by hand, by launcher upload, or automatic sync is off on this instance).
- **Out of date**: as Synced, but the last sync is more than 14 days old; it says how old. Problems lists it too.
- **Syncing**: a sync runs now, or a long listing continues with the next sync.
- **Needs attention**: the last sync failed or left items; the card says why.
- **Paused**: no scheduled syncs until someone resumes it.
- **Never synced**: nothing was synced yet.

### Before the first source
A source reads through a connection to its system. Connect Confluence, Jira or ServiceNow under Admin → Connectors first, then add it here. Nothing is ever written back to the source system. Adding the first source switches Knowledge on for the Workspace.

### Syncs and freshness
- **Sync now** performs a full pass: it lists every item in scope, retires items deleted or moved at the source and re-checks permissions, in steps when the scope exceeds the items per sync.
- Items restricted in the source system are withheld until access rules are enforced in search; they count as skipped and are listed without a title.
- A sync's per-item log keeps the first 200 items; the counts cover all of them.
- Local repository snapshots arrive by launcher upload: they have no syncs here, and their last upload counts as their last sync.

### Advanced fields
- **Connection id**: empty, each space, project or table uses the connection that binds it. To read only with one named connection, paste its id (Connectors → Named connections, "Copy ID") or enter `default`.
- **Products** and **Version** tag every synced revision.

### Local repository snapshots
A Workspace setting under Settings → Workspace → Repositories ("Allow local snapshots"). When it is on, a member who starts octryx-claude in a git checkout uploads its tracked files at HEAD (secrets redacted, key and env files skipped) as a repository source, so code questions answer from that commit. When it is off, the session is bound to the repository but nothing is uploaded.

### Adding a source: what each kind needs
- **Confluence space key**: it is in the page address. On Confluence Cloud `https://your-site.atlassian.net/wiki/spaces/KEY/pages/…`, on Server or Data Center `…/display/KEY/…` or `…/spaces/KEY/…`. Paste an address and the form names its key.
- **Confluence page trees**: a tree's space must be one of the connection's allowed spaces. A page moved out of a tree is removed from this Workspace's knowledge when the next sync completes its listing.
- **Git repository**: github.com reads public repositories; bitbucket.org reads with this Workspace's Bitbucket Cloud connection bound to the repository. A commit sha as ref reads the same content at every sync; a branch or tag is resolved to a commit at every sync, and the run report records which.
- **Schedule**: a custom interval is 15 minutes to 7 days. When automatic sync is off on this instance, only Sync now syncs until an operator switches it on.
