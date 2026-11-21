#!/usr/bin/env bash
# Deterministic lifecycle for the local S3-compatible object-store fixture
# (SeaweedFS 4.47, deployment/local/object-store).
#
# Usage (from this directory):
#   ./fixture.sh              # provision -> up -> ready -> smoke -> down (cleanup always runs)
#   ./fixture.sh up           # provision identities, start the runtime, wait for liveness
#   ./fixture.sh smoke        # run the product smoke against an already started runtime
#   ./fixture.sh down         # stop, remove and verify that nothing is left behind
#
# Optional inputs:
#   OBJECT_STORE_S3_PORT      loopback host port for the S3 API (default 8333)
#   OBJECT_STORE_STATE_DIR    directory for the generated identity file
#                             (default $HOME/.config/octryx/object-store)
#   OBJECT_STORE_PYTHON       interpreter for the product smoke
#                             (default ../../../backend/.venv/bin/python)
#
# Fail-closed by design: a missing container runtime, an unavailable image, a runtime
# that does not become live, a product-smoke failure, or a cleanup that leaves a
# container, volume or network behind all exit non-zero. Nothing is skipped silently.
#
# Credentials: every run generates fresh random secret keys into a 0600 file outside
# the repository and deletes them again on cleanup. There is no persistent state to
# keep access to, because all fixture data lives in the container's tmpfs. The secret
# keys are never printed, never passed on a command line and never put in the
# environment. Do not run this script with `bash -x`.
set -euo pipefail
umask 077

readonly project="octryx-object-store"
readonly image_digest="sha256:ce9e796f1fe6f06968f4c04bdaf8f678dad9c8acdfef3d244133d71bfa6bf882"

# Fixed, unmistakably local identity and bucket names. product_smoke.py carries the
# same constants and refuses to run when the generated file does not match them, so
# the two sides cannot drift apart.
readonly admin_identity="octryx-local-smoke-fixture-admin"
readonly client_identity="octryx-local-smoke-knowledge-client"
readonly denied_identity="octryx-local-smoke-denied-client"
# The operator-owned reconciliation identity: it may list and delete inside
# the bucket and deliberately holds no Read grant, so it cannot read Workspace bytes at all.
readonly retention_identity="octryx-local-smoke-retention-client"
readonly bucket="octryx-local-smoke-knowledge"
readonly absent_bucket="octryx-local-smoke-knowledge-absent"
readonly unrelated_bucket="octryx-local-smoke-unrelated"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly script_dir

fail() {
  printf 'FAIL %s\n' "$1" >&2
  exit 1
}

pass() {
  printf 'PASS %s\n' "$1"
}

step() {
  printf -- '--- %s\n' "$1"
}

readonly port="${OBJECT_STORE_S3_PORT:-8333}"
case "$port" in
  '' | *[!0-9]*) fail "OBJECT_STORE_S3_PORT must be a decimal port" ;;
esac
[ "$port" -ge 1 ] && [ "$port" -le 65535 ] || fail "OBJECT_STORE_S3_PORT out of range"

repo_root="$(git -C "$script_dir" rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$repo_root" ] && repo_root="$(cd "$repo_root" && pwd -P)"

state_dir="${OBJECT_STORE_STATE_DIR:-${HOME:-}/.config/octryx/object-store}"
case "$state_dir" in
  /*) ;;
  *) fail "OBJECT_STORE_STATE_DIR must be an absolute path" ;;
esac
readonly state_dir
readonly identities_file="$state_dir/object-store-identities.json"

python_bin="${OBJECT_STORE_PYTHON:-$script_dir/../../../backend/.venv/bin/python}"
readonly python_bin

compose() {
  OBJECT_STORE_IDENTITIES_FILE="$identities_file" \
  OBJECT_STORE_S3_PORT="$port" \
    docker compose -f "$script_dir/compose.yaml" "$@"
}

require_runtime() {
  command -v docker >/dev/null 2>&1 || fail "docker is required (Docker or Podman with a docker shim)"
  docker version --format '{{.Server.Version}}' >/dev/null 2>&1 ||
    fail "no reachable container runtime; start Docker/Rancher Desktop first"
  docker compose version >/dev/null 2>&1 || fail "docker compose v2 is required"
}

# provision writes the SeaweedFS S3 identity file. Actions are the narrowest the
# server can express: the product identity gets Read+Write on its own bucket and on
# the deliberately absent bucket, and nothing global. See README.md for what SeaweedFS
# cannot express and what the product actually needs on AWS S3.
provision() {
  [ -n "${HOME:-}" ] || [ -n "${OBJECT_STORE_STATE_DIR:-}" ] ||
    fail "neither HOME nor OBJECT_STORE_STATE_DIR is set"
  if [ -n "$repo_root" ]; then
    case "$state_dir/" in
      "$repo_root"/*) fail "OBJECT_STORE_STATE_DIR must live outside the repository" ;;
    esac
  fi
  command -v openssl >/dev/null 2>&1 || fail "openssl is required to generate test-only secret keys"
  # -m on `mkdir -p` would only apply to the deepest directory, so the mode is set
  # explicitly instead of relying on the umask above for it.
  mkdir -p "$state_dir" || fail "cannot create the state directory"
  chmod 700 "$state_dir" || fail "cannot restrict the state directory"

  local admin_secret client_secret denied_secret retention_secret
  admin_secret="$(openssl rand -hex 24)"
  client_secret="$(openssl rand -hex 24)"
  denied_secret="$(openssl rand -hex 24)"
  retention_secret="$(openssl rand -hex 24)"
  for value in "$admin_secret" "$client_secret" "$denied_secret" "$retention_secret"; do
    case "$value" in
      [0-9a-f]*) [ "${#value}" -eq 48 ] || fail "generated secret key has an unexpected length" ;;
      *) fail "generated secret key is not hexadecimal" ;;
    esac
  done

  # Written through a shell builtin into a 0600 file: the secrets never reach argv.
  rm -f "$identities_file"
  (
    umask 077
    {
      printf '{\n  "identities": [\n'
      printf '    {"name": "%s", "credentials": [{"accessKey": "%s", "secretKey": "%s"}], "actions": ["Admin", "Read", "Write", "List"]},\n' \
        "$admin_identity" "$admin_identity" "$admin_secret"
      printf '    {"name": "%s", "credentials": [{"accessKey": "%s", "secretKey": "%s"}], "actions": ["Read:%s", "Write:%s", "Read:%s", "Write:%s"]},\n' \
        "$client_identity" "$client_identity" "$client_secret" \
        "$bucket" "$bucket" "$absent_bucket" "$absent_bucket"
      printf '    {"name": "%s", "credentials": [{"accessKey": "%s", "secretKey": "%s"}], "actions": ["Read:%s", "Write:%s"]},\n' \
        "$denied_identity" "$denied_identity" "$denied_secret" \
        "$unrelated_bucket" "$unrelated_bucket"
      # List + Write, never Read: SeaweedFS has no separate delete action, so Write is the
      # narrowest grant that authorizes DeleteObject here (README records the divergence
      # from the IAM policy the product actually needs).
      printf '    {"name": "%s", "credentials": [{"accessKey": "%s", "secretKey": "%s"}], "actions": ["List:%s", "Write:%s"]}\n' \
        "$retention_identity" "$retention_identity" "$retention_secret" \
        "$bucket" "$bucket"
      printf '  ]\n}\n'
    } >"$identities_file"
  )
  unset admin_secret client_secret denied_secret retention_secret
  [ -s "$identities_file" ] || fail "identity file was not written"
  pass "identities: generated fresh test-only keys in a 0600 file outside the repository"
}

up() {
  require_runtime
  provision
  step "starting $project (image pinned to $image_digest)"
  compose config --quiet || fail "compose configuration does not render"
  # Always recreated: every start provisions fresh credentials, and the server reads
  # the identity file once at start-up, so reusing a running container would leave it
  # authenticating the previous run's keys. All data is tmpfs, so nothing is lost.
  compose up -d --force-recreate --wait --wait-timeout 180 >/dev/null ||
    fail "the object-store runtime did not become live"
  local container running_digest
  container="$(compose ps -q object-store)"
  [ -n "$container" ] || fail "no object-store container is running"
  running_digest="$(docker inspect "$container" --format '{{index .Image}}' 2>/dev/null || true)"
  [ "$running_digest" = "$image_digest" ] ||
    fail "the running container does not use the pinned image digest"
  pass "runtime: live and healthy on 127.0.0.1:$port, pinned image digest confirmed"
}

smoke() {
  [ -x "$python_bin" ] || fail "product smoke interpreter not found; set OBJECT_STORE_PYTHON"
  # Checked before the smoke runs so an unusable interpreter fails with a fixed line
  # instead of letting an arbitrary traceback reach the output.
  "$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
    >/dev/null 2>&1 || fail "product smoke interpreter is older than Python 3.11"
  "$python_bin" -c 'import boto3' >/dev/null 2>&1 ||
    fail "product smoke interpreter has no boto3; use the backend virtualenv"
  [ -f "$identities_file" ] || fail "no identity file; run ./fixture.sh up first"
  step "running the product smoke against the real KnowledgeObjectStore"
  OBJECT_STORE_S3_PORT="$port" \
  OBJECT_STORE_IDENTITIES_FILE="$identities_file" \
    "$python_bin" -B "$script_dir/product_smoke.py" || fail "the product smoke did not pass"
}

# down removes the container, its network and any volume of this Compose project, then
# proves that none of them survived. The fixture keeps no data outside the container.
down() {
  require_runtime
  step "removing $project and verifying that nothing is left behind"
  compose down --volumes --remove-orphans --timeout 10 >/dev/null 2>&1 || true
  local leftover
  for kind in container volume network; do
    case "$kind" in
      container) leftover="$(docker ps -aq --filter "label=com.docker.compose.project=$project" | tr -d '[:space:]')" ;;
      volume) leftover="$(docker volume ls -q --filter "label=com.docker.compose.project=$project" | tr -d '[:space:]')" ;;
      network) leftover="$(docker network ls -q --filter "label=com.docker.compose.project=$project" | tr -d '[:space:]')" ;;
    esac
    [ -z "$leftover" ] || fail "cleanup left a $kind of $project behind"
  done
  rm -f "$identities_file"
  [ -e "$identities_file" ] && fail "cleanup could not remove the identity file"
  rmdir "$state_dir" 2>/dev/null || true
  pass "cleanup: no container, volume, network or generated credential of $project remains"
}

case "${1:-all}" in
  up) up ;;
  smoke) smoke ;;
  down) down ;;
  all)
    # The trap is armed before anything is created, so a failure inside up() cleans up
    # too. require_runtime runs first so a missing runtime fails once, not twice.
    require_runtime
    trap down EXIT
    up
    smoke
    trap - EXIT
    down
    pass "fixture: start, readiness, product smoke and cleanup all passed"
    ;;
  *) fail "usage: ./fixture.sh [all|up|smoke|down]" ;;
esac
