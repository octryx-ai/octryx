#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# local-build-push.sh — Local replacement for GitHub Actions CI/CD
# Builds Docker images (linux/amd64) with Podman, pushes them to YOUR OWN
# registry, bumps the Helm chart, pushes it as OCI, and optionally
# triggers ArgoCD. Nothing is published to a shared Octryx registry.
#
# Required environment (no defaults; the script stops if one is missing):
#   OCTRYX_REGISTRY        registry host, e.g. registry.example.com
#   OCTRYX_IMAGE_BASE      image prefix, e.g. registry.example.com/team/octryx
#   OCTRYX_HELM_OCI_REPO   chart repo, e.g. oci://registry.example.com/team/octryx/helm-charts
#   OCTRYX_REGISTRY_USER   login user for the registry
# Optional: OCTRYX_REGISTRY_TOKEN (login token; on ghcr.io `gh auth token` is the fallback).
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ──
CHART_PATH="deployment/helm/octryx"
PLATFORM="linux/amd64"

# Images to build (name:target pairs from Dockerfile)
declare -a IMAGES=(
  "api:api"
)

# ── Helpers ──
log() { echo -e "\033[1;34m▸ $*\033[0m"; }
err() { echo -e "\033[1;31m✗ $*\033[0m" >&2; }
ok()  { echo -e "\033[1;32m✓ $*\033[0m"; }

# ── Parse flags ──
SKIP_BUILD=false
SKIP_PUSH=false
SKIP_HELM=false
ONLY_HELM=false
IMAGE_FILTER=""

while [[ $# -gt 0 ]]; do
  arg="$1"
  case "$arg" in
    --skip-build)  SKIP_BUILD=true ;;
    --skip-push)   SKIP_PUSH=true ;;
    --skip-helm)   SKIP_HELM=true ;;
    --only-helm)   ONLY_HELM=true ;;
    --images)
      shift
      IMAGE_FILTER="${1:-}"
      ;;
    --images=*)
      IMAGE_FILTER="${arg#--images=}"
      ;;
    --help|-h)
      echo "Usage: $0 [--skip-build] [--skip-push] [--skip-helm] [--only-helm] [--images api]"
      echo ""
      echo "  --skip-build   Skip image builds (use existing local images)"
      echo "  --skip-push    Skip pushing images to the registry"
      echo "  --skip-helm    Skip Helm chart packaging and push"
      echo "  --only-helm    Only do Helm chart (skip all image work)"
      echo "  --images       Comma-separated image names to build/push/patch"
      echo ""
      echo "Requires OCTRYX_REGISTRY, OCTRYX_IMAGE_BASE, OCTRYX_HELM_OCI_REPO and OCTRYX_REGISTRY_USER (your own registry)."
      exit 0
      ;;
    *)
      err "Unknown argument: $arg"
      exit 1
      ;;
  esac
  shift
done

if [[ -n "$IMAGE_FILTER" ]]; then
  FILTERED_IMAGES=()
  IFS=',' read -ra selected_images <<< "$IMAGE_FILTER"
  for selected in "${selected_images[@]}"; do
    selected="${selected// /}"
    found=false
    for entry in "${IMAGES[@]}"; do
      IFS=':' read -r image_name _ <<< "$entry"
      if [[ "$image_name" == "$selected" ]]; then
        FILTERED_IMAGES+=("$entry")
        found=true
        break
      fi
    done
    if [[ "$found" == "false" ]]; then
      err "Unknown image in --images: $selected"
      exit 1
    fi
  done
  IMAGES=("${FILTERED_IMAGES[@]}")
fi

# ── Registry configuration (environment only, never in the repository) ──
missing_config=()
for name in OCTRYX_REGISTRY OCTRYX_IMAGE_BASE OCTRYX_HELM_OCI_REPO OCTRYX_REGISTRY_USER; do
  [[ -n "${!name:-}" ]] || missing_config+=("$name")
done
if (( ${#missing_config[@]} > 0 )); then
  err "Set ${missing_config[*]} to your own registry (see the header of $0). There is no default and no shared Octryx registry."
  exit 1
fi
REGISTRY="$OCTRYX_REGISTRY"
IMAGE_BASE="$OCTRYX_IMAGE_BASE"
HELM_OCI_REPO="$OCTRYX_HELM_OCI_REPO"
REGISTRY_USER="$OCTRYX_REGISTRY_USER"

registry_token() {
  if [[ -n "${OCTRYX_REGISTRY_TOKEN:-}" ]]; then
    printf '%s' "$OCTRYX_REGISTRY_TOKEN"
    return 0
  fi
  if [[ "$REGISTRY" == "ghcr.io" ]] && command -v gh &>/dev/null; then
    gh auth token 2>/dev/null || true
  fi
}

patch_values_image() {
  local values_file="$1"
  local component="$2"
  local repository="$3"
  local tag="$4"
  local digest="$5"

  python3 - "$values_file" "$component" "$repository" "$tag" "$digest" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

path = Path(sys.argv[1])
component = sys.argv[2]
repository = sys.argv[3]
tag = sys.argv[4]
digest = sys.argv[5]

text = path.read_text()
lines = text.splitlines(keepends=True)
newline = "\r\n" if "\r\n" in text else "\n"

images_idx = next((i for i, line in enumerate(lines) if line.startswith("images:")), None)
if images_idx is None:
    raise SystemExit(f"{path}: missing images block")

component_idx = None
for idx in range(images_idx + 1, len(lines)):
    line = lines[idx]
    if line and not line.startswith((" ", "\t")):
        break
    if line.startswith(f"  {component}:"):
        component_idx = idx
        break
if component_idx is None:
    raise SystemExit(f"{path}: missing images.{component} block")

end_idx = len(lines)
for idx in range(component_idx + 1, len(lines)):
    line = lines[idx]
    if line.startswith("  ") and not line.startswith("    "):
        end_idx = idx
        break
    if line and not line.startswith((" ", "\t")):
        end_idx = idx
        break

block = lines[component_idx + 1 : end_idx]
updates = {
    "repository": f"    repository: {repository}{newline}",
    "tag": f'    tag: "{tag}"{newline}',
    "digest": f'    digest: "{digest}"{newline}',
}
seen: set[str] = set()
updated_block: list[str] = []
for line in block:
    stripped = line.strip()
    key = stripped.split(":", 1)[0] if ":" in stripped else ""
    if key in updates:
        updated_block.append(updates[key])
        seen.add(key)
    else:
        updated_block.append(line)

insert_at = 0
for idx, line in enumerate(updated_block):
    if line.strip().startswith("tag:"):
        insert_at = idx + 1
        break
else:
    for idx, line in enumerate(updated_block):
        if line.strip().startswith("repository:"):
            insert_at = idx + 1
            break

for key in ("repository", "tag", "digest"):
    if key not in seen:
        updated_block.insert(insert_at, updates[key])
        insert_at += 1

lines[component_idx + 1 : end_idx] = updated_block
path.write_text("".join(lines))
PY
}

# ── Ensure registry login ──
ensure_login() {
  if ! podman login --get-login "$REGISTRY" &>/dev/null; then
    token="$(registry_token)"
    if [[ -z "$token" ]]; then
      err "Not logged in to $REGISTRY. Set OCTRYX_REGISTRY_TOKEN or run: podman login $REGISTRY -u $REGISTRY_USER"
      exit 1
    fi
    echo "$token" | podman login "$REGISTRY" -u "$REGISTRY_USER" --password-stdin
  fi
  ok "Logged in to $REGISTRY"
}

# ── Get short SHA ──
SHORT_SHA=$(git rev-parse --short=12 HEAD)
log "Git SHA: $SHORT_SHA"

# ── Change to repo root ──
cd "$(git rev-parse --show-toplevel)"

# ═══════════════════════════════════════════════════════════════════════
# PHASE 1: Build & Push Images
# ═══════════════════════════════════════════════════════════════════════
if [[ "$ONLY_HELM" == "false" ]]; then
  ensure_login

  DIGEST_NAMES=()
  DIGEST_VALUES=()

  remember_digest() {
    DIGEST_NAMES+=("$1")
    DIGEST_VALUES+=("$2")
  }

  lookup_digest() {
    local wanted="$1"
    local idx
    for idx in "${!DIGEST_NAMES[@]}"; do
      if [[ "${DIGEST_NAMES[$idx]}" == "$wanted" ]]; then
        printf '%s' "${DIGEST_VALUES[$idx]}"
        return 0
      fi
    done
  }

  for entry in "${IMAGES[@]}"; do
    IFS=':' read -r name target <<< "$entry"
    tag="${IMAGE_BASE}/${name}:latest"
    sha_tag="${IMAGE_BASE}/${name}:${SHORT_SHA}"

    # Build
    if [[ "$SKIP_BUILD" == "false" ]]; then
      log "Building ${name} (target=${target}, platform=${PLATFORM})..."
      podman build \
        --platform "$PLATFORM" \
        --target "$target" \
        -t "$tag" \
        -t "$sha_tag" \
        -f ./Dockerfile . 2>&1 | tail -5
      ok "Built ${name}"
    fi

    # Push
    digest=""
    if [[ "$SKIP_PUSH" == "false" ]]; then
      log "Pushing ${name}..."
      digest_file="$(mktemp)"
      podman push "$tag" --digestfile "$digest_file" 2>&1 | tail -3
      digest="$(cat "$digest_file" 2>/dev/null || true)"
      rm -f "$digest_file"
      digest_file="$(mktemp)"
      podman push "$sha_tag" --digestfile "$digest_file" 2>&1 | tail -3
      if [[ -z "$digest" ]]; then
        digest="$(cat "$digest_file" 2>/dev/null || true)"
      fi
      rm -f "$digest_file"
      ok "Pushed ${name}"
    fi

    if [[ -z "${digest:-}" ]]; then
      digest=$(podman inspect "$tag" --format '{{.Digest}}' 2>/dev/null || true)
    fi
    remember_digest "$name" "$digest"
    log "  ${name} digest: ${digest}"
  done

  # ── Patch values files with new digests ──
  log "Patching Helm values with new digests..."
  values_file="$CHART_PATH/values.yaml"
  for entry in "${IMAGES[@]}"; do
    IFS=':' read -r name target <<< "$entry"
    digest="$(lookup_digest "$name")"
    if [[ -n "$digest" ]]; then
      case "$name" in
        api) component="api" ;;
        code-intel-worker) component="codeIndexer" ;;
        *) err "Unknown image component: $name"; exit 1 ;;
      esac
      # The chart deploys the API only; worker images are built for Compose and are not in its values.
      if ! grep -q "^  ${component}:" "$values_file"; then
        log "  ${name}: no images.${component} block in $(basename "$values_file"), not patched"
        continue
      fi
      patch_values_image "$values_file" "$component" "${IMAGE_BASE}/${name}" "$SHORT_SHA" "$digest"
    fi
  done
  ok "Values files patched"
fi

# ═══════════════════════════════════════════════════════════════════════
# PHASE 2: Helm Chart Package & Push
# ═══════════════════════════════════════════════════════════════════════
if [[ "$SKIP_HELM" == "false" ]]; then
  log "Logging Helm into OCI registry..."
  container_auth="${HOME}/.config/containers/auth.json"
  if [[ -f "$container_auth" ]] && grep -q "\"${REGISTRY}\"" "$container_auth"; then
    export HELM_REGISTRY_CONFIG="$container_auth"
    ok "Using container registry auth for Helm"
  else
    token="$(registry_token)"
    if [[ -z "$token" ]]; then
      err "Helm registry login failed. Set OCTRYX_REGISTRY_TOKEN or run: podman login $REGISTRY -u $REGISTRY_USER"
      exit 1
    fi
    echo "$token" | helm registry login "$REGISTRY" --username "$REGISTRY_USER" --password-stdin
  fi

  # Read current version
  CURRENT_VERSION=$(grep '^version:' "$CHART_PATH/Chart.yaml" | awk '{print $2}' | tr -d '"\r')
  # A pre-release suffix (0.0.1-alpha) stays; only the patch number counts up.
  CORE_VERSION=${CURRENT_VERSION%%-*}
  PRERELEASE=${CURRENT_VERSION#"$CORE_VERSION"}
  MAJOR_MINOR=$(echo "$CORE_VERSION" | cut -d. -f1,2)

  # Query ALL tags from OCI and find the highest patch for our major.minor
  LATEST_PATCH=""
  if command -v crane &>/dev/null; then
    LATEST_PATCH=$(crane ls "${HELM_OCI_REPO#oci://}/octryx" 2>/dev/null \
      | grep "^${MAJOR_MINOR}\." | sed 's/-.*//' | sort -t. -k3 -n | tail -1 | cut -d. -f3 || true)
  fi
  # Fallback: try helm show chart for the latest
  if [[ -z "$LATEST_PATCH" ]]; then
    LATEST_PATCH=$(helm show chart "$HELM_OCI_REPO/octryx" 2>/dev/null \
      | grep '^version:' | awk '{print $2}' | tr -d '\r' | sed 's/-.*//' | cut -d. -f3 || true)
  fi

  if [[ -z "$LATEST_PATCH" ]]; then
    # Last resort: use local Chart.yaml patch
    LATEST_PATCH=$(echo "$CORE_VERSION" | tr -d '\r' | cut -d. -f3)
  fi
  NEXT_PATCH=$((LATEST_PATCH + 1))
  NEW_VERSION="${MAJOR_MINOR}.${NEXT_PATCH}${PRERELEASE}"

  log "Chart version: ${CURRENT_VERSION} → ${NEW_VERSION}"

  # Update Chart.yaml
  # appVersion is the product's version (Chart.yaml); the images carry the commit in their tag.
  sed -i '' "s|^version:.*|version: ${NEW_VERSION}|" "$CHART_PATH/Chart.yaml"

  # Package
  log "Checking release values secret containment..."
  python3 "$(dirname "$0")/check_release_values_secrets.py" --root "$(git rev-parse --show-toplevel)"

  # Directory-level gate: helm packages what is on disk, including untracked and
  # git-ignored files, so inspect the exact chart path right before packaging.
  log "Inspecting chart package inputs..."
  python3 "$(dirname "$0")/check_chart_package_inputs.py" "$CHART_PATH"

  log "Packaging Helm chart..."
  helm package "$CHART_PATH"
  PKG=$(printf '%s\n' octryx-*.tgz | sort -V | tail -1)
  if [[ ! -f "$PKG" ]]; then
    err "helm package produced no octryx-*.tgz archive"
    exit 1
  fi
  ok "Packaged: $PKG"

  # Push
  log "Pushing Helm chart to OCI..."
  helm push "$PKG" "$HELM_OCI_REPO"
  ok "Pushed chart ${NEW_VERSION} to OCI"

  # Cleanup
  rm -f "$PKG"

  echo ""
  ok "Done! Chart ${NEW_VERSION} pushed. ArgoCD should pick up the new version."
  echo "   If auto-sync is disabled, run:"
  echo "   argocd app sync octryx --revision ${NEW_VERSION}"
fi
