# Changelog

## 0.0.1-alpha (unreleased)

The first public alpha of Octryx AI: the layer above your coding agents. Expect rough edges and breaking changes;
do not run it with production data or expose it to the internet.

- **One process for the team:** workflows from an idea in chat to a reviewed pull request. Shipped and on:
  Bug fix with a reproduction test, Story / epic delivery, Spec writing, PR review bot, PR explain. Shipped and off
  until a platform admin switches them on (Agents › Workflows): PR fix, Jira intake & triage, Incident / alert
  analysis, Team delivery.
- **Your coding agent stays:** with the launcher, a developer's Claude Code runs the workflow's turns under the team's
  rules and lands in the same record.
- **Knowledge:** the Workspace's documents, searchable with citations.
- **Governance:** approvals, four-eyes publishing, audit trail, Prometheus metrics (`octryx_*`).
- **Install:** Docker Compose on one machine (with a local demo: a sample shop on a local fake GitHub, its docs as
  Knowledge, the PR review bot and two work items) and a Helm chart for Kubernetes (build and push your own image).
  Native backend setup and start require Python 3.12 or newer. Served installers reject unresolved template variables.
- **Release labels:** Teams placeholder icons and newly serialized Office layout markers use current branding.
  Product-prefixed status badges use current labels; generic status labels and XML namespace lookup are unchanged.
- **Work item details:** optional source sections use plain field names or the current `octryx_` prefix.
- **Browser contracts:** current `octryx` event and storage names are used throughout
  ([list](frontend/chat/README.md#browser-keys-and-events)).
- **Removed from the alpha (Secure Work):** the user-facing pull request routes and the Work › Pull requests page
  (`/api/v1/secure-work/pull-requests` list, `/sync`, `/{id}/refresh`, `/{id}/reviewers`,
  `/work-items/{id}/pull-requests` and its Jira backlink preview now answer 404). A pull request a run or coding
  session opens is still recorded for its work item, shown on the run and the work item, and re-read from its host
  in the background. A work item and an intake keep the Workspace they were created in: an attempted change is a
  409 `workspace_immutable` and nothing is written.
- **Removed from the alpha (design traceability):** pull requests are no longer synced into design traceability
  (`POST /chat/api/panel/projects/{id}/design-traceability/sync-pull-requests` answers 404; the built-in
  `pull_requests` trace sync workflow and the `pull_request` source kind are gone, so the design tool and scheduled
  trace syncs run releases and checkpoints only). A trace link to a pull request can still be added by hand.
- **Chat start:** a phased start uses a Work Item of the chat's Workspace only; an item of another Workspace is
  treated exactly like a missing one.
- **Removed from the alpha (coding-agent gateway content handling):** the gateway forwards a request unchanged or
  refuses it, reading the whole body as one text minus an opaque key list
  ([README](README.md#sensitive-content-handling)). Removed: per-field protocol walking and shape validation (an
  unknown block or item type is no longer refused as `content_unreadable`), the opaque and authored path tables, the
  Claude Code built-in tool exemption, prompt-injection checks outside tool results (tool definitions, documents,
  citations, search results), email, internal IP, IBAN and phone handling on the gateway, `mask` / `reroute` /
  `mask_reroute` settings refusing a gateway request (they now apply to platform calls only), and the gateway's
  separate final-bytes check. On the gateway credentials are refused and credential assignments reported by default;
  a Workspace may set `refuse` or `report` for either.
- **Platform model calls:** the final check also refuses prompt injection and a reroute kind sent off its route; a
  platform instruction is skipped only when it is exactly a shipped seed text; each call and each gateway request
  has one decision record, written when it ends (Cedar's comparison no longer writes its own record for them); the
  record names a mask only where a value was replaced and a report only for a value sent. Governed chat's policy scan
  counts against the call's budget. A released tool result has one record (none when released unchanged with nothing
  to state), and the conversation's badge counts it only after the release.
- **Known limits:** workflows that only read or write text run on the server with your model key; a run that changes
  and tests code needs Claude Code or Codex on your machine, paired with the launcher. The local demo listens on
  `127.0.0.1` only.
