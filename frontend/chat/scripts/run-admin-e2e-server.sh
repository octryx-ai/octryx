#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH='' cd -- "$SCRIPT_DIR/../../.." && pwd)

cd "$REPO_ROOT/backend"

export OCTRYX_DISABLE_BACKGROUND_WORKERS="${OCTRYX_DISABLE_BACKGROUND_WORKERS:-1}"
export OCTRYX_DISABLE_KNOWLEDGE_EMBEDDING="${OCTRYX_DISABLE_KNOWLEDGE_EMBEDDING:-1}"
export OCTRYX_DISABLE_API_RATE_LIMIT="${OCTRYX_DISABLE_API_RATE_LIMIT:-1}"

# A worktree without its own backend venv names an interpreter and a free port.
PYTHON="${OCTRYX_E2E_PYTHON:-.venv/bin/python}"
export OCTRYX_E2E_PORT="${OCTRYX_E2E_PORT:-8000}"
# The browser's origin on that port (the attention WebSocket refuses any other origin).
export CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS:-http://127.0.0.1:$OCTRYX_E2E_PORT,http://localhost:$OCTRYX_E2E_PORT}"

# Opt-in loopback OpenAI-compatible provider stub for the unmocked Product Run
# acceptance. It lives exactly as long as this server.
if [ -n "${OCTRYX_E2E_PROVIDER_STUB_PORT:-}" ]; then
  "$PYTHON" "$SCRIPT_DIR/../tests/e2e/support/openai_compatible_stub.py" \
    --port "$OCTRYX_E2E_PROVIDER_STUB_PORT" \
    --api-key "${OCTRYX_E2E_PROVIDER_STUB_KEY:-}" &
  STUB_PID=$!
  trap 'kill "$STUB_PID" 2>/dev/null || true' EXIT
  trap 'exit 143' TERM
  trap 'exit 130' INT
fi

# proxy_headers=False: the application's trusted-proxy boundary is the
# only authority for forwarded headers.
"$PYTHON" -c "import os; from app.main import app; import uvicorn; uvicorn.run(app, host='127.0.0.1', port=int(os.environ['OCTRYX_E2E_PORT']), reload=False, proxy_headers=False, log_level='warning')"
