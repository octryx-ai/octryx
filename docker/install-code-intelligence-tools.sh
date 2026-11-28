#!/usr/bin/env bash
set -euo pipefail

echo "[code-intel] installing optional code intelligence toolchain"

INSTALL_BIN_DIR="${INSTALL_BIN_DIR:-/usr/local/bin}"
TOOL_CACHE_ROOT="${TOOL_CACHE_ROOT:-/opt/octryx}"
mkdir -p "${INSTALL_BIN_DIR}" "${TOOL_CACHE_ROOT}"

if command -v go >/dev/null 2>&1; then
  go_cache_dir="$(mktemp -d)"
  go_mod_dir="$(mktemp -d)"
  export GOCACHE="${go_cache_dir}"
  export GOMODCACHE="${go_mod_dir}"
  zoekt_version="${ZOEKT_VERSION:-latest}"
  GOBIN="${INSTALL_BIN_DIR}" go install "github.com/sourcegraph/zoekt/cmd/zoekt-index@${zoekt_version}"
  GOBIN="${INSTALL_BIN_DIR}" go install "github.com/sourcegraph/zoekt/cmd/zoekt-git-index@${zoekt_version}"
  GOBIN="${INSTALL_BIN_DIR}" go install "github.com/sourcegraph/zoekt/cmd/zoekt@${zoekt_version}"
  GOBIN="${INSTALL_BIN_DIR}" go install "github.com/sourcegraph/zoekt/cmd/zoekt-webserver@${zoekt_version}"
  rm -rf "${go_cache_dir}" "${go_mod_dir}"
else
  echo "[code-intel] go is required to install Zoekt binaries" >&2
  exit 1
fi

for binary in zoekt-index zoekt-git-index zoekt zoekt-webserver; do
  if ! command -v "${binary}" >/dev/null 2>&1; then
    echo "[code-intel] required Zoekt binary missing after install: ${binary}" >&2
    exit 1
  fi
done

if command -v npm >/dev/null 2>&1; then
  npm_cache_dir="$(mktemp -d)"
  npm install -g --cache "${npm_cache_dir}" tree-sitter-cli || true
  rm -rf "${npm_cache_dir}"
fi

echo "[code-intel] installation complete"
