#!/bin/sh
# The sandbox's entry point. The writable places live on the pod's emptyDir mounts (/tmp, /workspace) because the
# root filesystem is read-only; then the headless runner: enroll, clone through the platform's git gateway, serve the
# run's device jobs, exit when idle. No git secret in the pod: git asks `octryx-claude git-credential` for a
# short-lived, run-bound gateway token on every call.
set -eu
mkdir -p "$HOME" "$OCTRYX_CLAUDE_HOME"
exec octryx-claude device run --sandbox
