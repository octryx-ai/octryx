# Sandbox images (octryx-claude device runner, headless)

A sandbox runs with a read-only root as uid 10001, with `/workspace` and `/tmp` as emptyDir volumes, and reaches git
only through the platform's run-bound gateway.
The images are not published: build them yourself (below) and push them only to a private registry you
control (`<registry>/octryx-sandbox-<toolchain>`), digest-pinned in values.

Never publish an image that contains Claude Code. `Dockerfile.base` installs the Claude Code CLI, which is
proprietary software under Anthropic's terms, not open source, so an image built from it must stay private.

| Image | Dockerfile | Adds |
|---|---|---|
| `octryx-sandbox-base` | `Dockerfile.base` | Python 3.12, Node 22, git, tini, the octryx-claude wheel (build time, sha256 checked), Claude Code CLI (pinned) |
| `octryx-sandbox-java-maven` | `Dockerfile.java-maven` | Temurin 21, Maven 3.9 (sha512 checked) |
| `octryx-sandbox-node` | `Dockerfile.node` | corepack (pnpm, yarn) |
| `octryx-sandbox-python` | `Dockerfile.python` | uv, pytest |

## Build

```sh
docker build -f Dockerfile.base --build-arg OCTRYX_BASE_URL=https://<platform> -t octryx-sandbox-base .
docker build -f Dockerfile.python --build-arg BASE_IMAGE=octryx-sandbox-base -t octryx-sandbox-python .
```

Rebuild the base image after every client release, because the wheel is baked in.

## Runtime (set by the platform's Job)

- **env:**
  - `OCTRYX_BASE_URL` (https);
  - `OCTRYX_SANDBOX_RUN_ID`;
  - `OCTRYX_SANDBOX_BRANCH` (base branch, optional);
  - `OCTRYX_TOOLCHAIN`;
  - mirrors (optional): `MAVEN_MIRROR`, `NPM_CONFIG_REGISTRY`, `UV_INDEX_URL` / `PIP_INDEX_URL`.
- **one file:** `/run/secrets/octryx/enroll` (one-time, run-bound, TTL ≤ 10 min).
- **git only through the platform's git gateway** (contract section "Git through the platform gateway"). No git
  secret is in the pod: git asks `octryx-claude git-credential` (user `x-run`) for a short-lived, run-bound gateway
  token on every call. origin is the gateway URL; the work branch is `octryx-run/<run_id>`; the platform opens the PR.
- **pod:**
  - uid 10001, `readOnlyRootFilesystem`;
  - `/workspace` and `/tmp` as emptyDir;
  - no service-account token;
  - `drop: [ALL]`, `RuntimeDefault`;
  - egress only to the gateway, the registry proxy and the platform.

The entry point creates `$HOME` and the state dir under `/tmp`, then runs `octryx-claude device run --sandbox`:
enroll, clone through the gateway, check out `octryx-run/<run_id>`, serve the run's device jobs, and exit 0 after
10 minutes idle or on revoke.
