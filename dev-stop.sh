#!/bin/bash
# dev-stop.sh — Stop the Octryx dev servers that ./dev-start.sh started from this checkout.
# Processes this checkout cannot prove it started are reported and left running.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$SCRIPT_DIR/pids"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend/chat"

DEV_LAUNCHER_TAG="dev-stop"
# shellcheck source=scripts/dev-process-ownership.sh
source "$SCRIPT_DIR/scripts/dev-process-ownership.sh" || {
  echo "[dev-stop] Could not load scripts/dev-process-ownership.sh (see the error above). Check it with 'bash -n scripts/dev-process-ownership.sh'; Windows CRLF line endings break it." >&2
  exit 1
}

dev_say info "Stopping dev servers started from this checkout..."

status=0
dev_stop_owned "Backend" "$PID_DIR/backend.pid" "$BACKEND_DIR" || status=1
dev_stop_owned "Frontend" "$PID_DIR/frontend.pid" "$FRONTEND_DIR" || status=1

# Report, never signal, whatever else still listens on the dev ports.
dev_report_port_listeners 8000 "backend"
dev_report_port_listeners 5173 "frontend"

if [ "$status" -eq 0 ]; then
  dev_say ok "Done."
else
  dev_say error "Some dev servers could not be stopped; see above."
fi
exit "$status"
