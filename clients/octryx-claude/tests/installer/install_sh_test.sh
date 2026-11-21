#!/usr/bin/env bash
# The checks are eval'd strings (single quotes on purpose); values are read inside them.
# shellcheck disable=SC2016,SC2034
# Tests for installer/install.sh against a fake platform, in a temporary HOME only.
# Run: bash clients/octryx-claude/tests/installer/install_sh_test.sh
# Needs curl and a Python >= 3.11 (OCTRYX_TEST_PYTHON, default python3); pip fetches httpx unless
# PIP_FIND_LINKS/PIP_NO_INDEX point at a local wheelhouse.
set -uo pipefail

KIT="$(cd "$(dirname "$0")/../.." && pwd)"
REPO="$(cd "${KIT}/../.." && pwd)"
PY="${OCTRYX_TEST_PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || { echo "needs OCTRYX_TEST_PYTHON >= 3.11"; exit 2; }
PY="$(command -v "$PY")"
PORT="${PORT:-$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')}"
BASE="http://127.0.0.1:${PORT}"
# The canonical spelling (no "//", no symlinked /var): macOS's default TMPDIR ends in "/", so T held "T//octryx-…",
# while pip's shebangs and Python's Path write single slashes. Run directly (not through test_installer_scripts.py,
# whose tmp_path is already canonical) "console script runs the versioned venv" and "pet: on by default" compared
# the two spellings and failed.
T="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/octryx-install-test.XXXXXX")" && pwd -P)"
STATE="${T}/server"
CLIENT="${T}/client"
mkdir -p "$STATE" "${T}/fakebin" "${T}/home"
# A recording launchctl: uninstall removes the pet's login item and must never touch the real user's launchd.
printf '#!/bin/sh\necho "$*" >> "%s/launchctl.log"\n' "$T" > "${T}/fakebin/launchctl"
chmod 755 "${T}/fakebin/launchctl"
# The served sources: a copy, so a test can change them and get a new version.
mkdir -p "$CLIENT"
cp -R "${KIT}/octryx_claude" "${KIT}/installer" "${KIT}/pyproject.toml" "$CLIENT/"
find "$CLIENT" -name __pycache__ -prune -exec rm -rf {} +
FAILS=0

"$PY" "${KIT}/tests/installer/fake_platform.py" "$PORT" "$STATE" "$CLIENT" "${REPO}/backend/scripts" &
SERVER=$!
trap 'kill $SERVER 2>/dev/null; wait $SERVER 2>/dev/null; rm -rf "$T"' EXIT
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  curl -fs "${BASE}/octryx-claude/install.sh" >/dev/null 2>&1 && break; sleep 0.3
done

export HOME="${T}/home" SHELL=/bin/zsh OCTRYX_INSTALL_PYTHON="$PY"
unset OCTRYX_CLAUDE_HOME OCTRYX_PYTHON OCTRYX_CLAUDE_EXECUTABLE
export PATH="${T}/fakebin:${HOME}/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
SD="${HOME}/.octryx/claude"
SHIM="${HOME}/.local/bin/octryx-claude"

ok() { printf 'ok   %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1"; FAILS=$((FAILS + 1)); }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
served() { curl -fsS "${BASE}/octryx-claude/version" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["version"])'; }
run_installer() { curl -fsSL "${BASE}/octryx-claude/install.sh" | bash -s -- "$@"; }

# 1. The served script carries this platform's URL and the optional Workspace, nothing else.
script="$(curl -fsS "${BASE}/octryx-claude/install.sh?workspace=ws-1")"
check "served script: base URL filled" 'printf "%s" "$script" | grep -qx "OCTRYX_BASE_URL='"'"'${BASE}'"'"'"'
check "served script: workspace filled" 'printf "%s" "$script" | grep -qx "OCTRYX_WORKSPACE='"'"'ws-1'"'"'"'
check "served script: no placeholder left" '! printf "%s" "$script" | grep -q "@@OCTRYX_"'

# 2. Fresh install (curl | bash) into the temp HOME, no login (but a Workspace to select later). Without the pet
# here (fast and the same on every OS); section 13 installs it.
out="$(run_installer --no-login --workspace ws-1 --no-pet 2>&1)"; rc=$?
v1="$(served)"
check "install exits 0" '[ "$rc" -eq 0 ]'
check "shim written with the managed mark" 'grep -q "managed by the Octryx installer" "$SHIM" && [ -x "$SHIM" ]'
check "short command octryx runs the same command" '[ -x "${HOME}/.local/bin/octryx" ] && "${HOME}/.local/bin/octryx" status 2>&1 | grep -q "login:      not logged in"'
check "venvs/current points at the served version" '[ "$(readlink "${SD}/venvs/current")" = "$v1" ] && [ "$(cat "${SD}/installed-version")" = "$v1" ]'
check "state dir is private (0700)" '[ "$(stat -f %Lp "$SD" 2>/dev/null || stat -c %a "$SD")" = 700 ]'
check "status runs from the installed package" 'printf "%s" "$out" | grep -q "login:      not logged in"'
check "PATH line added to ~/.zshrc once" '[ "$(grep -c "octryx-claude (Octryx installer)" "${HOME}/.zshrc")" -eq 1 ]'
check "missing claude: official install command printed, not run" 'printf "%s" "$out" | grep -q "claude.ai/install.sh"'
check "installer copy kept for offline uninstall" 'grep -q "OCTRYX_BASE_URL='"'"'${BASE}'"'"'" "${SD}/installer/install.sh"'
check "G1: no ~/.claude* written" '[ -z "$(ls -d "${HOME}"/.claude* 2>/dev/null)" ]'
cfg() { "$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' "${SD}/config.json" "$1"; }
check "--no-login: base URL and requested Workspace stored" '[ "$(cfg base_url)" = "$BASE" ] && [ "$(cfg workspace_request)" = ws-1 ]'
check "--no-login: no credentials stored" '[ ! -e "${SD}/credentials.json" ]'
check "--no-pet: the choice is recorded for updates" '[ -e "${SD}/no-pet" ] && ! printf "%s" "$out" | grep -q "Octryx pet"'
check "--no-login: status shows the platform and the Workspace" 'printf "%s" "$out" | grep -qxF "base URL:   ${BASE}" && printf "%s" "$out" | grep -qF "workspace:  ws-1 (selected at the next login)"'
check "created dirs recorded (~/.local, ~/.local/bin, ~/.octryx)" 'grep -qxF "${HOME}/.local" "${SD}/installer-created-dirs" && grep -qxF "${HOME}/.local/bin" "${SD}/installer-created-dirs" && grep -qxF "${HOME}/.octryx" "${SD}/installer-created-dirs"'
check "no package cache written into HOME (~/Library/Caches/pip, ~/.cache)" '[ ! -e "${HOME}/Library" ] && [ ! -e "${HOME}/.cache" ]'

# 3. The installed package calls itself back through its own venv and carries the digest scripts.
shim_path="$("${SD}/venvs/current/bin/python" -I -c 'from octryx_claude import cli_session; print(cli_session.SHIM)')"
check "hooks call the versioned venv script" '[ "$shim_path" = "$(cd -P "${SD}/venvs/${v1}/bin" && pwd)/octryx-claude" ] && [ -x "$shim_path" ]'
check "console script runs the versioned venv" '[ "$(head -1 "${SD}/venvs/current/bin/octryx-claude")" = "#!${SD}/venvs/${v1}/bin/python" ]'
check "transcript digest scripts packaged" '"${SD}/venvs/current/bin/python" -I -c "from octryx_claude import digest; digest._load()"'
check "installed version is the served version" '[ "$("${SD}/venvs/current/bin/python" -I -c "from octryx_claude.install_layout import installed_version as v; print(v())")" = "$v1" ]'

# 4. Second run: nothing reinstalled, PATH line not duplicated.
out="$(run_installer --no-login 2>&1)"
check "rerun: already installed" 'printf "%s" "$out" | grep -q "${v1} is already installed"'
check "rerun: PATH line still once" '[ "$(grep -c "octryx-claude (Octryx installer)" "${HOME}/.zshrc")" -eq 1 ]'

# 5. A tampered package is refused; the installed version keeps working.
touch "${STATE}/tamper"
out="$(run_installer --no-login --force 2>&1)"; rc=$?
rm -f "${STATE}/tamper"
check "checksum mismatch -> non-zero exit" '[ "$rc" -ne 0 ] && printf "%s" "$out" | grep -q "checksum mismatch"'
check "checksum mismatch -> old version still active" '[ "$(readlink "${SD}/venvs/current")" = "$v1" ] && "$SHIM" status >/dev/null 2>&1'

# 6. Self-update on start: the platform serves new sources; the next start downloads and verifies them, builds
# venvs/<new>, switches current and runs the command on the new version.
printf '\n# changed\n' >> "${CLIENT}/octryx_claude/state.py"
v2="$(served)"
check "new sources -> new served version" '[ "$v2" != "$v1" ]'
out="$("$SHIM" status 2>&1)"
check "self-update: the answer is cached for a minute" '! printf "%s" "$out" | grep -q "updated\|failed" && [ "$(readlink "${SD}/venvs/current")" = "$v1" ]'
rm -f "${SD}/.self-update.json"  # stands in for that minute
touch "${STATE}/tamper"
out="$("$SHIM" status 2>&1)"; rc=$?
rm -f "${STATE}/tamper"
check "self-update: digest mismatch -> one warning, installed version runs" '[ "$rc" -eq 0 ] && printf "%s" "$out" | grep -q "update to ${v2} failed (digest_mismatch)" && printf "%s" "$out" | grep -q "login:" && [ "$(readlink "${SD}/venvs/current")" = "$v1" ] && [ ! -e "${SD}/venvs/${v2}" ]'
out="$("$SHIM" status 2>&1)"
check "self-update: a refused version is not retried at once" '! printf "%s" "$out" | grep -q "updated\|failed" && [ "$(readlink "${SD}/venvs/current")" = "$v1" ]'
rm -f "${SD}/.self-update.json"  # stands in for the hour after which a failed version is tried again
out="$("$SHIM" status 2>&1)"; rc=$?
check "self-update: start updates and re-executes the command" '[ "$rc" -eq 0 ] && [ "$(printf "%s\n" "$out" | grep -c "^octryx-claude updated ${v1} -> ${v2}$")" -eq 1 ] && printf "%s" "$out" | grep -q "login:"'
check "self-update: current switched, previous kept" '[ "$(readlink "${SD}/venvs/current")" = "$v2" ] && [ "$(cat "${SD}/installed-version")" = "$v2" ] && [ -x "${SD}/venvs/${v1}/bin/octryx-claude" ]'
check "self-update: the new venv reports the new version" '[ "$("${SD}/venvs/current/bin/python" -I -c "from octryx_claude.install_layout import installed_version as v; print(v())")" = "$v2" ]'
out="$("$SHIM" status 2>&1)"
check "self-update: the next start just runs" '! printf "%s" "$out" | grep -q "updated\|failed"'
check "self-update: no package cache written into HOME" '[ ! -e "${HOME}/Library" ] && [ ! -e "${HOME}/.cache" ]'
# Opt-out: the once-a-day notice instead of the update.
printf '\n# changed again\n' >> "${CLIENT}/octryx_claude/state.py"
v3="$(served)"
rm -f "${SD}/.update-check" "${SD}/.self-update.json"
out="$(OCTRYX_CLAUDE_AUTO_UPDATE=0 "$SHIM" status 2>&1)"
check "OCTRYX_CLAUDE_AUTO_UPDATE=0: notice, no update" 'printf "%s" "$out" | grep -q "update available (${v2} -> ${v3}); run: curl -fsSL '"'"'${BASE}/octryx-claude/install.sh'"'"' | bash -s -- update" && [ "$(readlink "${SD}/venvs/current")" = "$v2" ]'
out="$(OCTRYX_CLAUDE_AUTO_UPDATE=0 "$SHIM" status 2>&1)"
check "update notice at most once per day" '! printf "%s" "$out" | grep -q "update available"'

# 7. install.sh update installs the new version, keeps the previous one, prunes older ones.
run_installer update >/dev/null 2>&1; rc=$?
check "update -> new version active" '[ "$rc" -eq 0 ] && [ "$(readlink "${SD}/venvs/current")" = "$v3" ]'
check "update keeps the previous version for running sessions" '[ -x "${SD}/venvs/${v2}/bin/octryx-claude" ]'
check "update prunes the oldest version" '[ ! -e "${SD}/venvs/${v1}" ]'

# 8. A foreign octryx-claude in ~/.local/bin is never overwritten.
H2="${T}/home2"; mkdir -p "${H2}/.local/bin"; printf '#!/bin/sh\necho mine\n' > "${H2}/.local/bin/octryx-claude"
out="$(HOME="$H2" run_installer --no-login 2>&1)"; rc=$?
check "foreign shim -> refused, untouched" '[ "$rc" -ne 0 ] && grep -q "echo mine" "${H2}/.local/bin/octryx-claude"'
H7="${T}/home7"; mkdir -p "${H7}/.local/bin"; printf '#!/bin/sh\necho other octryx\n' > "${H7}/.local/bin/octryx"
out="$(HOME="$H7" run_installer --no-login --no-pet 2>&1)"; rc=$?
check "a foreign octryx is kept and named; octryx-claude still installs" '[ "$rc" -eq 0 ] && grep -q "echo other octryx" "${H7}/.local/bin/octryx" && printf "%s" "$out" | grep -q "kept ${H7}/.local/bin/octryx"'

# 8b. A second installation (its own OCTRYX_CLAUDE_HOME) never takes over the first one's shim.
H8="${T}/home8"; mkdir -p "$H8"
first_out="$(HOME="$H8" run_installer --no-login --no-pet 2>&1)"
first_shim="$(cat "${H8}/.local/bin/octryx-claude")"; first_alias="$(cat "${H8}/.local/bin/octryx")"
out="$(HOME="$H8" OCTRYX_CLAUDE_HOME="${T}/second" run_installer --no-login --no-pet 2>&1)"; rc=$?
check "second home: the first shim and octryx stay as they were" '[ "$rc" -eq 0 ] && [ "$(cat "${H8}/.local/bin/octryx-claude")" = "$first_shim" ] && [ "$(cat "${H8}/.local/bin/octryx")" = "$first_alias" ]'
check "second home: its own named shim runs its own state" 'grep -q "${T}/second/venvs/current/bin/octryx-claude" "${H8}/.local/bin/octryx-claude-second" && printf "%s" "$out" | grep -q "kept ${H8}/.local/bin/octryx-claude"'
check "only the first installation is announced as octryx" 'printf "%s" "$first_out" | grep -q "(short: octryx)" && ! printf "%s" "$out" | grep -q "(short: octryx)"'
out="$(HOME="$H8" OCTRYX_CLAUDE_HOME="${T}/second" run_installer uninstall 2>&1)"; rc=$?
check "second home: uninstall removes only its own shim" '[ "$rc" -eq 0 ] && [ ! -e "${H8}/.local/bin/octryx-claude-second" ] && [ "$(cat "${H8}/.local/bin/octryx-claude")" = "$first_shim" ] && [ -e "${H8}/.local/bin/octryx" ]'

# 9. G1: a state dir under ~/.claude* is refused before anything is written.
out="$(OCTRYX_CLAUDE_HOME="${HOME}/.claude-octryx" run_installer --no-login 2>&1)"; rc=$?
check "G1: OCTRYX_CLAUDE_HOME under ~/.claude* refused" '[ "$rc" -ne 0 ] && [ ! -e "${HOME}/.claude-octryx" ] && printf "%s" "$out" | grep -q "belongs to Claude Code"'

# 10. No usable Python: explicit refusal with the options.
out="$(OCTRYX_INSTALL_PYTHON=/usr/bin/false run_installer --no-login --force 2>&1)"; rc=$?
check "unusable python -> explicit refusal" '[ "$rc" -ne 0 ] && printf "%s" "$out" | grep -q "is not a Python >= 3.11"'

# 10b. A Python without venv/ensurepip (fresh Debian/Ubuntu/WSL): the fix is named, nothing is created.
NOVENV="${T}/novenv"; mkdir -p "$NOVENV"
for name in python3.14 python3.13 python3.12 python3.11 python3; do
  printf '#!/bin/sh\ncase "$*" in *ensurepip*) echo "No module named ensurepip" >&2; exit 1 ;; esac\nexec %s "$@"\n' "$PY" > "${NOVENV}/${name}"
  chmod 755 "${NOVENV}/${name}"
done
H4="${T}/home4"; mkdir -p "$H4"
out="$(HOME="$H4" PATH="${NOVENV}:${PATH}" OCTRYX_INSTALL_PYTHON='' run_installer --no-login 2>&1)"; rc=$?
check "python without venv -> names sudo apt install python3-venv" '[ "$rc" -ne 0 ] && printf "%s" "$out" | grep -q "cannot create venvs" && printf "%s" "$out" | grep -q "sudo apt install python3-venv"'
check "python without venv -> no package-index blame, no state dir" '! printf "%s" "$out" | grep -q "package index" && [ ! -e "${H4}/.octryx" ]'
out="$(HOME="$H4" OCTRYX_INSTALL_PYTHON="${NOVENV}/python3" run_installer --no-login 2>&1)"; rc=$?
check "OCTRYX_INSTALL_PYTHON without venv -> explicit refusal" '[ "$rc" -ne 0 ] && printf "%s" "$out" | grep -q "sudo apt install python3-venv"'

# 10c. A failed package download leaves no state directory behind.
touch "${STATE}/nopackage"
out="$(HOME="$H4" run_installer --no-login 2>&1)"; rc=$?
rm -f "${STATE}/nopackage"
check "failed download -> non-zero, no state dir created" '[ "$rc" -ne 0 ] && printf "%s" "$out" | grep -q "could not download" && [ ! -e "${H4}/.octryx" ]'

# 10d. G1 after resolving the path: ~/.claudeX, ~/x/../.claude and a symlink into ~/.claude are refused.
H3="${T}/home3"; mkdir -p "${H3}/.claude"; ln -s "${H3}/.claude" "${H3}/link"
for target in "${H3}/.claudeX" "${H3}/x/../.claude/octryx" "${H3}/link/octryx"; do
  out="$(HOME="$H3" OCTRYX_CLAUDE_HOME="$target" run_installer --no-login 2>&1)"; rc=$?
  check "G1: OCTRYX_CLAUDE_HOME=${target#"$T"/} refused" '[ "$rc" -ne 0 ] && printf "%s" "$out" | grep -q "belongs to Claude Code"'
done
check "G1: nothing written into the resolved ~/.claude" '[ -z "$(ls -A "${H3}/.claude")" ] && [ ! -e "${H3}/.claudeX" ] && [ ! -e "${H3}/x" ]'

# 11. uninstall keeps login and settings; --purge revokes the login and removes everything. Directories the
# installer created go once empty; a non-empty one stays (and stays recorded).
printf 'mine\n' > "${HOME}/.local/bin/mytool"; printf 'finder\n' > "${HOME}/.local/bin/.DS_Store"
run_installer uninstall >/dev/null 2>&1; rc=$?
check "uninstall: shim, venvs and PATH line removed" '[ "$rc" -eq 0 ] && [ ! -e "$SHIM" ] && [ ! -e "${HOME}/.local/bin/octryx" ] && [ ! -e "${SD}/venvs" ] && ! grep -q "Octryx installer" "${HOME}/.zshrc"'
check "uninstall: state kept" '[ -f "${SD}/config.json" ]'
check "uninstall: a non-empty ~/.local/bin is kept, its content untouched" '[ "$(cat "${HOME}/.local/bin/mytool")" = mine ] && [ -f "${HOME}/.local/bin/.DS_Store" ]'
check "uninstall: the kept dir stays recorded" 'grep -qxF "${HOME}/.local/bin" "${SD}/installer-created-dirs"'
rm -f "${HOME}/.local/bin/mytool"
run_installer uninstall >/dev/null 2>&1
check "uninstall (no --purge): the created, now empty ~/.local/bin and ~/.local removed" '[ ! -e "${HOME}/.local" ] && [ -f "${SD}/config.json" ]'
run_installer --no-login >/dev/null 2>&1
printf '{"base_url": "%s", "client_id": "c1", "refresh_token": "rt-test"}\n' "$BASE" > "${SD}/credentials.json"
printf 'finder\n' > "${HOME}/.octryx/.DS_Store"; printf 'finder\n' > "${HOME}/.local/._x"
bash "${SD}/installer/install.sh" uninstall --purge >/dev/null 2>&1; rc=$?
check "uninstall --purge (offline copy): login revoked at the platform" '[ "$rc" -eq 0 ] && grep -qx "rt-test" "${STATE}/revoked"'
check "uninstall --purge: state dir (and ~/.octryx, empty but for .DS_Store) removed" '[ ! -e "$SD" ] && [ ! -e "${HOME}/.octryx" ] && [ ! -e "$SHIM" ]'
check "uninstall --purge: created ~/.local/bin and ~/.local (empty but for ._x) removed, no Library/cache leftovers" '[ ! -e "${HOME}/.local" ] && [ ! -e "${HOME}/Library" ] && [ ! -e "${HOME}/.cache" ]'
check "G1 after all runs: no ~/.claude* in HOME" '[ -z "$(ls -d "${HOME}"/.claude* 2>/dev/null)" ]'

# 12. Pre-existing directories are never removed: an empty ~/.local/bin, ~/.octryx and a pip cache.
H5="${T}/home5"; mkdir -p "${H5}/.local/bin" "${H5}/.octryx" "${H5}/Library/Caches/pip"
printf 'x\n' > "${H5}/Library/Caches/pip/keep"
HOME="$H5" run_installer --no-login >/dev/null 2>&1; rc=$?
check "pre-existing dirs: install exits 0, nothing of them recorded" '[ "$rc" -eq 0 ] && ! grep -qE "/(\.local|\.local/bin|\.octryx)$" "${H5}/.octryx/claude/installer-created-dirs" 2>/dev/null'
# A lost race (Finder writes a .DS_Store into the state dir after rm emptied it): a fake rm on PATH that puts
# FAKE_RM_LEFT back into a removed .../octryx-claude and fails, once (FAKE_RM_ONCE) or every time.
mkdir -p "${T}/fakebin"
cat > "${T}/fakebin/rm" <<'EOF_RM'
#!/bin/bash
target=''
for a in "$@"; do case "$a" in */.octryx/claude) target="$a" ;; esac; done
/bin/rm "$@"; rc=$?
if [ -n "$target" ] && { [ -z "${FAKE_RM_ONCE:-}" ] || [ ! -e "${FAKE_RM_ONCE}" ]; }; then
  [ -z "${FAKE_RM_ONCE:-}" ] || : > "$FAKE_RM_ONCE"
  mkdir -p "$target"; printf 'x' > "${target}/${FAKE_RM_LEFT}"
  echo "rm: ${target}: Directory not empty" >&2; exit 1
fi
exit "$rc"
EOF_RM
chmod +x "${T}/fakebin/rm"
out="$(HOME="$H5" PATH="${T}/fakebin:${PATH}" FAKE_RM_ONCE="${T}/rm-once" FAKE_RM_LEFT=.DS_Store run_installer uninstall --purge 2>&1)"; rc=$?
check "lost race once: the second try removes the state dir, exit 0" '[ "$rc" -eq 0 ] && [ -e "${T}/rm-once" ] && [ ! -e "${H5}/.octryx/claude" ] && ! printf "%s" "$out" | grep -q stays'
check "pre-existing dirs: uninstall --purge keeps the empty ~/.local/bin and ~/.octryx" '[ "$rc" -eq 0 ] && [ -d "${H5}/.local/bin" ] && [ -d "${H5}/.octryx" ] && [ ! -e "${H5}/.octryx/claude" ]'
check "pre-existing pip cache untouched" '[ "$(ls -A "${H5}/Library/Caches/pip")" = keep ]'
H9="${T}/home9"; SD9="${H9}/.octryx/claude"
mkdir -p "$SD9"; printf '{}\n' > "${SD9}/config.json"
out="$(HOME="$H9" PATH="${T}/fakebin:${PATH}" FAKE_RM_LEFT=.DS_Store run_installer uninstall --purge 2>&1)"; rc=$?
check "lost race every time, only .DS_Store left: exit 0 and a clear sentence" '[ "$rc" -eq 0 ] && [ "$(ls -A "$SD9")" = .DS_Store ] && printf "%s" "$out" | grep -q "stays: the operating system kept writing its own files" && printf "%s" "$out" | grep -q "holds only the operating system"'
out="$(HOME="$H9" PATH="${T}/fakebin:${PATH}" FAKE_RM_LEFT=notes.txt run_installer uninstall --purge 2>&1)"; rc=$?
check "anything else left: says what and exits non-zero" '[ "$rc" -ne 0 ] && printf "%s" "$out" | grep -q "could not remove ${SD9}" && printf "%s" "$out" | grep -q "did not remove everything"'

# 13. The Octryx pet (macOS): comes along and is on by default, both choices are remembered, uninstall removes its
#     login item.
if [ "$(uname -s)" = Darwin ] && [ -z "${PIP_NO_INDEX:-}" ]; then
  H6="${T}/home6"; mkdir -p "$H6"; SD6="${H6}/.octryx/claude"
  # A temporary HOME is a second installation: its label carries the state dir's hash, so it never boots out the
  # person's own pet.
  LABEL6="ai.octryx.claude.pet.$(printf '%s' "$SD6" | tr -s / | shasum -a 256 | cut -c1-10)"
  PLIST6="${H6}/Library/LaunchAgents/${LABEL6}.plist"
  : > "${T}/launchctl.log"
  out="$(HOME="$H6" run_installer --no-login 2>&1)"; rc=$?
  check "pet: installed by default on macOS" '[ "$rc" -eq 0 ] && printf "%s" "$out" | grep -q "Octryx pet installed" && "${SD6}/venvs/current/bin/python" -I -c "import pystray, PIL, octryx_claude.pet.tray"'
  check "pet: no opt-out recorded" '[ ! -e "${SD6}/no-pet" ]'
  check "pet: the served wheel declares the extra" '"${SD6}/venvs/current/bin/python" -I -c "from importlib.metadata import metadata as m; assert \"pet\" in m(\"octryx-claude\").get_all(\"Provides-Extra\")"'
  check "pet: on by default, now and at every login" 'printf "%s" "$out" | grep -q "the pet runs now and starts at every login" && grep -q "pet</string>" "$PLIST6" && grep -q "bootstrap gui/$(id -u) ${PLIST6}" "${T}/launchctl.log"'
  out="$(HOME="$H6" "${H6}/.local/bin/octryx-claude" pet disable 2>&1)"
  check "pet: pet disable turns it off" '[ ! -e "$PLIST6" ] && [ -e "${SD6}/pet-autostart-off" ]'
  out="$(HOME="$H6" run_installer --no-login --force 2>&1)"
  check "pet: a new install keeps it off" 'printf "%s" "$out" | grep -q "the pet stays off" && [ ! -e "$PLIST6" ]'
  out="$(HOME="$H6" "${H6}/.local/bin/octryx-claude" pet enable 2>&1)"
  check "pet: pet enable turns it on again" '[ -e "$PLIST6" ] && [ ! -e "${SD6}/pet-autostart-off" ]'
  out="$(HOME="$H6" run_installer --no-login --no-pet 2>&1)"
  check "pet: --no-pet on a current install records the opt-out and drops the login item" 'printf "%s" "$out" | grep -q "is already installed" && [ -e "${SD6}/no-pet" ] && [ ! -e "$PLIST6" ]'
  out="$(HOME="$H6" run_installer --no-login --pet 2>&1)"
  check "pet: --pet with the pet present needs no reinstall and is on again" 'printf "%s" "$out" | grep -q "is already installed" && [ ! -e "${SD6}/no-pet" ] && [ -e "$PLIST6" ]'
  : > "${T}/launchctl.log"
  out="$(HOME="$H6" run_installer uninstall 2>&1)"; rc=$?
  check "pet: uninstall removes its login item" '[ "$rc" -eq 0 ] && [ ! -e "$PLIST6" ] && grep -q "bootout gui/$(id -u)/${LABEL6}" "${T}/launchctl.log" && ! grep -q "gui/$(id -u)/ai.octryx.claude.pet\$" "${T}/launchctl.log"'
else
  echo "skip 13. the Octryx pet (macOS with a package index only)"
fi

echo
if [ "$FAILS" -eq 0 ]; then echo "ALL PASSED"; else echo "${FAILS} FAILED"; exit 1; fi
