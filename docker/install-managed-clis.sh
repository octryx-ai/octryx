#!/usr/bin/env bash
set -euo pipefail

ENABLE_MANAGED_CLI_TOOLS="${ENABLE_MANAGED_CLI_TOOLS:-1}"
INSTALL_CLAUDE_CODE="${INSTALL_CLAUDE_CODE:-0}"
MANAGED_CLI_TOOLS="${MANAGED_CLI_TOOLS:-gemini,codex,opencode}"

if [[ "${ENABLE_MANAGED_CLI_TOOLS}" != "1" ]]; then
  echo "Skipping managed CLI installation."
  exit 0
fi

has_tool() {
  local needle=",$1,"
  local haystack=",${MANAGED_CLI_TOOLS// /},"
  [[ "${haystack}" == *"${needle}"* || "${haystack}" == *",all,"* ]]
}

packages=()
if has_tool "gemini"; then
  packages+=("@google/gemini-cli")
fi
if has_tool "codex"; then
  packages+=("@openai/codex")
fi
if has_tool "opencode"; then
  packages+=("opencode-ai")
fi

if (( ${#packages[@]} > 0 )); then
  npm_cache_dir="$(mktemp -d)"
  echo "Installing managed CLI tools: ${MANAGED_CLI_TOOLS}"
  npm install -g --cache "${npm_cache_dir}" "${packages[@]}"
  rm -rf "${npm_cache_dir}"
else
  echo "No managed CLI packages selected."
fi

if [[ "${INSTALL_CLAUDE_CODE}" == "1" ]]; then
  echo "Installing Claude Code via official installer..."
  curl -fsSL https://claude.ai/install.sh | bash
else
  echo "Skipping Claude Code install. Set INSTALL_CLAUDE_CODE=1 to enable it during docker build."
fi

echo "Installed tool versions:"
command -v gemini >/dev/null 2>&1 && gemini --version || true
command -v codex >/dev/null 2>&1 && codex --version || true
command -v opencode >/dev/null 2>&1 && opencode --version || true
command -v claude >/dev/null 2>&1 && claude --version || true
