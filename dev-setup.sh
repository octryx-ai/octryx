#!/bin/bash
# dev-setup.sh — Prepare this checkout for ./dev-start.sh: backend venv and frontend packages.
#
# The explicit, networked counterpart of the deterministic start: it installs and
# reports every change it makes. It never deletes a venv and never starts, stops or migrates
# anything.
#
# The backend closure comes from backend/uv.lock, installed with `uv sync --locked`,
# which is exact: it removes what the lock does not name.
#
#   DEV_SETUP_PYTHON      interpreter for a new venv (default: Homebrew Python 3.14, else python3)
#   DEV_SETUP_UV_VERSION  the pinned uv (default: the version Dockerfile's python-deps stage uses)
#   DEV_SETUP_EXTRAS      comma-separated extras to sync (default: dev,knowledge)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend/chat"
VENV_DIR="$BACKEND_DIR/.venv"
PYTHON_BIN="${DEV_SETUP_PYTHON:-/opt/homebrew/bin/python3.14}"
if [ -z "${DEV_SETUP_PYTHON:-}" ] && [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

say() { printf '[dev-setup] %s\n' "$1"; }
fail() { printf '[dev-setup] ✗ %s\n' "$1"; }

VERSION_CHECK='import sys; sys.exit(sys.version_info < (3, 12))'
if [ -e "$VENV_DIR" ]; then
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    problem="has no bin/python (a half-created venv?)"
  elif ! "$VENV_DIR/bin/python" -c "$VERSION_CHECK" >/dev/null 2>&1; then
    problem="does not run Python 3.12 or newer"
  else
    problem=""
  fi
  if [ -n "$problem" ]; then
    fail "The venv at $VENV_DIR $problem. It is never deleted automatically: remove it yourself (rm -rf \"$VENV_DIR\"), then run ./dev-setup.sh again."
    exit 1
  fi
  say "Using the existing venv at $VENV_DIR."
else
  # A venv on an older interpreter would be refused by ./dev-start.sh and kept by this script.
  if ! "$PYTHON_BIN" -c "$VERSION_CHECK" >/dev/null 2>&1; then
    fail "$PYTHON_BIN is not Python 3.12 or newer; name one with DEV_SETUP_PYTHON=<path to python3.12+>. No venv was created."
    exit 1
  fi
  say "Creating a venv at $VENV_DIR with $PYTHON_BIN..."
  if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
    fail "Could not create the venv at $VENV_DIR with $PYTHON_BIN."
    exit 1
  fi
fi

# backend/uv.lock is the authoritative description of the backend closure, so the
# local venv is installed from it rather than from a fresh resolution of the declared ranges.
# `uv sync --locked` refuses a stale lock instead of resolving around it, and it pins the same
# versions the image installs, so a developer's lxml can no longer differ from the shipped one.
#
# uv is pinned to the reviewed version, the same one Dockerfile's python-deps stage uses. A uv
# on PATH is accepted only at that exact version; otherwise the pin is installed into a
# bootstrap venv of its own, which keeps uv out of the backend venv that `uv sync` then keeps
# exact.
UV_VERSION="${DEV_SETUP_UV_VERSION:-0.12.19}"
UV_BOOTSTRAP_DIR="$SCRIPT_DIR/.tools/uv-$UV_VERSION"

uv_version_of() { "$1" --version 2>/dev/null | awk 'NR == 1 { print $2 }'; }

UV_BIN=""
if command -v uv >/dev/null 2>&1 && [ "$(uv_version_of uv)" = "$UV_VERSION" ]; then
  UV_BIN="$(command -v uv)"
  say "Using uv $UV_VERSION from PATH ($UV_BIN)."
elif [ -x "$UV_BOOTSTRAP_DIR/bin/uv" ] && [ "$(uv_version_of "$UV_BOOTSTRAP_DIR/bin/uv")" = "$UV_VERSION" ]; then
  UV_BIN="$UV_BOOTSTRAP_DIR/bin/uv"
  say "Using the pinned uv $UV_VERSION at $UV_BIN."
else
  say "Installing the pinned uv $UV_VERSION into $UV_BOOTSTRAP_DIR (kept out of $VENV_DIR)..."
  # python -m venv seeds its own pip, so this does not depend on pip inside $VENV_DIR.
  if ! "$VENV_DIR/bin/python" -m venv "$UV_BOOTSTRAP_DIR"; then
    fail "Could not create the uv bootstrap venv at $UV_BOOTSTRAP_DIR."
    exit 1
  fi
  if ! "$UV_BOOTSTRAP_DIR/bin/python" -m pip install "uv==$UV_VERSION" -q; then
    fail "Could not install uv $UV_VERSION (see above). Install it yourself and put it on PATH, then run ./dev-setup.sh again."
    exit 1
  fi
  UV_BIN="$UV_BOOTSTRAP_DIR/bin/uv"
fi

# Both declared extras by default. `dev` carries the tooling of every verification command. `knowledge` carries the declared in-process embedding option: `uv sync` is
# exact, so leaving it out would uninstall it from a venv that has it. Set DEV_SETUP_EXTRAS=dev
# to skip its ML stack, or DEV_SETUP_EXTRAS= for the runtime closure alone.
DEV_SETUP_EXTRAS="${DEV_SETUP_EXTRAS-dev,knowledge}"
UV_EXTRA_FLAGS=()
IFS=',' read -r -a requested_extras <<< "$DEV_SETUP_EXTRAS"
for extra in "${requested_extras[@]}"; do
  if [ -n "$extra" ]; then
    UV_EXTRA_FLAGS+=(--extra "$extra")
  fi
done

say "Installing the locked backend closure into $VENV_DIR (uv sync --locked, extras: ${DEV_SETUP_EXTRAS:-none})..."
say "  This is exact: a package backend/uv.lock does not name is removed, including anything installed by hand."
if ! "$UV_BIN" sync --project "$BACKEND_DIR" --locked "${UV_EXTRA_FLAGS[@]}"; then
  fail "Installing the locked backend closure failed (see above)."
  fail "If the message names lock drift, backend/uv.lock is not current for backend/pyproject.toml: run 'cd backend && uv lock', review the lock diff, and commit it with the change that caused it."
  exit 1
fi

if [ -d "$FRONTEND_DIR/node_modules" ]; then
  say "Frontend packages are installed; left as they are (npm ci in frontend/chat reinstalls them)."
else
  # npm ci installs exactly what package-lock.json names and never rewrites the lock file.
  say "Installing frontend packages (npm ci in frontend/chat)..."
  if ! (cd "$FRONTEND_DIR" && npm ci); then
    fail "Installing frontend packages failed (see above)."
    exit 1
  fi
fi

say "✓ Setup done. Start with ./dev-start.sh."
