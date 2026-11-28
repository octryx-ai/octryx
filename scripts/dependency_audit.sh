#!/usr/bin/env bash
# The backend dependency audit: pip-audit over the locked runtime closure and the locked build group.
#
#   scripts/dependency_audit.sh
#
# Needs network (the advisory database) and the backend venv (`uv sync --extra dev` brings pip-audit). Exit 0 only when
# no advisory is reported; there is no blanket allowance. Every advisory it ignores below is bound to
# dependency_gates/audit_exceptions.py by
# backend/tests/repo_contracts/test_dependency_audit_exceptions.py in both directions (no unrecorded ignore, no stale record).
set -euo pipefail

BACKEND=$(cd "$(dirname "$0")/../backend" && pwd)
UV=${UV:-uv}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cd "$BACKEND"

# --extra knowledge keeps the fastembed tree in scope: it is in the lock, and a locked distribution
# outside the audit is the gap that hid lxml and python-pptx.
"$UV" export --locked --format requirements-txt --no-dev --extra knowledge --no-emit-project >"$WORK/runtime.txt"
# The build group is audited too, because the image installs it: it is the locked build backend the project install
# uses instead of PEP 517 build isolation.
"$UV" export --locked --format requirements-txt --only-group build --no-emit-project >"$WORK/build.txt"

# No advisory is ignored today. An advisory with no fixed release that this product does not reach is added as
# `--ignore-vuln <id>` together with its record in dependency_gates/audit_exceptions.py (the tests hold both).
.venv/bin/pip-audit -r "$WORK/runtime.txt" -r "$WORK/build.txt"
