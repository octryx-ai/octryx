#!/usr/bin/env bash
# ============================================================
# update-registry.sh
# Update all image references in Kubernetes manifests and Helm
# values to point at a new registry.
#
# Usage:
#   ./scripts/update-registry.sh ghcr.io/myuser/octryx
#   ./scripts/update-registry.sh 123456.dkr.ecr.us-east-1.amazonaws.com/octryx
# ============================================================
set -euo pipefail

NEW_REGISTRY="${1:-}"
if [[ -z "${NEW_REGISTRY}" ]]; then
  echo "Usage: $0 <registry>" >&2
  echo "  e.g. $0 ghcr.io/myuser/octryx" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEPLOY="${PROJECT_DIR}/deploy"
DOCKER="${PROJECT_DIR}/docker"

echo "==> Updating image registry → ${NEW_REGISTRY}"
echo ""

# ── K8s kustomization overlays ────────────────────────────────
for kustomization in \
  "${DEPLOY}/kubernetes/overlays/local/kustomization.yaml" \
  "${DEPLOY}/kubernetes/overlays/eks/kustomization.yaml"; do
  if [[ ! -f "${kustomization}" ]]; then continue; fi
  echo "  ${kustomization}"
  # Replace image newName entries with the new registry prefix
  sed -i.bak \
    -e "s|newName: octryx-api|newName: ${NEW_REGISTRY}/api|g" \
    -e "s|newName: octryx-agent-worker|newName: ${NEW_REGISTRY}/agent-worker|g" \
    -e "s|newName: octryx-code-intel-worker|newName: ${NEW_REGISTRY}/code-intel-worker|g" \
    "${kustomization}"
  rm -f "${kustomization}.bak"
done

# ── Helm values.yaml ───────────────────────────────────────────
VALUES="${DEPLOY}/helm/octryx/values.yaml"
if [[ -f "${VALUES}" ]]; then
  echo "  ${VALUES}"
  sed -i.bak \
    -e "s|repository: octryx-api|repository: ${NEW_REGISTRY}/api|g" \
    "${VALUES}"
  rm -f "${VALUES}.bak"
fi

# ── Base manifests (image names in yaml) ───────────────────────
for yaml in \
  "${DEPLOY}/kubernetes/base/api.yaml" \
  "${DEPLOY}/kubernetes/base/platform-worker.yaml" \
  "${DEPLOY}/kubernetes/base/code-indexer.yaml" \
  "${DEPLOY}/kubernetes/base/optional-cli-workers.yaml"; do
  if [[ ! -f "${yaml}" ]]; then continue; fi
  echo "  ${yaml}"
  # Replace bare image: references
  sed -i.bak \
    -e "s|image: octryx-api:latest|image: ${NEW_REGISTRY}/api:latest|g" \
    -e "s|image: octryx-agent-worker:latest|image: ${NEW_REGISTRY}/agent-worker:latest|g" \
    -e "s|image: octryx-code-intel-worker:latest|image: ${NEW_REGISTRY}/code-intel-worker:latest|g" \
    -e "s|image: octryx-codex-worker:latest|image: ${NEW_REGISTRY}/codex-worker:latest|g" \
    -e "s|image: octryx-gemini-worker:latest|image: ${NEW_REGISTRY}/gemini-worker:latest|g" \
    -e "s|image: octryx-opencode-worker:latest|image: ${NEW_REGISTRY}/opencode-worker:latest|g" \
    "${yaml}"
  rm -f "${yaml}.bak"
done

echo ""
echo "==> Done. Commit the changes and deploy with:"
echo "    kubectl apply -k ${DEPLOY}/kubernetes/overlays/eks"
echo "    # or"
echo "    helm upgrade --install octryx ${DEPLOY}/helm/octryx \\"
echo "      --set image.repository=${NEW_REGISTRY}/api"