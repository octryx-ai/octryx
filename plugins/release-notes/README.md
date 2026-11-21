# Release notes (Octryx plugin)

Release notes from what really shipped: the done Jira tickets of a fix version and the merged pull requests,
written for customers or for the team, confirmed by a person and published to Confluence.

| Brings | What it does |
|---|---|
| Skill `release-notes` | Pins the version, collects the done tickets and merged pull requests, writes New / Improved / Fixed / Known issues for customers (plain language) or the team (with ticket and PR links), marks the text as AI-generated, and creates the Confluence page only after you confirm. |
| Skill `release-readiness` | Go / no-go before a release: open blockers, open tickets, done tickets with open pull requests, each with its link. Reads only. |
| Workflow `release-notes` | A run on the release's Work item: collect and draft (reads only), you confirm or send it back with your changes (up to three rounds). |
| Page `Releases` (Work, phone) | Pick a version: go / no-go, done / open / blockers and the done tickets with links. Reads only, as the person looking at it. |
| Role `release_manager` | Read, Work items, runs, connector writes, plus the function `release_notes` (the release and Confluence tools above). Assigned by a Workspace admin, never automatically. |

It uses the Workspace's Jira, Confluence and code host connections; it writes only to Confluence, and only after a
confirmation. No code, no container, no network access of its own.

## Install

Copy it into your Octryx image (`RUN cp -r /opt/octryx/plugin-examples/release-notes /opt/octryx/plugins/`), then
switch it on under Workspace › Plugins. How to build your own is in [../README.md](../README.md).

