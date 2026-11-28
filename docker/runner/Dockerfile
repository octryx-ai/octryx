# syntax=docker/dockerfile:1
# octryx-runner: the platform's server runner. The same launcher, Codex driver and hooks as a device; one image for
# every repository, language toolchains are the customer's layer on top (see README.md here).
# Build from the repository root: docker build -f docker/runner/Dockerfile -t octryx-runner .
FROM python:3.12.8-slim-bookworm@sha256:2199a62885a12290dc9c5be3ca0681d367576ab7bf037da120e564723292a2f0

ARG TARGETARCH
ARG CODEX_VERSION=0.169.0
ARG CODEX_SHA256_ARM64=97b97d87eea075c5cb7709c7f6156a451622a7667953ecda40e0276637196f3f
ARG CODEX_SHA256_AMD64=9af4d751fce183faedea629437d5252dbf458eeb04130cf4f97be844621ea985

RUN apt-get update \
 && apt-get install -y --no-install-recommends bash bubblewrap ca-certificates coreutils curl findutils git patch \
    procps ripgrep tini xz-utils \
 && rm -rf /var/lib/apt/lists/*

RUN case "$TARGETARCH" in \
      arm64) arch=aarch64; sum="$CODEX_SHA256_ARM64" ;; \
      amd64) arch=x86_64; sum="$CODEX_SHA256_AMD64" ;; \
      *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac \
 && curl -fsSL -o /tmp/codex.tar.gz \
    "https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-${arch}-unknown-linux-musl.tar.gz" \
 && echo "${sum}  /tmp/codex.tar.gz" | sha256sum -c - \
 && tar -xzf /tmp/codex.tar.gz -C /tmp \
 && install -m 0755 "/tmp/codex-${arch}-unknown-linux-musl" /usr/local/bin/codex \
 && rm -f /tmp/codex.tar.gz "/tmp/codex-${arch}-unknown-linux-musl"

# The launcher's own dependencies at the versions it pins, without claude-agent-sdk: it bundles the Claude Code CLI,
# which may not be redistributed, and a runner only drives Codex.
RUN python -m venv /opt/octryx/venv \
 && /opt/octryx/venv/bin/pip install --no-cache-dir httpx==0.28.1 cryptography==50.0.1 websockets==16.0 \
    ast-grep-cli==0.51.0 playwright==1.64.1 ruff==0.15.7
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN /opt/octryx/venv/bin/playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/* /root/.cache

# A run phase's browser (launcher browser_mcp): the Playwright MCP server at the versions of browser-mcp/package-lock.json,
# installed here because a runner has no internet; its Chromium shares the folder above. Node from nodejs.org, pinned.
ARG NODE_VERSION=22.23.4
ARG NODE_SHA256_ARM64=6287aa46b6c375d816e63ae66d024fbbfd70404825aabdfdf898a970871d2f4b
ARG NODE_SHA256_AMD64=1805bcd35e6815559bd2eb97db438d3fdb0eb3a5e6a977b7c1badca76337e9ce
COPY docker/runner/browser-mcp/package.json docker/runner/browser-mcp/package-lock.json /opt/octryx/browser-mcp/
RUN case "$TARGETARCH" in \
      arm64) arch=arm64; sum="$NODE_SHA256_ARM64" ;; \
      amd64) arch=x64; sum="$NODE_SHA256_AMD64" ;; \
      *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac \
 && curl -fsSL -o /tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${arch}.tar.xz" \
 && echo "${sum}  /tmp/node.tar.xz" | sha256sum -c - \
 && mkdir -p /opt/node && tar -xJf /tmp/node.tar.xz -C /opt/node --strip-components=1 && rm -f /tmp/node.tar.xz \
 && ln -s /opt/node/bin/node /usr/local/bin/node \
 && cd /opt/octryx/browser-mcp \
 && /opt/node/bin/npm ci --ignore-scripts --no-audit --no-fund \
 && ln -s /opt/ms-playwright /opt/octryx/browser-mcp/browsers \
 && node node_modules/playwright/cli.js install chromium \
 && rm -rf /opt/node/lib/node_modules/npm /opt/node/bin/npm /opt/node/bin/npx /opt/node/bin/corepack /root/.npm /root/.cache

COPY clients/octryx-claude/octryx_claude /opt/octryx/lib/octryx_claude
# The platform scripts the published wheel vendors (backend/app/services/octryx_client/artifact.py): the secret rules
# that redact every job output before it leaves the runner.
COPY backend/scripts/ingest_claude_session.py backend/scripts/mcp_session_ingest_common.py \
     backend/scripts/transcript_secrets.py backend/scripts/secret_patterns.py \
     /opt/octryx/lib/octryx_claude/_platform_scripts/
COPY docker/runner/entry.sh /opt/octryx/entry.sh

# The launcher's account owns the state; the agent's account runs Codex, its tools and hooks and cannot change the
# launcher, its interpreter or the session's Codex configuration.
RUN groupadd --gid 10001 octryx && groupadd --gid 10002 agent \
 && useradd --uid 10001 --gid octryx --groups agent --no-create-home --shell /usr/sbin/nologin octryx \
 && useradd --uid 10002 --gid agent --no-create-home --shell /bin/bash agent \
 && python -m compileall -q /opt/octryx/lib \
 && chmod -R a-w /opt/octryx /opt/node /usr/local/bin/codex

ENV PATH=/opt/octryx/venv/bin:/usr/local/bin:/usr/bin:/bin \
    OCTRYX_CLAUDE_HOME=/var/lib/octryx \
    OCTRYX_WORKSPACE=/workspace \
    OCTRYX_CLAUDE_AUTO_UPDATE=0 \
    OCTRYX_CODEX_CONTAINER_BOUNDARY=1 \
    OCTRYX_CODEX_PATH=/usr/local/bin/codex \
    OCTRYX_BROWSER_MCP_DIR=/opt/octryx/browser-mcp \
    HOME=/tmp/home

WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/octryx/entry.sh"]
