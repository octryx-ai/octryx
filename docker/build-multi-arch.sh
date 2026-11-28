#!/usr/bin/env bash
# ============================================================
# build-multi-arch.sh
# Build all octryx images for linux/amd64 + linux/arm64
# and push to a container registry.
#
# Supported registries:
#   - GHCR (GitHub Container Registry) — set GHCR_USER + GHCR_TOKEN
#   - ECR (AWS Elastic Container Registry) — uses AWS credentials
#   - Any other registry — set REGISTRY + ensure you are logged in
#
# Usage:
#   ./docker/build-multi-arch.sh                    # local build only (no push)
#   GHCR_USER=youruser GHCR_TOKEN=s_xxx ./docker/build-multi-arch.sh  # → ghcr.io
#   REGISTRY=123456.dkr.ecr.us-east-1.amazonaws.com ./docker/build-multi-arch.sh  # → ECR
#   SKIP_PUSH=1 PLATFORMS=linux/amd64 ./docker/build-multi-arch.sh   # single arch, local
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_DIR}"

# ── defaults ──────────────────────────────────────────────────
SKIP_PUSH="${SKIP_PUSH:-1}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
DOCKER_BUILDX_NAME="${DOCKER_BUILDX_NAME:-multiarch}"
BUILDER="${BUILDER:-desktop-linux}"   # use "desktop-linux" on macOS/Colima; "multiarch" after docker-container setup

# ── registry selection ─────────────────────────────────────────
# GHCR takes priority if GHCR_TOKEN is set
if [[ -n "${GHCR_TOKEN:-}" ]]; then
  GHCR_USER="${GHCR_USER:-$(git config --get remote.origin.url 2>/dev/null | grep -oP '(?<=:)[^/]+' | head -1)}"
  if [[ -z "${GHCR_USER}" ]]; then
    echo "ERROR: GHCR_TOKEN is set but GHCR_USER is empty and could not be auto-detected." >&2
    echo "       Set GHCR_USER explicitly: GHCR_USER=youruser GHCR_TOKEN=... ./build-multi-arch.sh" >&2
    exit 1
  fi
  REGISTRY="${REGISTRY:-ghcr.io/${GHCR_USER}/octryx}"
elif [[ -n "${REGISTRY:-}" ]]; then
  # REGISTRY already set externally — keep it
  :
else
  REGISTRY="local"
fi

DOCKERFILE="${PROJECT_DIR}/Dockerfile"

# Images: (name, dockerfile, context, target)
declare -a IMAGES=(
  "api|${DOCKERFILE}|${PROJECT_DIR}|api"
  "code-intel-worker|${DOCKERFILE}|${PROJECT_DIR}|code-intel-worker"
)

# ── login ──────────────────────────────────────────────────────
_login_ghcr() {
  if [[ -z "${GHCR_TOKEN:-}" ]]; then return 1; fi
  echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USER}" --password-stdin
  echo "    ✓ Logged into ghcr.io as ${GHCR_USER}"
}

_login_ecr() {
  if [[ "${REGISTRY}" != aws*dkr.ecr.*amazonaws.com* ]]; then return 1; fi
  local region
  region="$(echo "${REGISTRY}" | grep -oP '(?<=ecr\.)[a-z0-9-]+(?=\.amazonaws)' | head -1)"
  region="${region:-us-east-1}"
  aws ecr get-login-password --region "${region}" | docker login --username AWS --password-stdin "${REGISTRY}"
  echo "    ✓ Logged into ECR region ${region}"
}

_registry_login() {
  echo "==> Logging into registry..."
  _login_ghcr && return 0
  _login_ecr && return 0
  if [[ "${SKIP_PUSH}" != "1" ]]; then
    echo "WARNING: No registry login configured. Push will likely fail." >&2
    echo "         Set GHCR_TOKEN (+ GHCR_USER) or ensure 'docker login <registry>' was run." >&2
    sleep 2
  fi
}

# ── buildx setup ────────────────────────────────────────────────
_setup_builder() {
  if docker buildx inspect "${DOCKER_BUILDX_NAME}" &>/dev/null; then
    echo "    Builder '${DOCKER_BUILDX_NAME}' already exists."
  else
    docker buildx create \
      --driver docker-container \
      --name "${DOCKER_BUILDX_NAME}" \
      --platform "${PLATFORMS}" \
      2>/dev/null || true
  fi
  docker buildx use "${DOCKER_BUILDX_NAME}"
  docker buildx inspect --bootstrap 2>&1 | grep -v "^$" | head -5
}

# ── build + push ───────────────────────────────────────────────
echo ""
echo "============================================================"
echo " octryx — multi-arch image build"
echo "============================================================"
echo "  REGISTRY : ${REGISTRY}"
echo "  PLATFORM : ${PLATFORMS}"
echo "  SKIP_PUSH : ${SKIP_PUSH}"
echo ""

_registry_login
_setup_builder

errors=0
IFS=$'\n'
for entry in "${IMAGES[@]}"; do
  IFS='|' read -r name dockerfile context target <<< "${entry}"
  full_tag="${REGISTRY}/${name}:latest"

  echo ""
  echo "==> Building ${full_tag}"
  echo "    File   : ${dockerfile}"
  echo "    Target : ${target:-default}"

  build_cmd=(docker buildx build)
  build_cmd+=(--platform "${PLATFORMS}")
  build_cmd+=(--builder "${DOCKER_BUILDX_NAME}")

  if [[ -n "${target}" ]]; then
    build_cmd+=(--target "${target}")
  fi

  # The Java targets build on the Dockerfile's Java OS base; every target checks RUNTIME_BASE.
  if [[ "${target}" == "code-intel-worker" ]]; then
    build_cmd+=(--build-arg "RUNTIME_BASE=java-toolchain")
  fi

  if [[ "${SKIP_PUSH}" == "1" ]]; then
    build_cmd+=(--load)
    echo "    Mode   : local load only (SKIP_PUSH=1)"
  else
    build_cmd+=(--push)
    echo "    Mode   : build + push"
  fi

  build_cmd+=(
    "${context}"
    --dockerfile "${dockerfile}"
    --tag "${full_tag}"
  )

  if "${build_cmd[@]}"; then
    echo "    ✓ done"
  else
    echo "    ✗ FAILED: ${full_tag}" >&2
    errors=$((errors + 1))
  fi
done
IFS=$' \t\n'

echo ""
if (( errors > 0 )); then
  echo "==> ${errors} image(s) failed." >&2
  exit 1
fi

if [[ "${SKIP_PUSH}" == "1" ]]; then
  echo "==> All images built locally. To push:"
  echo ""
  for entry in "${IMAGES[@]}"; do
    IFS='|' read -r name _ _ _ <<< "${entry}"
    echo "   docker tag ${name}:latest ${REGISTRY}/${name}:latest"
    echo "   docker push ${REGISTRY}/${name}:latest"
  done
  echo ""
  echo "   Or run with: GHCR_USER=youruser GHCR_TOKEN=... ./docker/build-multi-arch.sh"
else
  echo "==> All images built and pushed."
fi

echo ""
echo "Image tags:"
for entry in "${IMAGES[@]}"; do
  IFS='|' read -r name _ _ _ <<< "${entry}"
  echo "  ${REGISTRY}/${name}:latest"
done
echo ""
echo "To update Kubernetes image references, run:"
echo "  ./scripts/update-registry.sh ${REGISTRY}"
echo "============================================================"