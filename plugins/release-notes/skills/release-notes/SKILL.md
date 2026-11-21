---
name: release-notes
description: Write release notes for one release from what really shipped - the done Jira tickets of the fix version and the merged pull requests - for customers or for the team, and publish them to Confluence after the person confirms. Use when someone asks for release notes, a changelog, "what is in version X" for an announcement, or a release page.
when_to_use: Release notes, changelog, release announcement or release page for a named version.
license: Apache-2.0
metadata:
  plugin: octryx.release-notes
---

# Release notes from what shipped

Write release notes only from evidence: the tickets and pull requests of the release. Never invent a feature, and
never copy internal details into notes meant for customers.

## 1. Pin the release

- Ask for the version only if it is not in the request or the Work item. Find it with `list_jira_versions`
  (do not guess project keys; use `list_jira_projects` if needed).
- `jira_release_status` tells you whether the version is released, its date and its open blockers. Open blockers
  go into the notes as "Known issues" (or ask whether the release should wait, see the release-readiness skill).

## 2. Collect what shipped

- Tickets: `search_jira_tickets` with JQL `fixVersion = "<version>" AND statusCategory = Done ORDER BY issuetype`.
  Read a ticket with `get_jira_ticket` only when its summary does not say what changed for the user.
- Pull requests: the merged pull requests of the repository for this release (`list_github_pull_requests`,
  `list_bitbucket_pull_requests` or `list_gitlab_merge_requests`, state merged). Use them to confirm and enrich the
  tickets, and to find changes without a ticket (list those separately; ask whether they belong in the notes).
- Tickets of the version that are not done are not in the release. Mention them only in the team version.

## 3. Write

Use [template.md](template.md). Group into **New**, **Improved**, **Fixed**, **Known issues**, in that order;
leave out an empty group.

- **Customers** (default when the person says "customers", "public", "announcement"): one line per change in plain
  language: what the user can do now, not how it was built. No ticket keys, no internal names, no people.
  Security fixes: say that a security issue was fixed, never how to exploit it.
- **Team**: the same groups, each line with the ticket key and link and the pull request link; add "Not in this
  release" for tickets of the version that are still open.
- Write in the language of the request; keep product names as they are.
- End with: "These release notes were drafted with AI and reviewed by <person>." (transparency, EU AI Act Art. 50).

## 4. Confirm, then publish

Show the full text and ask: right as it is, or what to change? Publish only after a clear yes.

- Confluence: search the space first (`search_confluence` for "Release notes <version>"). If the page exists and
  someone else wrote it, do not overwrite it; ask. Otherwise `create_confluence_page` with the title
  "Release notes <version>" in the space the person names (ask if unknown), under the parent page they name.
- Reply with the page link and the number of tickets and pull requests the notes are based on.
