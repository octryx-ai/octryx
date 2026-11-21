#!/bin/bash
# dev-start.sh — Start Octryx backend + frontend for local development.
#
# A start installs nothing and changes no venv: ./dev-setup.sh prepares the checkout, and a start
# that finds it unprepared stops and says so. The backend listens on 127.0.0.1 only, because the
# local defaults (admin/admin, placeholder secrets) must not reach the network.
# DEV_START_BACKEND_HOST=0.0.0.0, or one IPv4 address of this machine, opts into a wider bind.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend/chat"
VENV_DIR="$BACKEND_DIR/.venv"
LOG_DIR="$SCRIPT_DIR/logs"
PID_DIR="$SCRIPT_DIR/pids"

# ── Ensure log/pid dirs exist ────────────────────────────────────────────────
mkdir -p "$LOG_DIR" "$PID_DIR"

# ── colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

info()    { echo -e "${CYAN}[dev-start]${NC} $1"; }
warn()    { echo -e "${YELLOW}[dev-start] WARNING:${NC} $1"; }
success() { echo -e "${GREEN}[dev-start] ✓${NC} $1"; }
fail()    { echo -e "${RED}[dev-start] ✗${NC} $1"; }

# ── Process ownership: launch records, validated stop, port diagnostics ─────
DEV_LAUNCHER_TAG="dev-start"
# Loaded without errexit: bash 3.2 would exit inside a module that fails to load (missing file,
# CRLF checkout) before the message below could name the cause.
set +e
# shellcheck source=scripts/dev-process-ownership.sh
source "$SCRIPT_DIR/scripts/dev-process-ownership.sh"
ownership_module_status=$?
set -e
if [ "$ownership_module_status" -ne 0 ]; then
  fail "Could not load scripts/dev-process-ownership.sh (see the error above). Check it with 'bash -n scripts/dev-process-ownership.sh'; Windows CRLF line endings break it."
  exit 1
fi

# ── Migration gate: Alembic must reach the head before anything starts ───────
set +e
# shellcheck source=scripts/dev-migration-gate.sh
source "$SCRIPT_DIR/scripts/dev-migration-gate.sh"
migration_module_status=$?
set -e
# An empty or cut-off module sources without an error but lacks the gate.
if [ "$migration_module_status" -ne 0 ] || ! declare -F check_migrations >/dev/null; then
  fail "Could not load scripts/dev-migration-gate.sh (see the error above). Check it with 'bash -n scripts/dev-migration-gate.sh'; Windows CRLF line endings break it."
  exit 1
fi

# ── Backend bind address ─────────────────────────────────────────────────────
BACKEND_HOST="${DEV_START_BACKEND_HOST:-127.0.0.1}"

is_ipv4_address() {  # <text>; four dotted decimal octets, no leading zeros
  local IFS=. octet count=0
  case $1 in
    '' | *[!0-9.]* | .* | *. | *..*) return 1 ;;
  esac
  for octet in $1; do
    count=$((count + 1))
    case $octet in
      [0-9] | [1-9][0-9] | 1[0-9][0-9] | 2[0-4][0-9] | 25[0-5]) ;;
      *) return 1 ;;
    esac
  done
  [ "$count" -eq 4 ]
}

# Accepts the default or an explicit IPv4 opt-in; anything else stops the launch before it changes
# anything. A wider bind is announced, since it exposes the local-only defaults.
check_backend_host() {
  if ! is_ipv4_address "$BACKEND_HOST"; then
    dev_say error "DEV_START_BACKEND_HOST must be 127.0.0.1 (the default), 0.0.0.0 or one IPv4 address of this machine; nothing was started or stopped."
    return 1
  fi
  case $BACKEND_HOST in
    127.*) ;;
    *) dev_say warn "The backend will listen on $BACKEND_HOST (DEV_START_BACKEND_HOST): other hosts can reach it, and with it the local-only defaults (admin/admin, placeholder secrets)." ;;
  esac
}

# The address readiness probes and printed URLs use: loopback for loopback and all-interfaces binds.
backend_url_host() {
  case $BACKEND_HOST in
    127.0.0.1 | 0.0.0.0) printf '127.0.0.1' ;;
    *) printf '%s' "$BACKEND_HOST" ;;
  esac
}

# ── Check that ./dev-setup.sh has prepared this checkout ────────────────────
# Read-only: a start never installs anything or changes the venv.
check_dev_environment() {
  local problem=""
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    problem="there is no backend venv at $VENV_DIR"
  elif ! "$VENV_DIR/bin/python" -c 'import sys; sys.exit(sys.version_info < (3, 12))' >/dev/null 2>&1; then
    problem="the backend venv at $VENV_DIR does not run Python 3.12 or newer"
  # -P keeps the current directory off sys.path: backend/alembic/ must not pass for alembic.
  elif ! "$VENV_DIR/bin/python" -P -c 'import alembic, uvicorn' >/dev/null 2>&1; then
    problem="the backend venv at $VENV_DIR cannot import alembic and uvicorn"
  elif [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    problem="$FRONTEND_DIR has no node_modules"
  fi
  if [ -n "$problem" ]; then
    dev_say error "Not ready to start: $problem. Run ./dev-setup.sh, which installs what is missing, then ./dev-start.sh again. Nothing was started or stopped."
    return 1
  fi
}

start_frontend_build() {
  info "Preparing frontend build assets in backend static mount..."

  cd "$FRONTEND_DIR"

  npm run build

  # The build emits both files (vite.config.ts); the Docker image ships the same build output.
  local built_file
  for built_file in index.html admin-design-tokens.css; do
    if [ ! -f "$BACKEND_DIR/app/web/static/chat/$built_file" ]; then
      fail "Frontend build did not produce $BACKEND_DIR/app/web/static/chat/$built_file"
      return 1
    fi
  done

  success "Frontend build ready for /chat via /admin/static chat mount"
}

# ── Stop the dev servers this checkout started ───────────────────────────────
# Only processes whose launch record proves they were started from this checkout are
# signalled; stale or foreign PIDs are reported and left alone.
stop_dev_servers() {
  info "Stopping dev servers started from this checkout..."
  dev_stop_owned "Backend" "$PID_DIR/backend.pid" "$BACKEND_DIR" || return 1
  dev_stop_owned "Frontend" "$PID_DIR/frontend.pid" "$FRONTEND_DIR" || return 1
}

# ── Refuse to start next to a listener this checkout does not own ───────────
ensure_dev_ports_free() {
  local status=0
  dev_require_port_free 8000 "backend" || status=1
  dev_require_port_free 5173 "frontend" || status=1
  return "$status"
}

# ── Start backend (uvicorn with reload) ──────────────────────────────────────
# --no-proxy-headers: forwarded headers are evaluated by the application's
# validated trusted-proxy boundary (TRUSTED_PROXY_IPS), never by the
# transport layer. Direct local access over loopback is unaffected.
start_backend() {
  local url_host
  url_host=$(backend_url_host)
  info "Starting backend on http://$url_host:8000 (listening on $BACKEND_HOST) ..."

  dev_require_port_free 8000 "backend" || return 1
  dev_launch_detached "$VENV_DIR/bin/python" "$BACKEND_DIR" "$PID_DIR/backend.pid" "$LOG_DIR/backend.log" \
    "$VENV_DIR/bin/python" -m uvicorn app.main:app \
    --host "$BACKEND_HOST" \
    --port 8000 \
    --no-proxy-headers \
    --reload \
    --reload-dir app || return 1
  local backend_pid
  backend_pid=$(cat "$PID_DIR/backend.pid")

  # Wait for backend to come up; an exited process means it failed (e.g. port taken).
  info "Waiting for backend to start..."
  for _ in $(seq 1 30); do
    if ! dev_launched_process_running "$PID_DIR/backend.pid"; then
      break
    fi
    if curl -s -o /dev/null "http://$url_host:8000/api/v1/health" 2>/dev/null; then
      success "Backend started (PID $backend_pid)"
      return 0
    fi
    sleep 1
  done

  fail "Backend failed to start — see $LOG_DIR/backend.log"
  tail -20 "$LOG_DIR/backend.log" 2>/dev/null
  return 1
}

# ── Start frontend (vite dev server) ─────────────────────────────────────────
start_frontend() {
  info "Starting frontend dev server on http://localhost:5173 ..."

  # --strictPort makes vite fail instead of silently moving to another port.
  dev_require_port_free 5173 "frontend" || return 1
  dev_launch_detached "$VENV_DIR/bin/python" "$FRONTEND_DIR" "$PID_DIR/frontend.pid" "$LOG_DIR/frontend.log" \
    npm run dev -- --port 5173 --strictPort || return 1
  local frontend_pid
  frontend_pid=$(cat "$PID_DIR/frontend.pid")

  # Wait for vite to come up; an exited process means it failed.
  info "Waiting for frontend to start..."
  for _ in $(seq 1 30); do
    if ! dev_launched_process_running "$PID_DIR/frontend.pid"; then
      break
    fi
    if curl -s -o /dev/null http://localhost:5173 2>/dev/null; then
      success "Frontend started (PID $frontend_pid)"
      return 0
    fi
    sleep 1
  done

  fail "Frontend failed to start — see $LOG_DIR/frontend.log"
  tail -20 "$LOG_DIR/frontend.log" 2>/dev/null
  return 1
}

# ── Print useful URLs ────────────────────────────────────────────────────────
print_urls() {
  local url_host
  url_host=$(backend_url_host)
  echo ""
  success "Octryx is running!"
  echo ""
  echo -e "  ${CYAN}Chat:${NC}          http://$url_host:8000/chat"
  echo -e "  ${CYAN}Login:${NC}         http://$url_host:8000/chat/login"
  echo -e "  ${CYAN}Frontend (dev):${NC} http://localhost:5173/"
  echo -e "  ${CYAN}API Health:${NC}    http://$url_host:8000/api/v1/health"
  echo ""
  echo -e "  ${YELLOW}Log files:${NC}"
  echo -e "    Backend:  $LOG_DIR/backend.log"
  echo -e "    Frontend: $LOG_DIR/frontend.log"
  echo ""
  echo -e "  ${YELLOW}Stop with:${NC}  ./dev-stop.sh"
}

# ── Main ─────────────────────────────────────────────────────────────────────
# Configuration and readiness are checked before anything is stopped: a start that cannot go on
# leaves running servers alone.
check_backend_host || exit 1
check_dev_environment || exit 1
stop_dev_servers || exit 1
ensure_dev_ports_free || exit 1
check_migrations || exit 1
start_frontend_build || exit 1
start_backend || exit 1
start_frontend || exit 1
print_urls
