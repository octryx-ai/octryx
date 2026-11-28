# Changelog

## 0.0.2-alpha (2026-11-28)

Agents no longer run inside the platform: every agent turn runs as Claude Code or Codex, on a developer's device or on
the server runners, a pool of sandboxed containers the installation runs itself. Governed model calls go through
LiteLLM (bundled, or an external LiteLLM gateway); seat calls go through the gateway's seat relay to the person's own
subscription. Sessions live on the platform, so a thread moves between devices, runners and people. A private
Workspace stays hidden from everyone else, platform admins included.

### Upgrade notes

The database upgrades itself at start. Check these before you upgrade a 0.0.1-alpha install:

- **Models move to LiteLLM.** The direct provider drivers are gone: AWS Bedrock, GitHub Copilot, Google Gemini with
  its Google login, OpenRouter, OpenAI-compatible and Ollama, with their admin sections, the local model setup, the
  Bedrock price sync and the old `/admin/control-plane` page. A provider row of a removed driver stops working; add the
  model again in **Admin › Models**. GitHub Copilot is not available in 0.0.2. The first start still turns
  `LLM_PROVIDER` and `AGENT_DEFAULT_MODEL` (with `LLM_API_KEY`, `LLM_ENDPOINT_URL`, `OPENROUTER_API_KEY` or the AWS
  settings) into a model of the bundled LiteLLM and the default, once.
- **Helm:** the existing Secret needs `LITELLM_MASTER_KEY` (starting with `sk-`) and `LITELLM_SALT_KEY`, and
  `LITELLM_DATABASE_URL` with `database.internal=false`. The server runners are new and off by default
  (`runners.enabled`); see the chart README for the runtime class and the NetworkPolicy. No existing key changed.
- **Compose:** the stack now also runs LiteLLM, the runner gateway and one server runner. The runner image is built
  locally and is about 5 GB.
- **Codex:** the launcher runs Codex turns on `codex app-server` and needs Codex 0.169.0 or newer. The Codex seat's
  device mode is gone (the seat traffic switch, its admin card and the launcher's loopback proxy): Codex seat calls go
  through the platform's seat relay only, and Codex's hosted web search is off on the seat.
- **Handover API:** the run handover routes are replaced by `/api/v1/session-handovers` (`POST`, `GET .../pool`,
  `POST .../{id}/accept`, `POST .../{id}/decline`).
- **Webhooks:** a connector watcher without a webhook secret refuses webhook events (401, or the 404 of an unknown
  watcher in a private Workspace). Set `webhook_secret` to receive events; polling is unaffected.
- **MCP clients** that listed every platform tool now find most of them through `tool_search` (see Tools).
- **Content handling on the coding-agent gateway** follows the Workspace's settings (see Security); its shipped
  default masks credentials instead of refusing them.
- **Removed: graph flows and the orchestrator.** The flow builder in the admin panel, graph flow runs with their
  traces and test cases, the flow tools (`run_flow_…`) and `/api/v1/orchestrator` are gone, with their tables.
  Workflows that run in phases are unchanged; `/api/v1/flows` keeps the definition routes (list, create, drafts,
  validate, archive, publish, request review), which accept phased definitions only.
- **Workspace classification default:** an empty `OCTRYX_KNOWLEDGE_DEFAULT_DATA_CLASSIFICATION` now means `internal`
  (it was unclassified): new Workspaces, and unclassified ones when Knowledge is enabled, get `internal`. Set it to
  `none` to keep them unclassified; a default an admin stored still wins.
- **Launcher:** update octryx-claude on every developer machine. A device gets a turn only for an engine it reported at
  its handshake (Claude Code, Codex); an older launcher reports none, and its turns are refused as
  `device_engine_missing`.
- **Removed:** the platform's own agent loop and what only it used (the LLM response cache, context compaction,
  sub-agent groups, repo microagents), the built-in Coding agent, the `lint_passed` check type, SCIP indexing in code
  intelligence, the Teams call-proxy redirect with its "Calling webhook URL" fields, the distributed worker runtime and
  the launcher's sandbox enrollment. The emergency stop's `other_private_runs_paused` and
  `other_private_device_jobs_stopped` are now `hidden_runs_paused` and `hidden_device_jobs_stopped`.
- **Removed with their admin panels and tables:** scenario profiles, context budget profiles, the system prompt
  variant routing with its revision history, tool-result compression (its compressors and log), the models'
  planner context budget, and runtime settings only the old agent loop read (completion token defaults, elastic
  iteration, LLM cache TTLs, tool planner limits, stuck-loop thresholds).
- **Runtime settings API:** `PUT /admin/chat/api/panel/runtime-settings` answers 400
  (`unknown_runtime_settings`, naming the keys) for a key it does not write, and saves nothing; before, such a key
  was silently ignored. Scripts that send removed settings must drop them.

### Where agents run

- **Server runners:** containers from the `octryx-runner` image (Codex pinned, a browser with Playwright, no
  internet): the launcher runs Codex there under a separate agent account with no capabilities, on a network that
  reaches only the runner gateway. Runners enroll with the installation's join secret. A runner serves one person in
  one Workspace at a time and empties its disk before it switches. Kubernetes: a runner Deployment and gateway, egress
  limited by NetworkPolicy; the api admits only runners on the configured container runtime (`runtimeClassName`),
  otherwise the pool answers `needs_configuration`. A Workspace can forbid server runners.
- Chat turns from the web, the phone, `/api/v1` and Teams, scheduled tasks, and the turns of a workflow run the server
  runs all go to the server runners unless they run on a person's device. `/api/v1` and Teams wait for the answer and
  keep their responses. A turn without a model takes the Workspace's first governed model. The platform actions of a
  run (push, pull request, Jira) and the review stay on the platform.
- **Teamwork on runners:** a teamwork run on the server runners runs each item as a runner job in its own worktree
  branch inside the run's folder (one after another on a runner with one slot). The server-side teamwork executor is
  gone.
- **Waiting for a runner:** with every server runner busy, a chat message is kept and its turn waits as "Waiting for a
  server runner" until one is free, first come first served; Stop cancels the wait. Without any server runner set up
  the message is refused as `needs_configuration` (`runner_pool_not_set_up`).
- **Repositories on runners:** a runner fetches its run's branch from the platform over read-only git with a 10-minute
  token bound to the run; it never holds a repository credential and cannot push. The platform pushes the reviewed
  change and opens the pull request. The review result names the screenshots its verdict judged.
- **Chat on a device or runner:** a context meter and Compact, Stop ends the runner's turn, deciding an approval in the
  chat continues the thread, diagrams arrive whole, Codex answers stream.

### Sessions

- **Session files on the platform:** after each turn the launcher uploads the engine's session files (Claude Code's
  transcript, Codex's thread), encrypted at rest; only the device that runs the session's active turn can fetch them. A
  thread survives its runner container and moves to another device or runner.
- **Session pool:** a person can hand a session to a colleague or put it into the Workspace's pool; members see what
  waits and take it over in the web companion (Pool tab) or on the phone. The session, and the workflow run that
  follows it, continue on the same thread on the taker's device or runner.
- **Seat takeover:** a run phase that needs a person's Claude or ChatGPT seat on the server runners pauses as
  `seat_required`; its requester takes it over on a device that holds that seat, and the phase resumes there.
- Pull requests that runs and agents open link their run, session and approved plan; the chat lists a session's pull
  requests.

### Models

- **Admin › Models** manages the bundled LiteLLM's models in one table: add, edit, test or remove a model (Anthropic,
  OpenAI, AWS Bedrock, Azure OpenAI, Google Gemini, OpenRouter, Ollama, OpenAI-compatible) with its credential, data
  class, context window, price and tools. The credential is stored only in LiteLLM. A model needs both prices above 0.
  "Add provider" adds only an external LiteLLM gateway. A Bedrock model takes temporary AWS credentials (AWS SSO, an
  assumed role) with their session token, also at the first start. Such credentials expire, and the model stops
  working then: enter new ones in Admin › Models, or use a long-lived key pair.
- LiteLLM (pinned v1.82.0-stable) runs on the api pod's loopback only, with its own database and no UI or logging.
- A Workspace that never saved its model list may use every admitted model its data class clears.
- Codex works with a model added in Admin › Models (LiteLLM's simulated stream is turned into the events Codex needs).

### Codex and Claude Code

- Codex device turns run on `codex app-server` with only the launcher's hooks, settings and platform tools. A
  repository's own `.codex/config.toml` cannot change them (the turn is refused), which fixes
  [GHSA-h4xh-8wqf-rxj4](https://github.com/octryx-ai/octryx/security/advisories/GHSA-h4xh-8wqf-rxj4).
- A conformance suite checks that Claude Code and Codex get the same platform decision for the same act; the few
  differences by design are listed in it.
- Devices report the engines they run and whose seat they hold. A seat takeover and a pool entry go only to a device
  with that engine (and seat); a pool turn whose engine nobody chose runs on an engine the runner reported.

### Tools

- Codex and Claude Code sessions get the platform's tools from the web chat's registry, with the same visibility
  (classification, active connectors, the Workspace tool policy, work roles). The session MCP endpoint lists a small
  basic set plus `tool_search` and `tool_call`. A write or admin tool called over MCP waits for a person's approval in
  Octryx; infrastructure actions, logs, config and secret reads are never offered over MCP.

### Workflows and checks

- **Progress per Epic:** Work › Epics shows each story and its sub-tasks as done, in review (with its checks), in
  progress (with the run's phase) or open, derived from recorded events only: the work state, the latest run, the
  pull request record and CI (`GET /api/v1/secure-work/work-items/{id}/progress`). The phone shows a summary card
  per Epic.
- **Bounded retries:** a failed check goes back to the agent at most N times (Workspace setting, default 3); then the
  run pauses as `checks_failed` with the failed checks, so red work is never reported as done.
- **Change plan scope:** a plan phase records its change plan as data. Writes to expensive paths (migrations,
  auth/permissions, infrastructure, public API contracts; configurable) need an approved plan, and with an approved
  plan a write outside its paths is refused until a person approves it. Same decision for Claude Code and Codex.
- **Context pack:** the first turn of a run's writing phase starts with a short pack for its Work item, built on the
  device or runner from the checkout by a script (ast-grep for definitions, calls and imports in ten languages, a
  FastAPI adapter for routes and their dependencies; no model): the symbols the item names, their call sites, the
  routes they serve and the tests that import them. At most 3,000 characters, the same for Claude Code and Codex,
  cached per checkout state, and shown in the job as a "Context pack" card.
- **Responsible person:** everything the platform sends out for an agent (pull requests, comments, tickets, pages,
  channel replies) carries one line naming the agent (with model and run when known) and the person responsible.
- The pipeline runs the repository's declared lint after its tests; a red lint is a red pipeline.
- A confirmation box continues with open high findings only when its definition says so (`on_open_high`).

### Security

- **Private Workspaces:** every read of a Workspace's records leaves out somebody else's private Workspace in one place,
  for platform admins, members of other Workspaces and anonymous callers alike; an ID never shows whether such a
  Workspace exists, and no request body, form or scope can reach it. A session its owner shared stays visible to the
  person it was shared with.
- **Coding-agent gateway content handling:** Claude Code and Codex requests (governed routes, Claude and ChatGPT seats)
  follow the Workspace's content handling like the platform's own model calls: mask, refuse, reroute and report for
  every kind. Prompt injection in the newest turn or its tool results is refused; an older turn the agent re-sends is
  not refused again. The shipped default masks credentials and sends email and internal IPs as they are, recorded.
  Codex's hosted web search is off on seat routes.
- **Secret access audit:** every platform use of a stored secret is recorded (who, which secret, why; never the value).
  Channel bot credentials are stored secrets of the channel now (the upgrade moves them). Logs redact secrets in
  every process.
- A read-only workflow phase refuses a tool no rule names. Workflow confirmation tickets are redeemed at most once.
- Compliance audit records for admins (Operations › Govern › Compliance audit).

### Fixes and smaller changes

- Knowledge retention runs on a schedule for every Workspace with a policy and honours holds.
- The hourly cleanup prunes old code snapshots (newest 100, none older than 7 days).
- Custom detectors no longer match the masker's own placeholders; an invalid detector set answers 422.
- A platform stop waits for the language servers at most once.
- A Workspace gateway policy that sets only some keys (engines, device runs, ...) keeps the baseline's tool rules,
  client permissions and daily budget for the others.
- API: `GET /api/v1/sessions` filters by `project_id`; `POST /api/v1/providers` saves `config_json`; an Action
  created without `task_type` is an `agent_run`; a workflow start in a private Workspace answers
  `private_workspace_has_no_work`.

## 0.0.1-alpha (2026-11-24)

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
- **Removed from the alpha (repository binding):** `POST /api/v1/agent-gateway/sessions/repository` no longer reads
  `name` and `version` (they are ignored); an author labels a repository source with
  `PUT .../knowledge/repositories/{key}/label`.
- **Platform model calls:** the final check also refuses prompt injection and a reroute kind sent off its route; a
  platform instruction is skipped only when it is exactly a shipped seed text; each call and each gateway request
  has one decision record, written when it ends (Cedar's comparison no longer writes its own record for them); the
  record names a mask only where a value was replaced and a report only for a value sent. Governed chat's policy scan
  counts against the call's budget. A released tool result has one record (none when released unchanged with nothing
  to state), and the conversation's badge counts it only after the release.
- **Known limits:** workflows that only read or write text run on the server with your model key; a run that changes
  and tests code needs Claude Code or Codex on your machine, paired with the launcher. The local demo listens on
  `127.0.0.1` only.
