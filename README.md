# Octryx AI

**The layer above your coding agents.** Your developers keep Claude Code (Codex support is experimental).
Octryx AI gives the whole team one process, one set of rules and one record, from an idea in chat to a reviewed pull
request. Open source, self-hosted.

- Website: <https://octryx.ai>
- Documentation: <https://octryx.ai/docs/>
- Benchmark: <https://github.com/octryx-ai/octryx-bench>

## Status: v0.0.1-alpha

Octryx AI is early and changing. Expect rough edges, breaking changes between versions and features that are not
finished; the documentation marks each feature with its real stage. Do not run this alpha with production data or
expose it to the internet. Bug reports are very welcome (see [Contributing](#contributing)).

> **No warranty — use at your own risk.** Octryx is provided "AS IS", without warranties or conditions of any kind. You use it at your own risk and are responsible for its use, including what its agents do in connected systems. To the extent permitted by applicable law, the authors and contributors are not liable for any damages arising from its use (Apache License 2.0, sections 7 and 8). This alpha is not intended for production data or production systems.

## Try it: the local demo

The demo starts Octryx AI on your machine with a Workspace you can click through right away: a small sample app
("Demo Shop") on a local fake GitHub, its docs as Knowledge, a PR review bot and two work items, OCX-1 (a bug) and
OCX-2 (a story). It needs no GitHub, Jira or cloud account, only access to one model.

**A local demo, not for production.** Everything listens on `127.0.0.1` only.

### You need

- Docker Desktop, Rancher Desktop or Podman with `docker compose` 2.23 or newer (`docker compose version`). Give the
  container engine 8 GB of memory and 20 GB of disk.
- Access to one model: an Anthropic API key, an OpenAI-compatible endpoint with a key, or AWS Bedrock.
- Chrome, Edge or Firefox.

### Steps

1. Get the code.

   ```bash
   git clone https://github.com/octryx-ai/octryx.git
   cd octryx
   ```

2. Configure one model. Copy the example and fill in **one** block in `.env`; the active one is Anthropic:

   ```bash
   cp .env.example .env
   ```

   ```bash
   LLM_PROVIDER=anthropic
   AGENT_DEFAULT_MODEL=claude-sonnet-5-5
   LLM_API_KEY=<your key>
   ```

   Nothing else goes into `.env`: the database password, the signing and encryption keys and the object store
   credentials are generated on the first start and stay in Docker volumes.

   The model settings are read only on the first start; after that you change models under **Admin** › **Models**.
   To start over with another block in `.env`, remove the install first with `down -v` (see below), which deletes
   its data.

3. Start Octryx AI with the demo. The first build takes 10 to 20 minutes.

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build
   ```

   The demo is ready when its log shows `demo: ready in the Workspace 'Demo Shop'`, followed by its address:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.demo.yml logs demo
   ```

4. Create your administrator. There is no default password: the first start prints a one-time setup code.

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.demo.yml logs api | grep "setup code"
   ```

   Open <http://localhost:8000/chat/setup>, enter the code, your name, e-mail and a password of at least 12
   characters. From then on you sign in as **admin** with that password.

5. Open the demo. Choose the Workspace with the top icon in the left bar, then **Demo Shop**:
   - **Work** › **Work items**, then **All items**: OCX-1 (a bug: the discount is subtracted as an amount) and OCX-2.
   - **Knowledge** › Search for "rollback" finds the Demo Shop's incident runbook.
   - The demo repository can be cloned on your machine: `git clone http://127.0.0.1:8434/demo/demo-shop.git`.

### Three ways to try the demo

Workflows that only read or write text run on the Octryx AI server with the model key from `.env`. A run that
changes and tests code needs **Claude Code (or Codex, where the Workspace allows it) on your machine, paired with the
launcher**; the Octryx AI server does not build or test code.

1. **Without Claude Code.** Open OCX-1 and choose **Start workflow**. **Bug fix with a reproduction test** and
   **Story / epic delivery** build and test code, so they do not start on the server: the form says so and how to
   pair Claude Code. **Spec writing** is allowed on the server, but it is made for an epic (it interviews you, writes
   a specification for your approval and splits it into stories), not for a small item like these two. To see what
   a full run looks like without a device, open the sample run (3).
2. **With Claude Code paired.** Pair it first: **Agents** › **Install octryx-claude** (see the
   [documentation](https://octryx.ai/docs/)). Then open OCX-1, choose **Start workflow** and pick
   **Bug fix with a reproduction test**. The agent reproduces the bug in the Demo Shop, fixes it, runs its tests and
   opens a pull request on the local fake GitHub; the review bot then reviews it.
3. **See a finished run.** **Work** › **Runs** shows a **Story / epic delivery** run of OCX-2 with the badge
   **Sample run**, its pull request and the bot's review on the fake GitHub. The review bot asks for changes: the new
   tests lock in the discount bug of OCX-1, which the demo leaves open. A new Story / epic delivery on OCX-2 continues
   on that run's branch and pull request.

Port 8000 or 8434 taken? Set `OCTRYX_PORT` and `OCTRYX_DEMO_GIT_PORT` in `.env` before step 3.

To stop: `docker compose -f docker-compose.yml -f docker-compose.demo.yml down`. To start over and delete everything
(database, documents, generated keys): add `-v`.

Back up and restore an install (database, generated keys, documents):
[back up and restore](https://octryx.ai/docs/install/upgrade#back-up-and-restore).

More: [`deployment/demo/README.md`](deployment/demo/README.md) for the demo. An install without the demo, on
Kubernetes, upgrades with backup and restore, and common problems are in the documentation:
[Docker](https://octryx.ai/docs/install/docker), [Kubernetes](https://octryx.ai/docs/install/kubernetes),
[upgrade](https://octryx.ai/docs/install/upgrade), [troubleshooting](https://octryx.ai/docs/start/troubleshooting).

## Run a coding agent through Octryx AI

Octryx AI does not replace your coding agent. With the launcher, a developer's Claude Code (or Codex) runs its turns
under the team's rules and shows up in the same record: see [the documentation](https://octryx.ai/docs/).

## Sensitive content handling

Octryx AI examines what goes to a model for sensitive content and acts on it per content kind: credentials,
credential assignments, email addresses, internal IP addresses, IBANs and phone numbers.

**Threat model of the gateway.** The gateway filter protects against ACCIDENTAL leakage by the user's own coding agent
(Claude Code / Codex) and against prompt injection arriving in tool results. It does not defend against a
deliberately evasive client (the client is the user's own program; it can send anything to any provider directly).
Consequences: no protocol-shape validation beyond JSON parsing; opaque binary/provider-state fields are skipped by an
exact key list without content validation; caller-supplied names/types are not verified.

**Defaults** (a fresh install, and every Workspace that changes nothing):

- model calls of the platform (chat, tasks, governed runs, tool results): credentials and email addresses are
  masked, internal IP addresses are reported, IBANs and phone numbers are not acted on;
- requests of an external coding agent (Claude Code, Codex) on the gateway: credentials are refused, credential
  assignments are reported, nothing else is acted on;
- Command safety sends a command with credentials or internal IP addresses for review.

**The five actions** a Workspace admin can choose per kind (Agents → Governance → Policy) for the platform's own
model calls:

- `refuse` — the request is not sent (`content_policy_denied`);
- `mask` — the value is replaced by a numbered placeholder before it is sent;
- `reroute` — the request goes to the Workspace's governance alias;
- `mask_reroute` — masked, and sent to the governance alias;
- `report` — the text is sent unchanged; the finding is recorded as an informational decision.

**The governance alias** is one setting per Workspace, beside the per-kind actions: the single governed model alias
(an alias of an active model gateway) every `reroute` and `mask_reroute` kind is sent to. A kind can be set to reroute
only while the Workspace has one (`content_handling_alias_required`); it cannot be cleared while a kind still reroutes
(409 `content_handling_alias_in_use`, naming the kinds), only replaced by another governed alias. Kinds carry no alias
of their own. Every change of an action or of the alias is audited (`content_handling.changed`).

A model reply goes back to the user, not to another model: there `reroute` and `mask_reroute` mask instead. The
call's decision record is request-side: it says, for the request sent, which action was requested and which was
applied. The reply adds no per-kind entries; a refused reply only sets `reply_refused: true` on that same record.
Where no reroute applies (a direct
provider driver, commands), `reroute` and `mask_reroute` are refused with `content_route_unavailable`. The admin page
shows, for each kind, what the chosen action does at every place before you save; on the gateway it shows "platform
calls only" for every kind but credentials and credential assignments, and for `mask` and the reroutes.

**On the gateway of external coding agents** (the Anthropic route and Claude Code seat, the `/openai` Responses route
and the Codex seat) a request is forwarded unchanged or refused. A governed call's final payload — the model replaced
by the alias' model group and, on the Responses route, the effective output cap — is built before the scan; a seat
call sends the client's body as it arrived. The bytes sent are exactly the serialization of the payload the gateway
scanned: there is no separate final check on the gateway.

- The scan is the whole JSON payload as one text, minus the values under the opaque key list below, plus the
  structured credential assignments of its parsed keys and values: a field whose name ends in a credential name
  (`password`, `db_password`, `access_token`, `client-secret`, …) assigning a literal value — in tool arguments,
  tool results and prompt data, a string that is itself serialized JSON included, the opaque list honored — is a
  `credential_assignment` finding, classified the same way for `refuse` and `report`.
- Only `secrets` (credentials) and `credential_assignment` act there: credentials are refused by default, credential
  assignments reported by default (the request is forwarded and the finding recorded); a Workspace may set `refuse`
  or `report` for either. Every other kind, and `mask`, `reroute` and `mask_reroute`, apply to platform calls only
  (on the gateway such a setting leaves the kind at its default: a credential set to `mask` stays refused there).
- Prompt injection is checked only inside tool results — Anthropic `tool_result` blocks, Responses
  `function_call_output` and `*_call_output` items — each read as one text: found there, the request is refused
  (`content_policy_denied`). It is not checked in tool definitions, the user's, the assistant's or the client's system
  text, citations or search items.
- A body that is not valid JSON (a repeated key, a nesting deeper than 64, a non-finite number — a `NaN`/`Infinity`
  literal or a number beyond the float range —, invalid UTF-8) is refused with `request_body_invalid` (400), a body
  over 16 MiB with `request_body_too_large` (413), and a request that cannot be checked before its deadline (10 s
  from the moment the handler is entered, the body read included) with `content_scan_unfinished` (400). Nothing
  unfinished is remembered: the next request is examined again.
- The Workspace's custom content policies (Cedar) are asked over the whole body's findings. A policy that blocks
  refuses with `content_policy_denied`; one whose obligation asks to mask or reroute refuses with
  `content_handling_gateway_refused` (the gateway changes nothing); in shadow mode the request is sent and what the
  policy would have done is recorded.
- **Decision records.** A content decision record is written once, when the request ends, from its actual final
  outcome, for every request refused for a content reason (an unreadable, oversized or late body, a fixed rule, the
  content handling, a tool-result policy, Cedar: `refused` with the reason and the stage — `body`, `content`,
  `tool_result_policy`, `cedar`) and for every request with acted-on or reported findings. It never claims an action
  that was not applied: a request with findings that was sent is `forwarded` (`applied: report`), also when the
  upstream answered with a non-success status (`upstream_status`: the body crossed the transport, so it is never
  `refused`); one with findings that was not sent for another reason — a budget, an undelivered send, a cancellation
  or failure — is `not_sent` with that reason and stage (`applied: none`). A request is sent the moment the
  upstream's response headers arrive, before any error body is read. A tool-result injection refusal states the
  injection's count and source (`prompt_injection`). A refusal for a non-content reason (run
  limits, admission, budget or cost, authentication, a model denial, loop protection) with nothing found, and a clean
  forward, write no content record. The refusal and the report notice (`x-octryx-obligation`, on every returned
  answer, an upstream error and the token count's included) name the record and say what to do next: remove the affected message or start a new conversation (Claude
  Code: `/rewind` or `/clear`; Codex: start a new session). A credential refusal names the kind of credential on the
  run's timeline. The Agents badge counts what the newest turn carries.
- **Deadline.** The request's deadline (10 s from handler entry) bounds the content examination: from entry to the
  last scan, the structured fields and the bytes to send; the clock is read once after all of it, and a passed
  deadline is the fixed unfinished refusal before any finding reaches Cedar or a record. Admission, budget and commit steps after a finished examination are not content work and are not bounded
  by it.

**The opaque key list** — the only values not read, by key, wherever they are, without validating their content
(`content_detection/request_text.py`, the same list on the gateway and on the platform's own calls):

| Key | Skipped when |
|---|---|
| `signature` | its value is a string (a thinking block's signed state) |
| `encrypted_content` | its value is a string (encrypted reasoning, compaction or web-search state) |
| `data` | its value is a string in an object whose `type` is `base64` (a media source) or `redacted_thinking` |
| `image_url`, `url`, `file_data` | its value is a `data:` URL (an inline image or file) |

**On the platform's own model calls** every provider-bound field is examined once within one budget for the whole
call (size, number of parts, a deadline from the call's entry to the last scan, the final check's serialization
included — its cap counts the full serialized bytes, opaque values included; the clock is read once more after all
content work, and a deadline passed during the examination is the fixed unfinished refusal); the custom content policies' scans of a governed call — an obligation's masking pass included — are
charged to the same budget, and once it is spent the call is refused unfinished (`content_scan_unfinished`, a notice
without counts) before any later decision (a target, a second question). A kind set to `refuse` refuses new content (the
newest turn, system text, message fields) and newly offered tool definitions; found in older history or in a
replayed tool call it is masked instead (that text was checked when it was new). Prompt injection is refused in every
field sent to the model — the newest user text included; an administrator-authored agent role ("Act as …") is the
one phrasing not refused there. A platform instruction is sent unchecked only when its text is exactly a shipped seed
text (by content hash); an edited or Workspace-authored instruction is checked like authored text. A request of the
platform whose structure cannot be read (messages that are not a list of objects, a nesting deeper than 64, text
that is not valid Unicode, a role that is not a string, an unknown block) is refused with `content_unreadable` before
anything copies or hashes it, never an error.

**The final check of the platform's own calls:** right before a provider driver sends, the final request object it
hands to its transport or SDK (Bedrock's SDK serializes the checked object itself) is read once more as one JSON
text, minus the opaque key list, with the same structured credential classification as the gateway (a field whose
name ends in a credential name, in objects and in embedded JSON text); it never rewrites text. The only text not
read is a field that is exactly a shipped seed text (by content hash). By field identity, prompt injection is not
evaluated in a system carrier of the driver's request (the top-level `system` or `systemInstruction`, and a message
of the top-level `messages` or `input` list whose `role` is the string `system` or `developer`) whose value is
exactly an authored system text of the call or exactly the driver's join of the call's system texts (the join's other
system texts are evaluated on their own); nothing else — tool definitions and tool data included — is looked at for a
role, the same text in any other field or inside a longer value is evaluated, and every other detector reads the
authored field whole. If prompt injection or a kind whose action must keep it out (`refuse`, `mask`, `mask_reroute`)
is still there, a rerouting kind is there while the call is not going to the Workspace's governance alias, or the
call ran out of its budget, it is refused and nothing is sent. Right before the send, after the custom content
policies, a call a rerouting kind sent to the governance alias must still be going there: a mismatch is refused
(`content_route_unavailable`).

**The record of a platform call** is request-side only and written once, after the request was handed to the
transport, from the final check's reading of the sent bytes: a kind present in them is recorded with its applied
action (`report`, or `reroute`), a kind the completed examination of the input found and the sent bytes do not carry
is recorded `mask`; a report first seen in the sent bytes is included, and a report this process already recorded for
the same text is named (`reported_before`, the earlier record keeps counting it) whatever happened after the send. A
refused call is recorded `refuse` (Cedar and the final check included); a call neither refused nor sent (the driver
failed or the call was cancelled before the hand-off) has no record. The reply is masked or refused as configured but
leaves no per-kind evidence: a refused reply only sets `reply_refused: true` on the call's record; a reply part whose
examination does not finish is withheld. The governed conversation's badge is counted after the record.

**Tool results:** each released tool result has at most one decision record, written once from what was actually
released (unchanged, masked, blocked, or kept by a coding agent's client that cannot take a masked output); a result
released unchanged with nothing to state has none. Each kind's `applied` is read from the released result:
`report` only for a reported kind it carries, `mask` only for a kind found and absent from it (a Workspace policy's
mask), else `none` (it applies where the result next reaches a model); `informational` lists the kinds applied as
`report`; a blocked result is `refuse`, an unfinished examination the fixed record without findings. The record is
written when the check returns the result to its caller; a check that fails or is cancelled before writes nothing. A result the
client keeps (a built-in tool) is released as it came, with nothing claimed as blocked, masked or withheld — the
launcher's notice says the output stays and the gateway checks it; a Workspace policy's part is stated only for a
released result, and so is a withheld count. The conversation's badge counts only what entered the context, after
the record.

**What stays fixed:** text the detectors could not finish examining is withheld from a platform call (on the gateway:
the request is refused), content of an unknown shape in a platform call is refused, and prompt injection is refused
(on the gateway: in tool results). No setting changes these.

**Who can change it:** Workspace admins and owners, and platform admins. Members see the effective action per kind
and whether it is the default. Every change is written to the audit log (`content_handling.changed`).

## Known limitations

v0.0.1-alpha ships with these known limitations. Each one is planned for 0.0.2.

### Sensitive content handling
- **Threat model.** The coding-agent gateway protects against accidental leakage by your own coding agent and against prompt injection that arrives in tool results. It does not defend against a deliberately evasive client: Claude Code and Codex are your own programs and can reach any provider directly.
- **The gateway forwards a request unchanged or refuses it.** Masking and rerouting apply only to the platform's own model calls. On the gateway, a kind set to mask, reroute or mask-and-reroute keeps its gateway default (credentials refused, credential assignments reported, other kinds not acted on); only a custom content policy that asks to mask or reroute refuses the request (`content_handling_gateway_refused`).
- **Opaque fields are skipped by key name, without validation.** These are provider signed state and inline media data (see the opaque key list above).
- **Prompt injection on the gateway** is checked only inside tool results. It is not checked in your own text, in the assistant's text, in the client's system prompt or in tool metadata.
- **Report de-duplication covers only the platform's own model calls and is kept in memory.** A platform call does not report a text again that an earlier record of the same process and scope already reported. After a restart that text is reported once more, and a report first found by the final check of the sent bytes is not de-duplicated. The gateway writes a record for every forwarded request with a reported finding.
### Secure Work
- **Pull requests are recorded internally.** A workflow run records the pull request it opens, and its PR merge/decline wait requests a refresh of that record. The refresh worker reads GitHub and Bitbucket pull requests only, and only while the repository's connection still serves the host the pull request was recorded on (otherwise `host_mismatch`). GitLab run watches use their own poll and webhook path. There is no pull-request page and no manual sync or refresh. The pull-request reviewer routes were removed; Work Item reviewer recommendations and overrides remain.
- **A Work Item and an intake keep the Workspace they were created in.** A change of Workspace is refused (`409 workspace_immutable`).
- **There is no design-delivery pull-request traceability sync.** Release and checkpoint trace syncs remain.

## Repository layout

| Path | What |
|---|---|
| `backend/` | the platform: API, agents, workflows, Knowledge (Python, FastAPI) |
| `frontend/chat/` | the web app (React, TypeScript) |
| `clients/` | the launcher and other clients |
| `deployment/` | Helm chart and the local demo |
| `docker-compose.yml` | a local install; `docker-compose.demo.yml` adds the demo |
| `scripts/` | development and release helpers |
| `plugins/` | example plugins (release notes) |
| `bots/teams/` | the Microsoft Teams bot with calls |
| `docker/` | image build helpers |

How the parts fit together: [architecture](https://octryx.ai/docs/concepts/architecture); the HTTP API:
[API overview](https://octryx.ai/docs/admin/api).

## Contributing

Issues and pull requests are welcome; please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

## Reporting a vulnerability

Report security problems **privately**, through GitHub's private vulnerability reporting: open the repository on
GitHub, go to **Security › Report a vulnerability** and describe what is affected, how to reproduce it and what an
attacker could do. Never open a public issue for a security problem. We confirm a report within a few working days
and credit you in the release notes if you wish. Only the latest alpha receives fixes. The local demo listens on
`127.0.0.1` only; running it exposed to a network is out of scope.

## Code of Conduct

Everyone taking part follows the [Contributor Covenant 2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).
Unacceptable behaviour can be reported to the maintainers through a private report in the repository
(**Security › Report a vulnerability**) or a message to a maintainer on GitHub; every complaint is reviewed promptly
and fairly, and the reporter's privacy is respected.

## Licence

> **No warranty — use at your own risk.** Octryx is provided "AS IS", without warranties or conditions of any kind. You use it at your own risk and are responsible for its use, including what its agents do in connected systems. To the extent permitted by applicable law, the authors and contributors are not liable for any damages arising from its use (Apache License 2.0, sections 7 and 8). This alpha is not intended for production data or production systems.

[Apache License 2.0](LICENSE).
