# octryx-claude

Runs Claude Code through Octryx, one session at a time. Only sessions started by
this launcher use the platform's model gateway, its Workspace policy and its hooks.
Plain `claude` stays untouched: the kit writes nothing to `~/.claude` and installs no
managed settings.

## Use

```bash
# once: sign in with your browser (authorization code + PKCE; the CLI never sees a password)
clients/octryx-claude/bin/octryx-claude login --base-url https://octryx.example --workspace <id or name>

# every session (arguments after -- go to claude)
clients/octryx-claude/bin/octryx-claude [--profile auto|governed|seat] [--workspace ID|NAME] [--work-item KEY] [--no-code-intelligence] [-- <claude args>]

clients/octryx-claude/bin/octryx-claude status   # base URL, Workspace "name (id)", login state, status block (no tokens)

# your own Claude subscription for the seat profile (no platform login needed; alias: seat-login)
clients/octryx-claude/bin/octryx-claude login --seat
```

`--workspace` takes a Workspace id or its name (`--workspace "Demo Shop"`; case-insensitive, exact). The name is
looked up among the Workspaces your login may use; an unknown name lists them, and a name that two Workspaces
share asks for the id.

`--work-item KEY` attaches the session to that Work item's active workflow run at start (if you are its requester,
the Work item owner or an admin) and prints the run banner: workflow, phase, loop i/n and what the run waits for.
Without an active run, your first prompt gets a workflow proposal; a change or phased workflow starts only after you
confirm it. When the run waits for **your** decision (a confirmation, a question, a paused loop), you can tell the
agent your answer and confirm it in Claude Code's permission prompt, which shows the exact payload — or decide in
Octryx. Approvals by another person (four-eyes) are decided only in Octryx.

`--profile auto` is the default: the session uses `seat` (your own Claude subscription) when the Workspace allows
seat and your seat login works, and `governed` otherwise. The choice is made once at start and never changes during
the session. The seat login is detected without reading any credential: Claude Code's credential file in
`claude-config-seat/`, or a marker the launcher writes after `login --seat` or a seat session that ended normally
(on macOS Claude Code keeps the login in the Keychain). A login that was rejected, or a subscription limit reached in
the last 5 hours, also means `governed` (see "Seat status" below). `--profile seat` and `--profile governed` force
the profile.

Every start prints a status block on stderr before Claude Code starts (`status` prints the same block for the next
session):

```text
octryx-claude: Workspace Demo Shop (ws-1)
octryx-claude:   seat (your Claude subscription): ready
octryx-claude:   governed (company model):        ready
octryx-claude:   seat allowance:                  5h 42% · 7d 13% (as of 11:58)
octryx-claude:   daily budget:                    3.25 / 50.00 USD today (resets 02:00)
octryx-claude:   → this session: seat, model claude-opus-5-5 (auto: Workspace allows seat and the seat login is present)
octryx-claude:   seat login: octryx-claude login --seat
```

`seat` reads `ready`, `not logged in`, `not allowed by the Workspace (<reason>)`, `login expired (rejected at
HH:MM)`, `limit reached (at HH:MM; counts for 5h)` or `unknown (client policy unavailable)`; `governed` reads
`ready`, `not set up (client policy <state>/<reason>)` (then nothing starts), or `needs_configuration: no Claude model admitted and seat not allowed` with what an admin does about it (the platform admits no company model and the Workspace refuses seat, so a session has nothing to run on). The model is the `main` alias, or
`--model` passed to Claude Code. The Workspace is `name (id)`: the stored name, else the name from the Workspace
list the launcher reads with its login (the id alone when neither knows it).

`seat allowance` and `daily budget` come from `GET /api/v1/agent-gateway/daily-budget?workspace_id=` (the user's
own data, read with the launcher's login): the latest 5h/7d utilization Anthropic reported on one of your seat
sessions (`not reported yet` before the first seat turn; `reset since` once a window's reset time has passed;
hidden when the Workspace forbids seat), and your gateway spend of the UTC day against the Workspace's
`session_budget.per_user_daily_usd` (`not configured (<reason>)`, `used up (<reason>)`, or `unavailable (<code>)`
when the platform cannot answer). Times are local.

`login --seat` runs Claude Code's own `claude auth login --claudeai` with `CLAUDE_CONFIG_DIR=claude-config-seat/`
and without any `ANTHROPIC_*` variable, so the subscription login lands in the seat profile only; then it writes
the seat marker. In `--profile auto`, when the Workspace allows seat but the seat login is missing or was
rejected, an interactive start asks once per state: `Seat (your Claude subscription) is not logged in. Log in now?
[y/N]`. A non-interactive start (no terminal, or `-p`) only shows the hint and continues governed.

The shim runs `backend/.venv/bin/python` of the same checkout; set `OCTRYX_PYTHON` to
another Python with `httpx` otherwise (a git worktree has no venv of its own).
`login --headless` is for automated acceptance on dev instances only: it signs in with
`OCTRYX_USERNAME` / `OCTRYX_PASSWORD` from the environment and approves the consent over HTTP.

Commands Claude Code runs itself: `api-key-helper`, `mcp-headers`,
`hook pre-tool-use|post-tool-use|stop|stop-failure|session-end|user-prompt-submit`.

## Install without the repository

The platform serves the installers with its own URL filled in (public routes, nothing secret; Admin → Agents →
"Install octryx-claude" shows the lines with the selected Workspace preselected).

Governed sessions need a **Claude** model on the platform: an Anthropic key, or Bedrock with a Claude model. With
only an OpenAI-compatible model, `status` lists no company model and a governed session has nothing to run on. The
other way is the seat profile (each member's own Claude subscription), which an admin allows per Workspace.

A second installation on the same Mac (another HOME or `OCTRYX_CLAUDE_HOME`) gets its own launchd labels
(`ai.octryx.claude.pet.<hash>`), so it never stops the first installation's pet or device service.

```bash
# macOS, Linux, WSL2 (bash 3.2+; needs curl and Python >= 3.11 or uv)
curl -fsSL 'https://octryx.example/octryx-claude/install.sh?workspace=<id>' | bash
curl -fsSL 'https://octryx.example/octryx-claude/install.sh' | bash -s -- update
curl -fsSL 'https://octryx.example/octryx-claude/install.sh' | bash -s -- uninstall [--purge]
# offline: bash ~/.octryx/claude/installer/install.sh uninstall
```

```powershell
# Windows PowerShell 5.1 or 7, no admin rights (WSL2 must exist: once, as administrator, `wsl --install`)
irm 'https://octryx.example/octryx-claude/install.ps1?workspace=<id>' | iex
& ([scriptblock]::Create((irm 'https://octryx.example/octryx-claude/install.ps1'))) uninstall -Purge
```

What `install.sh` does: checks for `claude` (prints the official install command when it is missing, never installs
it), fetches `GET /octryx-claude/version`, downloads `GET /octryx-claude/package/<version>` and refuses it unless its
sha256 matches, creates `venvs/<version>` (uv when present, else `python3 -m venv` + pip; pip/uv fetch the pinned
`httpx` from the configured index, so `PIP_INDEX_URL`/`UV_INDEX_URL` work for a mirror; no package cache is
written into the home directory), points `venvs/current` at
it, keeps the previous version (a running session keeps calling the version it started with) and removes older
ones, writes the shim `~/.local/bin/octryx-claude` and one PATH line into the login shell's rc file, stores the
platform with `octryx-claude configure --base-url <platform> [--workspace <id or name>]` (no sign-in, no secret; a
later plain `octryx-claude login` uses it and selects that Workspace), then runs
`login --base-url <platform> [--workspace <id>]` (skip with `--no-login`) and `status`. A foreign
`~/.local/bin/octryx-claude` is never overwritten, and a state directory that resolves (after `..`, `.` and
symlinks) to `~/.claude*` is refused. The state directory is created only after the package downloaded and its
checksum matched. A Python without the `venv`/`ensurepip` module (a fresh Debian/Ubuntu/WSL Ubuntu) is refused with
`sudo apt install python3-venv` (or uv) as the fix. `uninstall`
removes package, shim and PATH line and keeps login and settings; `--purge` also revokes the login at the platform
(`python -m octryx_claude.logout`) and deletes the state directory. Directories the installer created
(`~/.local/bin`, `~/.local`, `~/.octryx`) are recorded in `installer-created-dirs` and removed by `uninstall`
once they are empty; pre-existing or non-empty ones stay (a kept one stays recorded). `install.ps1` does the same for
its `%LOCALAPPDATA%\Octryx\octryx-claude\bin`.

### The Octryx pet (macOS)

On macOS the installer also installs the `pet` extra (`octryx-claude[pet]`: pystray, Pillow, pyobjc), the tray icon
that shows what needs you (`GET /api/v1/agent-gateway/pet`). It is a separate step after the launcher: when it fails
(no package index, no wheel) the installer says so and the launcher works without it. `--no-pet` leaves it out and is
recorded in `<state>/no-pet`; `--pet` brings it back. `install.sh update` and the self-update on start keep that
choice. The icon does not start by itself: `octryx-claude pet enable` shows it now and at every login (a LaunchAgent,
`ai.octryx.claude.pet`, with a suffix for a second installation); `uninstall` removes that login item. Quiet hours: none by default,
`octryx-claude pet quiet 19:00-08:00` (local time). Linux gets no pet.

### The Octryx pet on Windows

octryx-claude runs in WSL2, but a tray icon needs native Windows, so `install.ps1` builds a second, native venv
(`%LOCALAPPDATA%\Octryx\octryx-claude\pet\venv`, `octryx-claude[pet]` from the same verified wheel) when
Windows has a Python >= 3.11 (py launcher, `python.exe` but not the Store stub, or uv); otherwise it names
`winget install Python.Python.3.12` and goes on. `-NoPet` leaves it out. The pet borrows the gateway token from the
WSL login (`wsl.exe -d <distro> -e <home>/.local/bin/octryx-claude api-key-helper`, no console window), keeps it in
memory for ten minutes or until a 401, and stores nothing secret: `pet\account.json` holds the platform URL, the
distribution and the WSL home. `octryx-pet enable` (the shim calls `python -m octryx_claude.pet`) sets
`HKCU\...\Run\OctryxPet` to `pythonw.exe -m octryx_claude.pet run` and starts it; `install.ps1 update` rebuilds the
venv when the version changed (a running pet is stopped and started again); `uninstall` removes venv, shim and Run
value (`-Purge` also the pet settings). Inside WSL, `octryx-claude pet run|enable` points at `octryx-pet`.

The package is a wheel the platform builds deterministically from this directory (`backend/app/services/
octryx_client/artifact.py`): version `__version__+<source hash>`, so every source change is a new version, plus the
two `backend/scripts` files the transcript digest uses.

**Self-update on start.** An installed copy updates itself, so a deploy with changed client code reaches every
machine at its next start, without running the `curl` line again. Every person-facing start (a session, `status`,
`device run`, …; never the commands Claude Code runs itself) asks the configured platform for `GET
/octryx-claude/version` (2 s timeout; the answer is cached for 60 s in `.self-update.json`). When the served version
differs from the installed one it does what `install.sh` does: downloads the package, refuses it unless its sha256
matches the published one, builds `venvs/<version>` (uv when present, else the venv's base Python with `venv` + pip,
`OCTRYX_INSTALL_PYTHON` honoured, no package cache), checks that the new venv reports that version, switches
`venvs/current` atomically, keeps the previous venv (running sessions keep calling it; rollback) and removes older
ones. Then it prints `octryx-claude updated <old> -> <new>` and re-executes the command through the shim with the
same arguments. Offline, refused, a malformed answer, a checksum mismatch or a failed build: one warning line and the
command runs on the installed version; a failed version is tried again after an hour at the earliest, and a start
while another one is updating just runs the installed version. The re-executed process carries
`OCTRYX_CLAUDE_UPDATED_TO` and never checks again (no loop). The source is only the configured base URL; nothing
under `~/.claude*` is touched; a repository checkout never updates. Opt out with `OCTRYX_CLAUDE_AUTO_UPDATE=0`: then
an installed copy only prints the update command once a day when the platform serves another version.

The device service (`device run`) updates at its start like every command and checks again every five minutes while
no job runs. When a new version is active it waits until no job runs (a running job is never interrupted; an offer
arriving while it stops is rejected with `device_updating`), stops cleanly and re-executes `device run` on the new version
in the same process, so launchd, systemd and the WSL logon task need no restart policy. Should that re-exec fail it
exits with 75, which the launchd `KeepAlive.SuccessfulExit=false` and systemd `Restart=on-failure` units restart.

Windows: governed sessions need Claude Code's Bash sandbox (`sandbox.failIfUnavailable`), which runs on macOS, Linux
and WSL2 but not on native Windows, where Claude Code would exit at startup. So `install.ps1` runs `install.sh` inside
the default (or `-Distribution`) WSL2 distribution and adds `%LOCALAPPDATA%\Octryx\octryx-claude\bin\
octryx-claude.cmd` (forwards to `wsl.exe -d <distro> -e ~/.local/bin/octryx-claude`) to the user PATH. Claude Code must
be installed inside WSL. The launcher itself refuses native Windows (`needs_configuration:
native_windows_unsupported`), and the AF_UNIX hook signer works unchanged in WSL2.

Secrets stay in `credentials.json` (0600) inside the state directory rather than the macOS Keychain or the Windows
Credential Manager: the enforced boundary is Claude Code's sandbox `denyRead` on that directory, which keeps the
agent's own commands away from it; an item the `security` CLI creates is readable by any process that runs `security`
as the user, which the sandbox does not demonstrably block, and WSL has no credential store. Outside the sandbox the
refresh token is readable by any process running as the same user; `uninstall --purge`
revokes it at the platform.

What the checksum does and does not protect: the installer compares the wheel with the sha256 the same platform
publishes over the same connection, so it catches a corrupted or truncated download, not a compromised platform or
connection. Trust in the platform is TLS (serve it over `https`; the scripts carry the configured
`OCTRYX_PUBLIC_ORIGIN`, else the request origin whose scheme a proxy named in `TRUSTED_PROXY_IPS` may raise).
`httpx` is pinned; its transitive dependencies (`httpcore`, `h11`, `anyio`, `idna`, `certifi`, …) are resolved from
the package index at install time and are not hash-pinned.

## State

`~/.octryx/claude/` (0700, override with `OCTRYX_CLAUDE_HOME`):

| Path | Content |
|---|---|
| `config.json` | `base_url`, `workspace_id` (`workspace_request` until the next login resolves it), optional `work_item`, optional `aliases` (`main`, `opus`, `small_fast`; defaults `claude-opus-5-5`, `claude-opus-5-5`, `claude-sonnet-5`) |
| `credentials.json` (0600) | OAuth `client_id`, loopback `redirect_uri`, rotating `refresh_token`, cached access tokens per audience |
| `credentials.lock` | Serializes refreshes. Refresh tokens rotate, and replaying a rotated token revokes the whole grant |
| `claude-config/` | `CLAUDE_CONFIG_DIR` for octryx sessions only (`governed` profile) |
| `claude-config-seat/` | `CLAUDE_CONFIG_DIR` of the `seat` profile: your own Claude subscription login lives here only |
| `.seat-session-ok`, `.seat-problem.json`, `.seat-login-declined` | Seat markers: the seat login worked; the last rejected login or reached limit (fixed codes and a time); the state you declined the login offer for |
| `venvs/<version>/`, `venvs/current`, `installed-version`, `installer/install.sh`, `installer-created-dirs` | Installed copies only: the package venvs, the active version, the installer copy for an offline uninstall and the directories the installer created |
| `.self-update.json` | Installed copies only: the platform's last release answer (60 s cache) and the last version that failed to install |
| `.update-check` | Installed copies with `OCTRYX_CLAUDE_AUTO_UPDATE=0` only: when the update notice last asked the platform |
| `sessions/<key>/` | Generated `settings.json`, `mcp.json`, the stop-hook counter and, while the session runs, the hook signer socket `hook.sock` (0600) |

## Profiles

- **`governed`** (default): model traffic goes through the platform's governed data plane (LiteLLM, the
  Workspace's model policy, the per-user daily budget).
- **`seat`**: Claude Code uses **your own Claude subscription** (Team/Enterprise seat) and its allowance.
  Model calls still go through the Octryx gateway, which applies the Workspace's seat policy,
  the model allowlist (`seat_models`), the secret scan and the transcript, then forwards them to
  Anthropic with your own `Authorization` header, unchanged. The gateway never stores, logs or audits
  that token. It reads the allowance from Anthropic's rate-limit headers, so Workspace admins see each
  seat's 5-hour and weekly use in "Agents".
  - The Workspace decides: without a stored `agent_gateway_policy.seat_mode`, the seat is allowed for a
    Workspace with `public` or `internal` data and off from `confidential` up. A data
    classification at or above `confidential`, an unresolved classification, or
    `requires_governed_routing: true` forbids it too. The launcher checks this up front and refuses with
    the fixed reason; there is no silent fallback to `governed`.
  - Sign in with `octryx-claude login --seat` (or `/login` inside a seat session). That login lives in
    `claude-config-seat/` only. Your plain `claude` login (its own keychain entry) is never read,
    copied or changed.
  - **Seat credential.** At launch the launcher registers the session (`POST
    /api/v1/agent-gateway/sessions/register`) and receives a random, session-bound credential (256 bit,
    stored on the platform only as a hash). Claude Code sends it as `X-Octryx-Seat-Credential`
    (in `ANTHROPIC_CUSTOM_HEADERS`). It works only on the seat model route, ends at finalize, and expires
    after 12 h (`seat_session_expired`: start a new session).
  - **Residual risk (accepted):** the agent's Bash can read the child environment, so it can read the seat
    credential. The credential is useless without your own subscription login, spends no platform budget,
    and is bound to this one session. A launcher-local auth proxy that keeps it out of the environment is
    a possible later hardening.

## Company models in `/model`

`/model` lists the models the Workspace admits for this session, after Claude Code's own lineup:

- **`governed`**: every company model (Octryx alias) that the Workspace's model policy, its data
  classification, the Cedar `call_model` policies and the alias catalog admit for tool use. Each row reads
  "Company model through Octryx, billed to the Workspace budget".
- **`seat`**: your subscription models (`seat_models`). If the Workspace sets
  `agent_gateway_policy.seat_allows_governed_models: true` (default `false`), the list also has the company
  models, as `company/<alias>` labelled "<name> (company)". Choosing one sends that call through the governed
  path: the same daily and platform budget, model policy, secret scan and audit as a `governed` session.
  It is billed to the Workspace, not to your subscription, and your subscription login is never sent with it.
  Without the opt-in the gateway refuses `company/...` with `seat_governed_models_not_allowed`.

The status block names them before Claude Code starts, for example:

```text
octryx-claude:   company models (/model):         company/example-model (billed to the Workspace budget)
```

How it gets there:

- The client policy carries the rows per profile (`models.governed`, `models.seat`). The launcher writes them
  as `modelPicker` into the session's own `settings.json`. It never writes `~/.claude*`.
- The `governed` profile also sets `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`. At startup Claude Code then
  reads `GET <base>/api/v1/model-gateway/anthropic/v1/models` with the `apiKeyHelper` credential.
  Claude Code keeps only ids that contain `claude` or `anthropic`, so `modelPicker` stays the authoritative
  list.
- The `seat` profile sets discovery to `0`, because a subscription login is not a credential that discovery
  sends. The seat route also serves `GET .../anthropic/seat/v1/models` for clients that do ask.
- A model the Workspace does not admit is refused before dispatch with a fixed reason and the hint "Run /model
  to see the models it offers."

## What a launch does

1. It requires a login and a Workspace, then calls `GET /api/v1/agent-gateway/client-policy`
   with the session headers. The session starts only when the policy state is `allowed` (and, for
   `--profile seat`, when its `seat.seat_mode` is `allowed`). Then it registers the session
   (`POST /api/v1/agent-gateway/sessions/register` with the profile, git branch, client and version),
   which also makes it visible on the Workspace's "Agents" view from the first second.
2. It generates a session key (uuid4). The key is used as `X-Octryx-Session` and as
   Claude's own `--session-id`, so one id identifies the session end to end.
3. It writes `settings.json` for `--settings`:
   - `apiKeyHelper`: `octryx-claude api-key-helper` (`governed` only; in `seat` mode the subscription
     login owns `Authorization`, and the base URL is `.../anthropic/seat` plus the seat credential header).
   - `env`: `ANTHROPIC_BASE_URL=<base>/api/v1/model-gateway/anthropic`,
     `ANTHROPIC_CUSTOM_HEADERS` (session, Workspace and optional work item headers), the
     model aliases (`ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` and
     `CLAUDE_CODE_SUBAGENT_MODEL` get `main`, `ANTHROPIC_DEFAULT_OPUS_MODEL` gets `opus`,
     `ANTHROPIC_DEFAULT_HAIKU_MODEL` and `ANTHROPIC_SMALL_FAST_MODEL` get `small_fast`; only Sonnet
     and Opus are admitted, so Sonnet also serves the small/fast calls), `CLAUDE_CODE_API_KEY_HELPER_TTL_MS=600000`,
     `DISABLE_TELEMETRY=1`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` and
     (`governed` only; `seat` keeps Claude Code's betas) `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`. The provider switches
     (`CLAUDE_CODE_USE_BEDROCK`, `_VERTEX`, `_FOUNDRY`, `_MANTLE`, `_ANTHROPIC_AWS`) are set to
     `""`.
   - `modelPicker`: the client policy's picker rows for the session's profile (see "Company models in
     `/model`"); the `governed` profile also gets `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` in `env`,
     the `seat` profile `0`.
   - `permissions`: `deny` holds the launcher's own `Read`/`Edit` deny for the state
     directory plus the policy's `deny` rules. `ask` holds the policy's `ask` rules.
     `disableBypassPermissionsMode` is `"disable"`.
   - `sandbox`: Bash runs in Claude Code's OS sandbox (`enabled`, `failIfUnavailable`,
     `allowUnsandboxedCommands: false`). `filesystem.denyRead` holds the state directory and
     `network.deniedDomains` holds the platform host (plus `localhost` and `127.0.0.1` when the
     platform host is loopback). So the agent's own commands can neither read the tokens or the
     signer socket nor call the platform directly. A machine without sandbox support refuses to
     start the session (`failIfUnavailable`). `network.allowedDomains` is the Workspace's
     admin-edited list for builds and package registries (`agent_gateway_policy.sandbox.allowed_domains`,
     `PUT /api/v1/workspaces/<id>/agent-gateway/sandbox`). It comes from the client policy, and
     malformed or platform-host entries are dropped. Without it, Claude Code asks you per domain.
   - `disableAllHooks: false`.
   - Hooks: `PreToolUse` (matcher `*`), `Stop` and `SubagentStop`, and `SessionEnd`.
4. It writes `mcp.json` with only the Octryx knowledge MCP
   (`<base>/api/v1/mcp/knowledge-protocol/mcp`, `type: http`), authenticated through
   `headersHelper` = `octryx-claude mcp-headers`.
5. It generates a 32-byte hook key and registers it with `POST /sessions/hook-key`
   (`{"hook_key": <base64url, no padding>, "state_root": <absolute state directory>}`; set once
   per session). The platform adds the state directory to its own self-protection rules. Any
   failure, for example `409 hook_key_already_registered`, means `session not started: hook key
   <codes>`.
5a. It reads the Workspace's catalog skills (`GET /skills/manifest`), fetches the blobs it does not have
   cached yet (`GET /skills/blobs/{sha256}`, re-hashed; cache under the state directory) and writes a
   read-only, per-session plugin `octryx` next to the state directory
   (`<state parent>/octryx-skill-plugins/<session>/octryx/`, files 0444). A hash or bundle-digest
   mismatch, or a `SKILL.md` with frontmatter outside the delivery allowlist, refuses the session
   (`denied: skill_bundle_digest_mismatch` / `skill_frontmatter_not_allowed`). If the platform cannot be
   reached the session starts without catalog skills and the start line says `skills_unavailable`. The
   settings add `disableSkillShellExecution: true`, `Edit`/`Write` deny rules for the plugin folder and a
   `UserPromptExpansion` hook that reports a typed `/octryx:<skill>` by name only. Allowed catalog
   MCP server entries (image by digest, no shell variables passed through) are added to `mcp.json`. The
   folder is removed at `SessionEnd`; folders of older sessions are swept at the next start.
6. It binds the git repository of the launch folder and uploads a snapshot of HEAD (see
   "Code intelligence in your checkout"). A failure never blocks the launch.
7. It starts the hook signer and runs `claude --settings <file> --strict-mcp-config --mcp-config <file> [--plugin-dir <plugin>] --session-id <key> <args>`.
   as its child (see "Supervisor and hook signer").
   `--session-id` is left out when you pass `--resume`/`--continue`. The child process gets
   `CLAUDE_CONFIG_DIR`, `OCTRYX_SESSION_KEY`, `OCTRYX_WORKSPACE_ID`, `OCTRYX_WORK_ITEM` and
   `OCTRYX_BASE_URL`, which the hooks inherit. The launcher removes credentials and provider
   switches that would reroute traffic: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
   `CLAUDE_CODE_OAUTH_TOKEN`, `AWS_BEARER_TOKEN_BEDROCK`, `CLAUDE_CODE_USE_*` and the provider
   base URLs and keys. `AWS_PROFILE` and ordinary AWS variables stay, because your tools may
   need them.

It refuses (`denied: flag_not_allowed`) any flag that would skip the hooks, replace the
generated configuration or leave the governed local session: `--bare`, `--safe-mode`,
`--settings`, `--setting-sources`, `--mcp-config`, `--strict-mcp-config`, `--plugin-dir`,
`--dangerously-skip-permissions`, `--allow-dangerously-skip-permissions`, `--bg`/`--background`,
`--cloud`, `--remote-control` and `--teleport`.

## Code intelligence in your checkout

Start octryx-claude in the folder where your code already is. The launcher detects the git
repository of that folder and makes it the code-intelligence source of the session, with
the same session key:

1. `POST /sessions/repository` registers the binding session -> Workspace -> repository.
   It sends the remote URL (`origin`, otherwise the first remote) **without credentials**:
   `user:password@` and token userinfo, query and fragment are stripped from http(s) URLs
   before anything leaves the machine; the ssh form `git@host:owner/repo.git` stays as is.
   It also sends the HEAD sha, whether the working tree has uncommitted changes to tracked
   files (`head_dirty`), whether a remote branch contains HEAD (`head_pushed`), the branch and
   the absolute checkout path (`root`). A confirmed change workflow may edit only inside `root`.
2. The Workspace policy `allow_local_snapshots` decides whether a snapshot may be uploaded.
   When it does, the launcher sends a manifest of the tracked regular files at HEAD (path,
   blob sha, size; at most 10000 files; symlinks and submodules are skipped). The platform
   answers which paths it still wants, so a re-launch only uploads changed blobs. The wanted
   contents follow in batches of at most 50 files and 3 MiB; a file over 1 MiB is never sent.
   `/complete` closes the repo@commit snapshot.
3. Only committed content is sent: uncommitted edits and untracked files never leave the
   machine. A dirty working tree is reported in the summary line.

The launcher prints exactly one line, for example
`octryx-claude: code intelligence: owner/repo @ 1a2b3c4 bound to Workspace <id>, 812 files indexed (12 new)`,
or `octryx-claude: code intelligence: off (<code>)` (`not_a_git_repository`, `head_missing`,
`remote_missing`, `git_unavailable`, a platform refusal code or `platform_unreachable`).
The session then starts anyway. `--no-code-intelligence` skips detection and sends nothing
(`off (skipped_by_flag)`).

Claude Code treats `~/.claude` paths as sensitive, so run it from a normal folder such as
`/tmp/<repo>`, not from inside `~/.claude`.

## Tokens

One login yields one refresh token, and each audience gets its own access token. The
platform writes the requested `resource` into the JWT `aud`:

- `octryx-model-gateway` for the model route and the control plane. `api-key-helper`
  prints it; the hooks use it too.
- `octryx-mcp` for the knowledge MCP. `mcp-headers` prints
  `{"Authorization": "Bearer ..."}` plus the session headers.

The scopes are `model:invoke knowledge:read knowledge:write session:write`. Every JWT
carries them all, and the audience keeps each token on its own surface. A token is
refreshed 15 minutes before it expires. That is longer than the 10-minute helper cache,
so a token Claude Code has cached never expires while it is in use. When a refresh fails,
the helper prints nothing, writes a fixed message to stderr and exits 1. Claude Code then
reports an auth error and you run `octryx-claude login` again.

## Hooks

- `pre-tool-use` posts the hook input to `/sessions/tool-check`.
  - `deny`: prints `permissionDecision: "deny"` as
    `Octryx policy denied this tool call [rule X] (reason_code): message`. The message is
    the platform's (bounded, control characters stripped), for example a `capability_read_only`
    denial that tells the agent to ask for a change workflow.
  - `allow`: prints nothing, so Claude Code's normal permission flow still applies. An
    explicit `allow` would skip the user's permission prompt.
  - `ask` (for example the MCP tool `workflow_confirm`): prints `permissionDecision: "ask"`
    with the platform's message, so you confirm the governed approval in Claude Code's own
    permission prompt. When the answer carries a `confirmation_ticket`, the hook adds it to the
    tool input through `updatedInput`, so only the real MCP call carries the one-time ticket.
  - `workflow_confirm` (`mcp__octryx-knowledge__workflow_confirm`): before the
    tool-check the hook asks the supervisor's signer for an HMAC over
    `v1|confirm|<session>|<tool_use_id>|<approval_id>|<nonce>|<ts>` and sends
    `confirmation_proof: {nonce, ts, mac}`. Without a signature it denies
    (`hook_signer_unavailable`, fail closed).
  - Anything else denies the call (fail closed): the platform is unreachable, the call is
    refused, the answer is invalid or the hook crashes. The hook command ends in
    `|| { ...; exit 2; }`, so a hook that cannot even start still blocks the call.
- `post-tool-use` (PostToolUse and PostToolUseFailure, matcher `Bash` only) posts the hook
  input to `/sessions/tool-executed`. The platform stores only the execution outcome
  (`succeeded`/`failed`) on the tool call, so the verification gate can tell a failed test
  from one that was refused before it ran (`last_test_not_run`). It prints nothing, never
  blocks and always exits 0 (4 s HTTP timeout, 10 s hook timeout).
- `stop` (Stop and SubagentStop) posts the hook input to `/sessions/verification`.
  - `passed` and `not_applicable`: the stop is allowed.
  - `blocked`: returns `{"decision":"block","reason":<detail>}`, even when
    `stop_hook_active` is true, because the platform is the authority. **Cap:** once 3
    consecutive blocks have been returned in one continuation chain, the hook allows the
    stop and prints a `systemMessage` that says the gate is still red. A chain restarts when
    Claude Code sends `stop_hook_active: false`. The counter is stored per event and agent in
    `sessions/<key>/stop_blocks.json`. Claude Code's own cap is 8 continuations.
  - `needs_configuration`, the platform is unreachable, or the state is unknown: the stop is
    allowed with a `systemMessage`.
- Seat sessions only: `stop-failure` (Claude Code's `StopFailure`, which "fires instead of Stop when an API
  error ended the turn" and ignores the hook's output) records the fixed `error` code. `authentication_failed` or
  `oauth_org_not_allowed` means the subscription login was rejected, `rate_limit` or `billing_error` that the
  limit is reached; a refusal by the Octryx seat route (`Octryx gateway: <state> (<reason>)`) is
  kept apart. The next prompt shows the failure once with its fix as a `systemMessage` (`user-prompt-submit`), the
  launcher prints it again when the session ends, and the next start's status block and `--profile auto` use it.
  A completed seat turn (`stop`) or `login --seat` clears it.
- `session-end` builds the digest from `transcript_path` and posts `/sessions/finalize`. It
  only reads transcripts inside `claude-config/`. The digest reuses
  `backend/scripts/ingest_claude_session.build_digest` and
  `mcp_session_ingest_common.cap_digest` (redaction and cap). The hook always exits 0.

## Codex device turns

A device turn on `codex app-server` runs only with the launcher's own hooks, settings and platform tools
(`codex_driver`, `codex_trust`, `codex_hook_guard`).

- A turn starts only when Codex reports exactly the launcher's three hooks, enabled and trusted by hashes the
  launcher computes itself, and the hook guard runs.
- Codex receives a PreToolUse decision only as an explicit allow or as a block (`codex_hook_guard`).
- Every launcher command Codex runs goes through the session's wrapper, which starts the launcher by absolute path
  with `python -I`; hooks and helpers also get a fixed `PATH` (`codex_config`).
- A sandboxed turn starts only when no part of the hook chain lies in a folder the turn may write, and a round
  starts only while the session's config, wrapper and guard are unchanged (`codex_driver`).
- The work folder and its git root are untrusted for Codex; a turn in which a repository's `.codex/config.toml`
  still takes effect is refused (`codex_trust`).
- Tool shells get none of the launcher's `OCTRYX_*` variables except the turn mark and the browser and build-cache
  settings, and none of Codex's `*KEY*`, `*SECRET*`, `*TOKEN*` names (`codex_config`).

Known limits:

- Codex 0.169 runs a tool call when it cannot start the hook, or when the hook's runner fails or passes its
  deadline before the guard answers.
- A bypass turn (full access) on a person's device is no boundary against the agent, as Claude Code's
  skip-permissions mode is not.

## Supervisor and hook signer

The launcher does not exec claude. It stays as claude's parent process (the supervisor),
with inherited stdio in the same process group, and exits with claude's exit code
(`128 + signal` for a signal death). It ignores SIGINT and SIGQUIT, because claude receives
them from the terminal itself. It forwards SIGTERM and SIGHUP. When claude stops (Ctrl-Z), the
supervisor stops itself and wakes claude again when it is resumed.

The hook key exists only in the supervisor's memory. It is never written to a file, an
environment variable, argv or a log. The signer answers on `sessions/<key>/hook.sock`
(directory 0700, socket 0600) with one JSON line per connection (`{"op": "sign", "message"}`
returns `{"mac"}` or `{"error"}`). It signs only confirmation messages of its own session, and
requests are capped at 4 KiB. The socket is removed when the session ends. A process that
holds only the tokens therefore cannot forge a confirmation proof, and the sandboxed Bash
cannot reach the socket. The socket path must fit in 104 bytes, so keep `OCTRYX_CLAUDE_HOME`
short (`session not started: hook signer socket_path_too_long` otherwise).

## Verified Claude Code facts

Checked against the docs and against the installed CLI (`claude --version` =
2.1.282; `claude --help` lists `--settings <file-or-json>`, `--strict-mcp-config`,
`--mcp-config <configs...>` and `--session-id <uuid>`, which "must be a valid UUID").

| Fact | Source |
|---|---|
| `apiKeyHelper` runs through `/bin/sh`. Its output is sent as both `X-Api-Key` and `Authorization: Bearer`. The command is rerun when the cache lifetime ends (5 min by default, `CLAUDE_CODE_API_KEY_HELPER_TTL_MS`), on a `401`/`403`, and before a request when the cached value is an expired JWT (v2.1.246+). The last two cases apply only while `ANTHROPIC_AUTH_TOKEN` is unset | https://code.claude.com/docs/en/settings-reference#apikeyhelper |
| The helper must print nothing but the credential: from v2.1.227, extra output makes it fail. If it exits with an error, times out or prints nothing, requests fail with "Your apiKeyHelper script is failing" | https://code.claude.com/docs/en/llm-gateway-connect , https://code.claude.com/docs/en/authentication |
| Credential precedence: `CLAUDE_CODE_USE_BEDROCK`/`_VERTEX`/`_FOUNDRY` first, then `ANTHROPIC_AUTH_TOKEN`, then `ANTHROPIC_API_KEY`, then `apiKeyHelper`, then `CLAUDE_CODE_OAUTH_TOKEN`, then `/login`. This is why the launcher scrubs the variables above `apiKeyHelper` | https://code.claude.com/docs/en/authentication#authentication-precedence |
| `ANTHROPIC_CUSTOM_HEADERS` holds `Name: Value` pairs, newline-separated. `ANTHROPIC_BASE_URL` overrides the API endpoint | https://code.claude.com/docs/en/env-vars |
| `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU}_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL` are supported. `ANTHROPIC_SMALL_FAST_MODEL` is deprecated: `ANTHROPIC_DEFAULT_HAIKU_MODEL` also covers background tasks | https://code.claude.com/docs/en/env-vars , https://code.claude.com/docs/en/model-config |
| `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` strips `anthropic-beta` headers and beta tool fields. `DISABLE_TELEMETRY` and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` each take any non-empty value | https://code.claude.com/docs/en/env-vars |
| `CLAUDE_CONFIG_DIR` replaces `~/.claude`. Project and local settings cannot set it | https://code.claude.com/docs/en/env-vars , https://code.claude.com/docs/en/settings-reference |
| Precedence: managed, then `--settings` (command line), then project local, then project, then user. `env` values in `--settings` override shell exports. An empty value counts as unset for provider selection | https://code.claude.com/docs/en/settings , https://code.claude.com/docs/en/settings-reference#env |
| `permissions.disableBypassPermissionsMode: "disable"` rejects `--dangerously-skip-permissions`. Absolute paths in rules use `//path` | https://code.claude.com/docs/en/settings-reference , https://code.claude.com/docs/en/permissions |
| `--strict-mcp-config` uses only the servers from `--mcp-config`. An MCP `http` server supports `headersHelper`: a shell command that prints a JSON object of headers. It runs on each connection, is not cached, times out after 10 s and is rerun on a `401`/`403` | https://code.claude.com/docs/en/cli-reference , https://code.claude.com/docs/en/mcp |
| PreToolUse output is `hookSpecificOutput.permissionDecision` (`allow`, `deny`, `ask`, `defer`). The reason for `deny` is shown to Claude. `allow` skips the permission prompt. Deny and ask rules are still evaluated. Exit 2 blocks the call; any other non-zero exit is a non-blocking error | https://code.claude.com/docs/en/hooks |
| Stop and SubagentStop: `{"decision":"block","reason":...}` prevents the stop, and Claude receives the reason as the explanation for why it should continue. `stop_hook_active` is true while Claude is already continuing because of a stop hook. After 8 consecutive continuations Claude Code overrides the next block (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`) | https://code.claude.com/docs/en/hooks#stop-decision-control |
| SessionEnd has no decision control, and its output is discarded. The default budget is 1.5 s; a per-hook `timeout` raises it to at most 60 s | https://code.claude.com/docs/en/hooks#sessionend |
| Hooks inherit Claude Code's environment. Hook `timeout` is in seconds (default 600) | https://code.claude.com/docs/en/hooks |
| A failed Bash command reaches PostToolUseFailure with `error` = `Exit code N` plus the output, "generally the same text Claude receives as the failed tool's result". A Bash `tool_result` whose content starts with `Exit code N` (N != 0) has `is_error: true` in Claude Code transcripts | https://code.claude.com/docs/en/hooks#posttoolusefailure |
| PostToolUse fires after a tool call succeeded (a Bash command with exit code 0); PostToolUseFailure fires "when a tool that started executing fails" (non-zero exit, timeout). PostToolUseFailure "doesn't fire for tool calls rejected before execution: an unknown tool name, input that fails schema or tool-specific validation, or a permission denial"; cancelling a running tool fires neither. Both receive `tool_name`, `tool_input` and `tool_use_id`, match on the tool name, and cannot block (exit 2 only shows stderr to Claude). PermissionDenied fires only for auto-mode denials, not for a manually refused prompt | https://code.claude.com/docs/en/hooks#posttoolusefailure , https://code.claude.com/docs/en/hooks#permissiondenied |
| PreToolUse output supports `hookSpecificOutput.updatedInput` (modified tool input) together with `permissionDecision: "ask"`. MCP `tools/call` carries `_meta["claudecode/toolUseId"]`. Settings support `sandbox` (`enabled`, `failIfUnavailable`, `allowUnsandboxedCommands`, `filesystem.denyRead`, `network.deniedDomains`, ...), and `Read(...)` deny rules are merged into the sandbox `denyRead` | installed CLI 2.1.282 |
| `StopFailure` fires instead of Stop when an API error ended the turn; input `error` (`authentication_failed`, `oauth_org_not_allowed`, `rate_limit`, `billing_error`, `overloaded`, `server_error`, ...), optional `error_details` and `last_assistant_message`; output and exit code are ignored. `claude auth login [--claudeai]` signs in to the subscription | installed CLI 2.1.282 |
| `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` fills `/model` from the gateway's `GET /v1/models?limit=1000` (3 s timeout, no redirects) when `ANTHROPIC_BASE_URL` is a gateway. Discovery sends `Authorization` (from `ANTHROPIC_AUTH_TOKEN` or `apiKeyHelper`) and `x-api-key`, plus `ANTHROPIC_CUSTOM_HEADERS`. It is skipped when neither credential resolves, so a subscription login gets no discovery. It reads `id`, `display_name` and `description` from `data`, and keeps only ids that contain `claude` or `anthropic`. The cache lives under `CLAUDE_CONFIG_DIR` | https://code.claude.com/docs/en/llm-gateway-protocol#model-discovery , https://code.claude.com/docs/en/env-vars |
| `modelPicker` (`--settings`, user or managed scope only; v2.1.242+): `options` rows with `model`, optional `label` and `description`, added after the built-in lineup unless `replaceBuiltInOptions` is set. Each row's `model` is taken verbatim | https://code.claude.com/docs/en/settings-reference#modelpicker |
| Project and local settings can turn hooks off (`disableAllHooks`), so the generated settings set it to `false` at the higher `--settings` level | https://code.claude.com/docs/en/settings-reference#disableallhooks |

## Tests

```bash
cd clients/octryx-claude
<main checkout>/backend/.venv/bin/python -m pytest -q   # contract tests
<main checkout>/backend/.venv/bin/python -m ruff check .  # ruff.toml mirrors the backend rule set
bash tests/installer/install_sh_test.sh                  # install.sh against a fake platform in a temp HOME
```

`tests/test_installer_scripts.py` runs the install.sh suite too (real venvs: pip needs its index, or
`PIP_NO_INDEX=1 PIP_FIND_LINKS=<wheelhouse>`) and tests `install.ps1` statically (no PowerShell 7-only syntax) and,
when `pwsh` is installed, with a fake `wsl.exe`.
