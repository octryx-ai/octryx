---
name: release-readiness
description: Check whether a release can ship - open tickets and blockers of the fix version, pull requests not yet merged, done tickets without a merged change - and give a clear go / no-go with the list of what is missing. Use before a release, for "can we release X", "what is still open in version X" or a release checklist.
when_to_use: Go / no-go or open-items check before releasing a named version.
license: Apache-2.0
metadata:
  plugin: octryx.release-notes
---

# Release readiness: go or no-go, with evidence

Answer with facts queried now, never from memory or knowledge pages. Say "as of <time>".

1. **Status**: `jira_release_status` for the version: released or not, release date, tickets per status category,
   open blockers (each with its link).
2. **Open tickets**: `search_jira_tickets` with JQL `fixVersion = "<version>" AND statusCategory != Done`. Group by
   status; name the assignee only for the team.
3. **Open changes**: open pull requests that mention the version's ticket keys (`list_github_pull_requests`,
   `list_bitbucket_pull_requests` or `list_gitlab_merge_requests`, state open). A done ticket with an open pull
   request is not done; list it.
4. **Verdict**:
   - **Go**: no open blockers, no open tickets, no open pull requests of the version.
   - **No-go**: list exactly what blocks, most important first, each with its link and who can resolve it.
   - **Go with known issues**: only when the person says the open items may ship as known issues; they then go
     into the release notes (skill release-notes).
5. Change nothing: no transitions, no version release, no comments. If the person wants to move a ticket out of
   the version or release it in Jira, that is their decision and a separate, confirmed step.
