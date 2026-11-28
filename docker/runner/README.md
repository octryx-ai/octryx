# octryx-runner

The platform's server runner: Codex sessions in a container of their own, for people who run a chat turn or a
workflow step "on the Server runners" instead of their own device. It runs the same launcher, Codex driver and hooks
as a device (`clients/octryx-claude`); the platform sees it as a device owned by the technical account
`octryx-runner` that serves every Workspace allowing server runners.

## Running it

`docker compose up -d` starts one runner next to the platform (service `runner`); more with
`docker compose up -d --scale runner=3`. Nothing else is needed:

- `secrets-init` writes a join secret into the `runner_join` volume, which only the api and the runners mount.
- On its first start a runner registers with that secret (`POST /api/v1/devices/runner/enroll`) and keeps its device
  credential in its own state (`/var/lib/octryx`, a tmpfs). A restarted container enrolls again as a new device; the
  old one stays offline in Admin › Devices until it is removed there.
- A Workspace switches server runners off with `server_runners: "forbidden"` in its configuration. Then neither a
  chat turn nor a workflow run of that Workspace lands on a runner.

A chat turn targets the pool with `execution_target: {"kind": "device", "device_id": "pool", "profile": "governed"}`;
a workflow run offers "Server runners · governed" in its start dialog while a runner is online. The platform picks the
runner that already holds the thread when it is free (its Codex thread lives there), else the least busy one, and a
fresh folder `/workspace/<id>` for a new thread. Runners only run governed: models through the platform's gateway,
never a person's seat.

## What a session can and cannot do

Two accounts share the container. The launcher (`octryx`, uid 10001) holds the device credential, writes each
session's Codex configuration and hook chain, and starts Codex under the agent's account (`agent`, uid 10002) with
no capabilities. Everything Codex runs (commands, tools, hooks) runs as the agent:

- The device credential and the join secret are not readable by the agent. A token broker (a socket of the launcher)
  hands the agent's processes the model-gateway and MCP tokens they need, never the device channel's token.
- The session's `config.toml`, its hook wrapper, the launcher and Codex itself are read-only for the agent, so even a
  session with full access cannot switch its hooks off. The launcher also checks the chain's content between rounds.
- The container is on a network (`runners`, internal) that reaches nothing but the runner gateway, an nginx that
  forwards the api's port. No database, object store, LiteLLM or internet; `git push` has nowhere to go.
- A gateway call from a runner acts for the person whose turn it runs, and only while that turn is active: their
  Workspace membership, budget and usage, never a standing access of the runner account.
- All sessions of a runner share the agent's account and its disk, so a runner serves one person in one Workspace at
  a time: the platform offers it no turn of anyone else while one is active, and before the first turn of another
  person or Workspace the launcher empties `/workspace`, the agent's home and the Codex and session state. A
  thread that comes back to an emptied runner gets an empty folder; the launcher restores its Codex thread from the
  session files the platform keeps.

Behind the container boundary Codex runs without its own sandbox (`danger-full-access`); "ask before changes" in the
chat becomes Codex's approval policy `untrusted`, so every command that is not known to be read-only is asked in the
chat.

## The run's repository

A runner holds no credential of the Workspace's SCM connection, and its network reaches no git host. The launcher
reads the run's branch through the platform:
1. It asks for a run-bound token (`POST /api/v1/agent-gateway/sessions/git-token`). The token lives 10 minutes and is
   checked again on every request: the turn must still be active, the person still a member, the session still bound
   to the run and the run still active.
2. It fetches with git smart HTTP from the run's working copy on the platform (`/api/v1/agent-gateway/git/<run>`).
   Only the run's branch is visible there. The token reaches git only in the environment of that one fetch, never in
   argv, a URL or `.git/config`, and the agent's account never sees it. `origin` stays the repository's own URL.

Nothing is pushed from a runner: the gateway refuses `git-receive-pack`, and `git push` is blocked in the session.
The change goes to the platform as a patch. The platform pushes the reviewed tree with its connection (`scm.push`)
and opens the pull request. The job folder is a safe git directory for the agent (`safe.directory`), so its own git
calls and hooks work in the folder the launcher set up.

## Container runtime: gVisor

Codex runs other people's code with a shell, so the hardened option is gVisor (`runsc`), a user-space kernel between
the session and the host. The runtime is configured, never guessed:

- compose: `RUNNER_RUNTIME=runsc` in `.env`. Docker then starts the runner with `runtime: runsc`, and refuses to start
  it on a host that has no such runtime.
- Helm: `runners.runtimeClassName` (for example `gvisor`), set on the runner pods. Kubernetes refuses to create a pod
  whose RuntimeClass does not exist (`kubectl get runtimeclass` shows what the cluster has).
- In both, the api gets the same name and admits only runners that report it at enrollment
  (`runner_runtime_mismatch`). With no runner admitted, a pool turn is `needs_configuration`
  (`runner_pool_unavailable`). Nothing falls back to plain runc.

Installing gVisor is the host's or the cluster's part (https://gvisor.dev/docs/user_guide/install/, on Kubernetes
usually a node pool with the `runsc` handler and a RuntimeClass pointing at it). Not yet tested here: a chat turn and
a workflow run on gVisor itself (tracked in the v0.0.2 tracker).

## A browser for the session

A run phase that opts in to a browser (`browser_phases`, or `config.browser` on the phase) gets the same Playwright
MCP server as on a device, with Chromium for this session only: headless, its own profile, loopback pages only. A
runner has no internet, so the image carries both at pinned versions (`browser-mcp/package-lock.json`, Node.js by
checksum) and nothing is installed at run time. The session starts its app on 127.0.0.1, opens it, and sees the
screenshots; its browser folders sit in the session's state and are emptied with it.

## Language toolchains: extend the image

The image carries Python, git, ripgrep, ast-grep, ruff and a headless Chromium, and no language toolchains. A
customer adds theirs in a layer on top and runs that image in place of `octryx-runner`:

```dockerfile
FROM octryx-runner:local
USER root
RUN apt-get update && apt-get install -y --no-install-recommends default-jdk-headless maven \
 && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/default-java MAVEN_OPTS=-Dmaven.repo.local=/tmp/agent-home/.m2
```

The full example is `examples/java.Dockerfile`. Keep the entrypoint and the two accounts as they are; anything the
agent should write (build caches, package caches) belongs under its home `/tmp/agent-home` or the session folder.

## Building

From the repository root: `docker build -f docker/runner/Dockerfile -t octryx-runner .` The Codex release and Node.js
are pinned by version and checksum per architecture (`CODEX_*`, `NODE_*`), the Playwright MCP server by
`browser-mcp/package-lock.json`. The image is large (about 5 GB): Python's Playwright and the MCP server's each bring
their own Chromium build.

On Kubernetes the chart runs the image (`runners.enabled`, `images.runner`, see `deployment/helm/octryx/README.md`).
