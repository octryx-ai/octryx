#!/usr/bin/env bash
# Local LiteLLM data-plane qualification.
#
# Generates throwaway TLS material and a throwaway virtual key outside the
# repository, runs the product qualification against the deterministic
# LiteLLM-compatible fixture in this directory over real loopback sockets, then
# removes everything it created.
#
# Nothing here contacts AWS, EKS, a staging cluster, a shared environment, or the cluster
# LiteLLM service. It does not deploy anything. The virtual key and the TLS
# private key exist for the duration of one run and are never printed.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../../.." && pwd)"

# Backend interpreter. Worktrees have no own venv, so an explicit override is
# supported; the default is the repository backend environment.
PYTHON="${OCTRYX_PYTHON:-${REPO_ROOT}/backend/.venv/bin/python}"
if [[ ! -x "${PYTHON}" ]]; then
  echo "Backend interpreter not found. Set OCTRYX_PYTHON to a Python 3.12 environment with httpx and cryptography." >&2
  exit 2
fi

TLS_DIR="$(mktemp -d "${TMPDIR:-/tmp}/octryx-litellm-fixture-XXXXXX")"
chmod 700 "${TLS_DIR}"

cleanup() {
  rm -rf "${TLS_DIR}"
}
trap cleanup EXIT INT TERM

# A fresh test-only virtual key per run, never written to a file in the repository.
#
# Generated through the interpreter rather than a `tr </dev/urandom | head`
# pipeline: under `pipefail` that pipeline exits 141, because `head` closes the
# pipe and `tr` dies on SIGPIPE, so the whole run would abort. The command
# substitution below is a single process with no pipe, so `pipefail` has nothing
# to trip on, and `set -e` already aborts if the interpreter fails.
#
# The result is then validated rather than trusted: a substitution that produced
# nothing would otherwise hand the fixture an empty bearer token and turn a
# credential check into a vacuous one.
VIRTUAL_KEY="sk-fixture-$("${PYTHON}" -c 'import secrets; print(secrets.token_hex(16))')"
if [[ ! "${VIRTUAL_KEY}" =~ ^sk-fixture-[0-9a-f]{32}$ ]]; then
  echo "Virtual key generation failed. Check the interpreter set in OCTRYX_PYTHON." >&2
  exit 2
fi

echo "LiteLLM gateway qualification fixture"
echo "  interpreter : ${PYTHON}"
echo "  tls material: ${TLS_DIR} (removed on exit)"
echo

cd "${HERE}"
# The fixture is an isolated local contract harness and intentionally uses the
# repository's documented non-production bootstrap profile. The flag is scoped
# to this subprocess; it is never exported to a deployed service or shared
# environment.
DEBUG=true OCTRYX_FIXTURE_TLS_DIR="${TLS_DIR}" OCTRYX_FIXTURE_VIRTUAL_KEY="${VIRTUAL_KEY}" "${PYTHON}" qualification_smoke.py
