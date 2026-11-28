# Which OS base the Python runtime stage builds on: `os-base` (default) for api,
# `java-toolchain` for api-coding and code-intel-worker. A global ARG, because
# FROM only expands ARGs declared before the first FROM. The target stages check the value, so a
# Java target built without it (or a plain target built with it) fails instead of shipping the
# wrong toolchain.
ARG RUNTIME_BASE=os-base

FROM node:22-slim AS chat-frontend-build

WORKDIR /app/frontend/chat

COPY frontend/chat/package*.json ./
RUN npm ci

COPY frontend/chat/ ./
RUN mkdir -p /app/backend/app/web/static/chat \
    && npm run build \
    && rm -rf node_modules /root/.npm /root/.cache

# Resolves the exact locked closure -- both the runtime set and the build backend.
# Kept in its own stage so that uv never reaches a shipped image, and so the exported
# requirement sets cannot drift from backend/uv.lock: `uv export --locked` fails the
# build if the lock is not current.
#
# Runs on $BUILDPLATFORM, not on the target platform. The export is platform
# independent -- uv writes a universal requirements file carrying every environment
# marker and the hashes of every platform's wheels, and pip evaluates those markers
# when it installs. Running it natively also avoids a hard failure: uv is a Rust
# binary and segfaults under qemu, so a `--platform linux/amd64` build on Apple
# Silicon (the documented local build path) aborts with SIGSEGV if this stage is emulated.
#
# BUILDPLATFORM is predefined by BuildKit, which `docker buildx` uses. A builder that does not predefine it fails here
# with "empty platform value from expression $BUILDPLATFORM" rather than building
# something wrong; pass the builder's own platform explicitly in that case
# (--build-arg BUILDPLATFORM=<os>/<arch>).
FROM --platform=$BUILDPLATFORM python:3.12-slim AS python-deps

# Pinned so two builds of the same commit export the same requirement set.
ARG UV_VERSION=0.12.19

WORKDIR /export

COPY backend/pyproject.toml backend/uv.lock ./
# Two exports, both from the same lock:
#   requirements.txt       the runtime closure the image serves from (--no-dev), plus the
#                          `knowledge` extra: the in-process embedding option (fastembed/ONNX)
#                          the Knowledge module supports next to Bedrock.
#   build-requirements.txt the `build` dependency group, i.e. the [build-system]
#                          backend, so the project install below needs no PEP 517
#                          build isolation. Build isolation resolves and downloads a
#                          build backend from PyPI on every build -- unpinned,
#                          unhashed, outside uv.lock and outside every audit -- which
#                          is exactly the fresh resolution the lock removes.
RUN pip install --no-cache-dir "uv==${UV_VERSION}" \
    && uv export --locked --format requirements-txt --no-dev --extra knowledge --no-emit-project \
        -o /export/requirements.txt \
    && uv export --locked --format requirements-txt --only-group build --no-emit-project \
        -o /export/build-requirements.txt

# The OS layers every runtime image shares: runtime user, shell tools, AWS CLI. They come before
# and independent of the Python dependency layers, so a lock change never rebuilds them.
FROM python:3.12-slim AS os-base

WORKDIR /app/backend

ENV PATH="/root/.local/bin:/usr/local/lib/node_modules/.bin:${PATH}"
# Keep bytecode enabled: without it every first import compiles inside the API's event loop
# and stalled it for seconds to minutes. The image compiles the backend at build time (below); a dev stack that
# bind-mounts the source read-only sets PYTHONPYCACHEPREFIX to a container-local path and compiles at start.
ENV PYTHONUNBUFFERED=1
ENV HOME=/tmp

RUN groupadd --system --gid 10001 octryx \
    && useradd --system --uid 10001 --gid 10001 --home-dir /tmp --shell /usr/sbin/nologin octryx

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash curl ca-certificates git ripgrep unzip \
    && arch="$(uname -m)" \
    && case "${arch}" in \
        x86_64) aws_arch="x86_64" ;; \
        aarch64|arm64) aws_arch="aarch64" ;; \
        *) echo "Unsupported AWS CLI architecture: ${arch}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${aws_arch}.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/aws /tmp/awscliv2.zip \
    && rm -rf /var/lib/apt/lists/*

# LibreOffice headless: the optional pixel-faithful render of Office documents (PDF/PNG preview, opt-in render
# step of validate_office_document). It never runs with a network: the acceptance stack starts this image a
# second time as the `office-render` sidecar (network_mode: none, no secrets; services/office/render_server.py)
# and the API talks to it over a Unix socket. Without the sidecar the API renders only behind a no-network
# wrapper (unshare --net), otherwise it reports office_preview_unavailable. Every conversion uses a locked-down
# per-call profile (macros off, link updates never), rlimits, a timeout and a process-group kill
# (services/office/render_sandbox.py). The Office tools and build scripts themselves run in-process on
# python-docx, python-pptx and openpyxl (services/office/engine). Writer, Calc and Impress only (no
# recommends: no Java, no GUI); DejaVu gives the renders and the Pillow flow diagrams a font.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-core libreoffice-writer libreoffice-calc libreoffice-impress fonts-dejavu-core \
    && soffice --version \
    && rm -rf /var/lib/apt/lists/*

# The Java build toolchain (Temurin 25 JDK and Maven) that coding sessions run: a coding agent builds
# and tests a Java repository in its session workspace. Built on the OS
# base only, so a lock change reuses this layer instead of downloading the JDK again.
FROM os-base AS java-toolchain

RUN apt-get update \
    && apt-get install -y --no-install-recommends gnupg maven \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --dearmor -o /etc/apt/keyrings/adoptium.gpg \
    && . /etc/os-release \
    && echo "deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb ${VERSION_CODENAME} main" > /etc/apt/sources.list.d/adoptium.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends temurin-25-jdk \
    && rm -rf /var/lib/apt/lists/*

# The locked Python closure, the application and its write roots, on the base RUNTIME_BASE names.
# Written once for both bases; the two stages below pin which base a target family accepts.
FROM ${RUNTIME_BASE} AS runtime-closure

COPY --from=python-deps /export/requirements.txt /tmp/requirements.txt
COPY --from=python-deps /export/build-requirements.txt /tmp/build-requirements.txt
# Every artifact in this image comes from backend/uv.lock, and pip resolves nothing:
# --require-hashes pins every artifact by digest and implies --no-deps.
#
#   1. the locked build backend, so that step 3 can run without build isolation;
#   2. the locked runtime closure;
#   3. (after the source copy below) the project itself.
#
# Steps 1 and 2 are their own layer and depend only on the two exported files, i.e. on
# backend/pyproject.toml + backend/uv.lock: a source-only change reuses it and downloads
# nothing. The BuildKit cache mount keeps pip's download cache across builds, outside the
# image, so a lock change fetches only the changed artifacts; every artifact, cached or
# downloaded, is still checked against its lock digest by --require-hashes.
RUN --mount=type=cache,id=octryx-pip,target=/var/cache/pip,sharing=locked \
    PIP_CACHE_DIR=/var/cache/pip pip install --require-hashes -r /tmp/build-requirements.txt \
    && PIP_CACHE_DIR=/var/cache/pip pip install --require-hashes -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt /tmp/build-requirements.txt

COPY backend/ ./
COPY --from=chat-frontend-build /app/backend/app/web/static/chat ./app/web/static/chat
# Bytecode at build time: no import ever compiles at runtime (an import inside a request blocked the event loop).
RUN python -m compileall -q -j 0 app
# The octryx-claude client the platform serves to its installers: the routes build the wheel from these
# sources (app/services/octryx_client, read from /app/clients/octryx-claude) and fill the installer scripts.
COPY clients/octryx-claude/pyproject.toml /app/clients/octryx-claude/pyproject.toml
COPY clients/octryx-claude/octryx_claude/ /app/clients/octryx-claude/octryx_claude/
COPY clients/octryx-claude/installer/ /app/clients/octryx-claude/installer/
# Plugins (backend/app/services/plugins/image.py): Octryx installs what is in /opt/octryx/plugins at every start.
# This image brings none there; the plugins of this repository come along as examples to copy in your own image:
#   FROM <octryx image>
#   COPY my-plugin/ /opt/octryx/plugins/my-plugin/
#   RUN cp -r /opt/octryx/plugin-examples/release-notes /opt/octryx/plugins/
COPY plugins/ /opt/octryx/plugin-examples/
#   3. the project itself, --no-deps (its dependencies are already satisfied by 2)
#      and --no-build-isolation (its build backend is already satisfied by 1). Without
#      --no-build-isolation pip would build this project in a throwaway environment it
#      populates by resolving [build-system].requires from PyPI on every build, which
#      no lock, hash or audit covers.
RUN pip install --no-cache-dir --no-deps --no-build-isolation . \
    && rm -rf build octryx.egg-info \
    && rm -rf /usr/local/lib/python3.12/site-packages/app/

# Runtime write roots. Several services still derive them from the source tree:
# uploads (knowledge documents, corporate identities, office templates, chat files)
# resolve to /app/uploads, parsed knowledge documents to /app/research, and a few
# data files (audit fallback, snapshots, report exports) to /app/backend/data. All of
# them must exist and belong to the runtime user, or those features fail with a 500.
RUN mkdir -p /app/data /app/data/provider_profiles /app/data/code-intelligence \
        /app/uploads /app/research /app/backend/data \
    && chown -R 10001:10001 /app/data /app/uploads /app/research /app/backend/data

FROM runtime-closure AS python-runtime

ARG RUNTIME_BASE
RUN test "${RUNTIME_BASE}" = "os-base" \
    || { echo "this target builds on RUNTIME_BASE=os-base, got ${RUNTIME_BASE}" >&2; exit 1; }

FROM runtime-closure AS java-runtime

ARG RUNTIME_BASE
RUN test "${RUNTIME_BASE}" = "java-toolchain" \
    || { echo "this target needs --build-arg RUNTIME_BASE=java-toolchain, got ${RUNTIME_BASE}" >&2; exit 1; }

FROM python-runtime AS api

EXPOSE 8000

USER 10001:10001

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=5)" || exit 1

CMD ["python", "-m", "app.main"]

# The api with the Java toolchain, for stacks where coding sessions build and test Java
# repositories in the API's session workspaces (the local acceptance stack).
FROM java-runtime AS api-coding

EXPOSE 8000

USER 10001:10001

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=5)" || exit 1

CMD ["python", "-m", "app.main"]

FROM java-runtime AS code-intel-worker

RUN apt-get update \
    && apt-get install -y --no-install-recommends golang-go universal-ctags clangd nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY docker/install-code-intelligence-tools.sh /tmp/install-code-intelligence-tools.sh
RUN chmod +x /tmp/install-code-intelligence-tools.sh \
    && /tmp/install-code-intelligence-tools.sh \
    && rm -f /tmp/install-code-intelligence-tools.sh \
    && rm -rf /root/.cache /root/.npm /root/.m2 /root/go

USER 10001:10001

CMD ["python", "-m", "app.code_indexer_main"]

FROM api AS default
