# Source Sync listing tokens

A listing pass resumes from `SyncCursor.token` (`cursor.py`), at most `MAX_TOKEN_CHARS` characters. The token is
the connector's own and opaque to the runner; `None` starts a pass, and a page with no next token ends it.

| Connector | Token | Notes |
|---|---|---|
| Confluence | `<unit index>:<next link>` | A unit is a whole space, then each configured page tree. A unit starts at `<index>:0`; after that the token carries the source's own `_links.next`, followed verbatim relative to the base URL (Cloud pages by opaque cursor, Server/Data Center by offset). A multi-connection connector (`confluence_multi.py`) keeps the same form over its units. |
| Jira Server/Data Center | `<offset>` | `GET /rest/api/2/search`, paged by `startAt`. |
| Jira Cloud | `c:<nextPageToken>` | `POST /rest/api/3/search/jql`, paged by Jira's opaque token. A token of the other API never pages on. |
| Jira releases | `r:<project index>:<offset>` | After the last issue page, when a release configuration is active (`jira_releases.py`); starts at `r:0:0`. |
| ServiceNow | `<target index>:<offset>` | `kb_knowledge` for the configured knowledge bases first, then each configured record table, paged by `sysparm_offset`; the scripted source uses the same form. |
| Kubernetes | `<offset>` | The position in the namespace list, sorted by name. |
| git (`remote_git`) | `<commit sha>:<offset>` | The pass resolves `ref` once; every later page carries that sha, so a pass over several runs never mixes two commits. |

A `local_snapshot` repository has no listing token: its pass state is the cursor's `snapshot` entry
(`repository_snapshot/protocol_types.py`).

An incremental change listing keeps its own token in `incremental_token`, in the form of the connector's header
listing.

## Pinned Confluence read

`ConfluenceConnector.fetch_pinned_view` reads one published page again at exactly its published version, for the
documentation provenance check (`workflow_runs/documentation/knowledge.py`). It goes through one bounded
compatibility profile (`confluence_pinned.LEGACY_VIEW_PROFILE`): Confluence Cloud only, one endpoint
(`GET /rest/api/content/{id}` with `body.view,version`), so its bytes compare with the ingested revision. A response
outside its strict shape, a version other than the pinned one, or a removed endpoint (404/410) is a refusal; there is
no fallback. The profile records its removal dependency, the deprecation of the v1 content endpoint. The sync's own
`fetch` does not use it.
