#!/usr/bin/env bash
# octryx-claude installer (Octryx). The platform serves it with its URL filled in:
#   curl -fsSL '<platform>/octryx-claude/install.sh' | bash
#   curl -fsSL '<platform>/octryx-claude/install.sh' | bash -s -- [install|update|uninstall] [options]
# Options: --no-login, --workspace ID, --force (reinstall the same version), --purge (uninstall:
# also revoke the login and delete the state directory), --no-pet / --pet (macOS: leave out or bring back the
# Octryx pet, the tray icon; it comes along by default and is remembered for updates and self-updates). The pet is
# on by default: every install turns it on at login unless the person turned it off (octryx-claude pet disable, or
# "Turn off Octryx" in its menu; octryx-claude pet enable turns it on again).
# The platform URL (and --workspace) is always stored with `octryx-claude configure`, so a later plain
# `octryx-claude login` knows the platform. Directories the installer creates (~/.local/bin, ...) are
# recorded in the state directory; uninstall removes them again once they are empty.
#
# Installs the launcher into its own venv under the state directory
# (~/.octryx/claude/venvs/<version>, "current" points at the active one), the
# octryx-claude shim into ~/.local/bin and that directory into PATH. The package comes from the
# platform and is checked against the sha256 the platform publishes. Never touches ~/.claude or
# plain `claude`; Claude Code itself is a prerequisite and is never installed here.
# bash 3.2 compatible (macOS); Linux and WSL2 too. Needs curl and Python >= 3.11 (or uv).
set -euo pipefail

OCTRYX_BASE_URL='@@OCTRYX_BASE_URL@@'
OCTRYX_WORKSPACE='@@OCTRYX_WORKSPACE@@'
# The operating system's own files (.DS_Store, ...; octryx_claude/os_junk.json): a created folder holding only those
# still counts as empty at uninstall.
OCTRYX_OS_JUNK='@@OCTRYX_OS_JUNK@@'
MIN_PYTHON_MINOR=11

STATE_DIR="${OCTRYX_CLAUDE_HOME:-${HOME}/.octryx/claude}"
VENVS_DIR="${STATE_DIR}/venvs"
CURRENT="${VENVS_DIR}/current"
VERSION_FILE="${STATE_DIR}/installed-version"
INSTALLER_COPY="${STATE_DIR}/installer/install.sh"
# Directories this installer created, one absolute path per line. Outside installer/, so it survives a plain
# uninstall (and the offline uninstall copy reads it as well).
CREATED_DIRS="${STATE_DIR}/installer-created-dirs"
BIN_DIR="${HOME}/.local/bin"
SHIM="${BIN_DIR}/octryx-claude"
SHIM_MARK="# octryx-claude shim (managed by the Octryx installer)"
# `octryx`: the short name for the same command. It forwards to the shim, so updates and
# self-updates need nothing of their own; an existing foreign `octryx` is left alone.
ALIAS="${BIN_DIR}/octryx"
ALIAS_MARK="# octryx command (managed by the Octryx installer)"
PATH_MARK="# octryx-claude (Octryx installer): ~/.local/bin on PATH"
USAGE="usage: install.sh [install|update|uninstall] [--no-login] [--workspace ID] [--force] [--purge] [--no-pet|--pet]"
# The Octryx pet (octryx-claude[pet]: pystray, Pillow; macOS only for now). This file records an opt-out;
# self_update.py reads the same file, so an update never drops or adds the pet behind the person's back.
NO_PET_FILE="${STATE_DIR}/no-pet"
agent_label() {
  # $1 base label. launchd labels live per user (gui/<uid>), not per HOME: a second install (temporary HOME or
  # OCTRYX_CLAUDE_HOME) with the plain label booted out the person's own pet (alpha install test). The
  # standard install keeps the plain label; every other one gets .<10 hex of its state dir>, the same as
  # octryx_claude.device_service_units.instance_label.
  # The state dir as Python's Path spells it: repeated slashes collapsed, no trailing slash.
  local account_home state
  state="$(printf '%s' "$STATE_DIR" | tr -s /)"; state="${state%/}"
  account_home="$(eval echo "~$(id -un)" 2>/dev/null || true)"
  if [ "${HOME%/}" = "${account_home%/}" ] && [ "$state" = "${account_home%/}/.octryx/claude" ]; then
    printf '%s' "$1"
  else
    printf '%s.%s' "$1" "$(printf '%s' "$state" | { shasum -a 256 2>/dev/null || sha256sum; } | cut -c1-10)"
  fi
}
PET_AGENT_LABEL="$(agent_label ai.octryx.claude.pet)"
PET_AGENT_PLIST="${HOME}/Library/LaunchAgents/${PET_AGENT_LABEL}.plist"
PACKAGE_INSTALLED=''  # 1 once install_package put a new version in place (a running pet restarts on it)
CLAUDE_INSTALL_HINT="curl -fsSL https://claude.ai/install.sh | bash   (https://code.claude.com/docs/en/setup)"

say() { printf '%s\n' "$*" >&2; }
die() { say "octryx-claude installer: $*"; exit 1; }

# Single-quote $1 for sh.
sh_quote() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

# $1 with "." and ".." segments and repeated slashes removed (lexically; $1 is absolute).
collapse_path() {
  local part out='' IFS=/
  set -f
  for part in $1; do
    case "$part" in ''|.) ;; ..) out="${out%/*}" ;; *) out="${out}/${part}" ;; esac
  done
  set +f
  printf '%s' "${out:-/}"
}

# $1 as an absolute path: the existing part resolved physically (cd -P, symlinks followed), the rest
# collapsed lexically.
physical_path() {
  local head="$1" tail=''
  case "$head" in /*) ;; *) head="$(pwd -P)/${head}" ;; esac
  head="$(collapse_path "$head")"
  while [ "$head" != / ] && [ ! -d "$head" ]; do
    tail="/$(basename "$head")${tail}"
    head="$(dirname "$head")"
  done
  head="$(cd -P "$head" 2>/dev/null && pwd)" || die "refused: cannot resolve ${1}"
  collapse_path "${head}${tail}"
}

# G1: nothing this script writes or deletes may be standard Claude Code's config. Compared after
# resolving both sides, so ~/x/../.claude or a symlink into ~/.claude cannot slip through.
guard_path() {
  local path home
  [ -n "$1" ] || die "refused: empty path"
  path="$(physical_path "$1")" || exit 1
  home="$(physical_path "$HOME")" || exit 1
  case "$path" in
    /) die "refused: root path" ;;
    "${home}/.claude"*) die "refused: ${1} belongs to Claude Code (~/.claude*); octryx-claude never writes there" ;;
  esac
}

# --- directories the installer creates ----------------------------------------------
# $1 and its missing ancestors inside HOME, deepest first.
missing_dirs() {
  local dir="$1"
  while [ ! -e "$dir" ]; do
    case "$dir" in "${HOME}"/*) ;; *) return 0 ;; esac
    printf '%s\n' "$dir"
    dir="$(dirname "$dir")"
  done
}

# mkdir -p $1, recording what it creates. The state dir is the first thing created, so the record can go there.
make_dir() {
  local created line
  created="$(missing_dirs "$1")"
  mkdir -p "$1"
  [ -n "$created" ] || return 0
  printf '%s\n' "$created" | while IFS= read -r line; do
    grep -qsxF "$line" "$CREATED_DIRS" || printf '%s\n' "$line" >> "$CREATED_DIRS"
  done
}

# True when $1 holds nothing but the operating system's own files (OCTRYX_OS_JUNK), which are then removed: Finder
# drops a .DS_Store into any folder it shows. Anything else in it (a folder, a link, another file) keeps it all.
clear_os_junk() {
  local entry junk=''
  for entry in "$1"/* "$1"/.[!.]* "$1"/..?*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    [ -f "$entry" ] && [ ! -L "$entry" ] && is_os_junk "${entry##*/}" || return 1
    junk="${junk}${entry}
"
  done
  [ -n "$junk" ] || return 1
  printf '%s' "$junk" | while IFS= read -r entry; do rm -f -- "$entry"; done
}

# True when the file name $1 is one of the operating system's own (OCTRYX_OS_JUNK; patterns such as "._*").
is_os_junk() {
  local junk_names name
  read -r -a junk_names <<< "$OCTRYX_OS_JUNK" || true
  [ "${#junk_names[@]}" -gt 0 ] || return 1
  for name in "${junk_names[@]}"; do
    # shellcheck disable=SC2254 # the names are patterns ("._*")
    case "$1" in $name) return 0 ;; esac
  done
  return 1
}

# True when everything left under $1 is folders and the operating system's own files.
only_os_junk_left() {
  local file
  while IFS= read -r file; do
    [ -n "$file" ] || continue
    is_os_junk "${file##*/}" || return 1
  done <<EOF_LEFT
$(find "$1" ! -type d 2>/dev/null)
EOF_LEFT
}

# rm -rf that survives a lost race: Finder can write a .DS_Store into a folder after rm emptied it and before rm
# removes it ("Directory not empty"). One more try after a short pause; never stops the script by itself. When a
# path stays only because of the operating system's own files, it says so and counts as done; anything else that
# stays is said too and returns 1.
remove_tree() {
  local path rc=0
  for path in "$@"; do
    [ -e "$path" ] || [ -L "$path" ] || continue
    rm -rf -- "$path" 2>/dev/null && continue
    sleep 1
    rm -rf -- "$path" 2>/dev/null && continue
    if only_os_junk_left "$path"; then
      say "- ${path} stays: the operating system kept writing its own files (.DS_Store) into it; delete it any time"
    else
      say "- could not remove ${path}"
      rc=1
    fi
  done
  return "$rc"
}

# rmdir every recorded directory that is empty now, deepest first (never rm -r); the record keeps the ones still
# there (not empty). A folder holding only the operating system's own files counts as empty. $1: the record's
# content, read before a --purge deleted the state dir.
remove_created_dirs() {
  local dir kept=''
  [ -n "$1" ] || return 0
  while IFS= read -r dir; do
    case "$dir" in "${HOME}"/?*) ;; *) continue ;; esac
    if [ -d "$dir" ] && [ ! -L "$dir" ] && guard_path "$dir" \
      && { rmdir "$dir" 2>/dev/null || { clear_os_junk "$dir" && rmdir "$dir" 2>/dev/null; }; }; then
      say "- removed the empty ${dir}"
    elif [ -d "$dir" ]; then
      kept="${kept}${dir}
"
    fi
  done <<EOF_DIRS
$(printf '%s\n' "$1" | awk '{ print length($0) "\t" $0 }' | sort -rn | cut -f2-)
EOF_DIRS
  if [ -d "$STATE_DIR" ]; then
    if [ -n "$kept" ]; then printf '%s' "$kept" > "$CREATED_DIRS"; else rm -f "$CREATED_DIRS"; fi
  fi
}

# --- flat JSON field reader (the platform's /version answer) ----------------------
json_str() { printf '%s' "$2" | grep -o "\"$1\" *: *\"[^\"]*\"" | head -1 | sed 's/^.*: *"\(.*\)"$/\1/' || true; }

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1
  elif command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else die "needs shasum or sha256sum to verify the package"
  fi
}

python_ok() {
  "$1" -c "import sys; sys.exit(0 if sys.version_info >= (3, ${MIN_PYTHON_MINOR}) else 1)" >/dev/null 2>&1
}

# Debian/Ubuntu (also a fresh WSL Ubuntu) ship python3 without venv/ensurepip (package python3-venv).
venv_ok() { "$1" -c 'import ensurepip, venv' >/dev/null 2>&1; }

VENV_MISSING_HINT="install the venv module and rerun:
    sudo apt install python3-venv                           (Debian, Ubuntu, WSL Ubuntu)
  or install uv, which brings its own Python:
    curl -LsSf https://astral.sh/uv/install.sh | sh"

# Prints the Python to build the venv with, "uv" when uv does it, or nothing. Dies when the only
# new-enough Python cannot create venvs.
find_python() {
  local candidate path no_venv=''
  if [ -n "${OCTRYX_INSTALL_PYTHON:-}" ]; then
    python_ok "$OCTRYX_INSTALL_PYTHON" || die "OCTRYX_INSTALL_PYTHON=${OCTRYX_INSTALL_PYTHON} is not a Python >= 3.${MIN_PYTHON_MINOR}"
    venv_ok "$OCTRYX_INSTALL_PYTHON" || die "OCTRYX_INSTALL_PYTHON=${OCTRYX_INSTALL_PYTHON} cannot create venvs; ${VENV_MISSING_HINT}"
    printf '%s' "$OCTRYX_INSTALL_PYTHON"; return 0
  fi
  if command -v uv >/dev/null 2>&1; then printf 'uv'; return 0; fi
  for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    path="$(command -v "$candidate" 2>/dev/null || true)"
    if [ -z "$path" ] || ! python_ok "$path"; then continue; fi
    if venv_ok "$path"; then printf '%s' "$path"; return 0; fi
    no_venv="${no_venv:-$path}"
  done
  [ -z "$no_venv" ] || die "${no_venv} cannot create venvs (no venv/ensurepip module); ${VENV_MISSING_HINT}"
  return 0
}

check_claude() {
  if command -v claude >/dev/null 2>&1; then return 0; fi
  say "- Claude Code (claude) was not found. octryx-claude needs it to start sessions; install it with"
  say "  the official installer, then open a new terminal:"
  say "    ${CLAUDE_INSTALL_HINT}"
}

# --- package -------------------------------------------------------------------------
create_venv() {
  # $1 python or "uv", $2 venv dir, $3 wheel
  if [ "$1" = uv ]; then
    # No package cache: it would land in the user's home (~/Library/Caches/pip, ~/.cache/uv) and outlive uninstall.
    uv venv --quiet --no-cache --python ">=3.${MIN_PYTHON_MINOR}" "$2" </dev/null
    uv pip install --quiet --no-cache --python "$2/bin/python" "$3" </dev/null
  else
    "$1" -m venv "$2" </dev/null
    "$2/bin/python" -m pip install --quiet --disable-pip-version-check --no-cache-dir "$3" </dev/null
  fi
}

# --- the Octryx pet (optional) -------------------------------------------------------
pet_wanted() {
  # $1 "on" (--pet), "off" (--no-pet) or empty (keep the recorded choice; default on).
  [ "$(uname -s)" = Darwin ] || return 1
  case "$1" in on) return 0 ;; off) return 1 ;; esac
  [ ! -e "$NO_PET_FILE" ]
}

record_pet_choice() {
  case "$1" in on) rm -f "$NO_PET_FILE" ;; off) : > "$NO_PET_FILE" ;; esac
}

pet_present() { [ -x "$1/bin/python" ] && "$1/bin/python" -I -c 'import pystray, PIL' >/dev/null 2>&1; }

install_pet() {
  # $1 python or "uv", $2 venv dir, $3 wheel. Never fatal: the launcher works without the pet.
  local requirement
  requirement="octryx-claude[pet] @ file://$(collapse_path "$3")"  # macOS TMPDIR ends in "/": no "//" in the URL
  if [ "$1" = uv ]; then
    uv pip install --quiet --no-cache --python "$2/bin/python" "$requirement" </dev/null || true
  else
    "$2/bin/python" -m pip install --quiet --disable-pip-version-check --no-cache-dir "$requirement" </dev/null || true
  fi
  if pet_present "$2"; then
    say "- Octryx pet installed"
  else
    say "- the Octryx pet (pystray, Pillow) could not be installed; octryx-claude works without it (retry: update --force)"
  fi
}

remove_pet_agent() {
  # The pet's login item points at the shim; it goes with the installation.
  [ "$(uname -s)" = Darwin ] && [ -f "$PET_AGENT_PLIST" ] || return 0
  launchctl bootout "gui/$(id -u)/${PET_AGENT_LABEL}" >/dev/null 2>&1 || true
  rm -f "$PET_AGENT_PLIST"
  say "- removed the Octryx pet login item"
}

start_pet() {
  # On by default; `pet autostart` keeps it off when the person turned it off. Without the pet
  # (or after --no-pet) the login item goes, so it cannot fail at every login. Never fatal.
  [ "$(uname -s)" = Darwin ] || return 0
  if ! pet_wanted "" || ! pet_present "$CURRENT"; then remove_pet_agent; return 0; fi
  local restart=''
  [ -n "$PACKAGE_INSTALLED" ] && restart='--restart'
  # shellcheck disable=SC2086 # $restart is one flag or nothing
  if ! "$SHIM" pet autostart $restart 2>&1 | sed 's/^octryx-claude: /- /'; then
    say "- the Octryx pet could not be started now; it starts at the next login (or: octryx-claude pet enable)"
  fi
}

prune_versions() {
  # Keeps the active version and $1 (the one before, which a running session may still call).
  local entry name
  for entry in "${VENVS_DIR}"/*; do
    [ -d "$entry" ] && [ ! -L "$entry" ] || continue
    name="$(basename "$entry")"
    [ "$name" = "$2" ] || [ "$name" = "$1" ] || rm -rf "$entry"
  done
}

install_package() {
  # $1 force (1/empty), $2 pet choice (on/off/empty). Installs the served version unless it is already active
  # (and, with --pet, already has the pet).
  local meta version filename sha python tmp wheel actual dir previous
  meta="$(curl -fsS --max-time 30 "${OCTRYX_BASE_URL}/octryx-claude/version")" \
    || die "could not reach ${OCTRYX_BASE_URL}/octryx-claude/version"
  version="$(json_str version "$meta")"
  filename="$(json_str filename "$meta")"
  sha="$(json_str sha256 "$meta")"
  printf '%s' "$version" | grep -Eq '^[0-9][0-9A-Za-z.+_-]{0,63}$' || die "the platform answered no usable version"
  printf '%s' "$filename" | grep -Eq '^octryx_claude-[0-9A-Za-z.+_-]+-py3-none-any\.whl$' \
    || die "the platform answered no usable package name"
  printf '%s' "$sha" | grep -Eq '^[0-9a-f]{64}$' || die "the platform answered no usable checksum"

  if [ -z "$1" ] && [ -x "${CURRENT}/bin/octryx-claude" ] && [ "$(cat "$VERSION_FILE" 2>/dev/null || true)" = "$version" ] \
    && { [ "$2" != on ] || ! pet_wanted on || pet_present "$CURRENT"; }; then
    record_pet_choice "$2"
    say "- octryx-claude ${version} is already installed"
    return 0
  fi
  python="$(find_python)" || exit 1
  if [ -z "$python" ]; then
    die "needs Python >= 3.${MIN_PYTHON_MINOR} or uv. Install one of them and rerun, e.g.:
    curl -LsSf https://astral.sh/uv/install.sh | sh        (uv, brings its own Python)
    brew install python@3.12                                (macOS with Homebrew)"
  fi

  tmp="$(mktemp -d "${TMPDIR:-/tmp}/octryx-install.XXXXXX")"
  wheel="${tmp}/${filename}"
  if ! curl -fsS --max-time 300 "${OCTRYX_BASE_URL}/octryx-claude/package/${version}" -o "$wheel"; then
    rm -rf "$tmp"; die "could not download the package ${version}"
  fi
  actual="$(sha256_of "$wheel")"
  if [ "$actual" != "$sha" ]; then
    rm -rf "$tmp"
    die "checksum mismatch for ${filename} (expected ${sha}, got ${actual}); nothing was installed"
  fi

  # The state dir only exists once there is something verified to put into it.
  make_dir "$STATE_DIR"
  chmod 700 "$STATE_DIR"
  record_pet_choice "$2"
  dir="${VENVS_DIR}/${version}"
  mkdir -p "$VENVS_DIR"
  rm -rf "$dir"
  say "- installing octryx-claude ${version} (${python})"
  if ! create_venv "$python" "$dir" "$wheel" || ! "${dir}/bin/python" -c "import octryx_claude.cli" >/dev/null 2>&1; then
    rm -rf "$dir" "$tmp"
    die "the package could not be installed into ${dir}; see the pip/uv messages above (its dependency httpx comes from your package index)"
  fi
  if pet_wanted "$2"; then install_pet "$python" "$dir" "$wheel"; fi
  rm -rf "$tmp"
  previous="$(cat "$VERSION_FILE" 2>/dev/null || true)"
  ln -sfn "$version" "$CURRENT"
  printf '%s\n' "$version" > "$VERSION_FILE"
  prune_versions "$previous" "$version"
  PACKAGE_INSTALLED=1
}

save_installer_copy() {
  # Kept for an offline uninstall: bash ~/.octryx/claude/installer/install.sh uninstall
  mkdir -p "$(dirname "$INSTALLER_COPY")"
  if curl -fsS --max-time 30 "${OCTRYX_BASE_URL}/octryx-claude/install.sh" -o "${INSTALLER_COPY}.tmp"; then
    mv -f "${INSTALLER_COPY}.tmp" "$INSTALLER_COPY"
  else
    rm -f "${INSTALLER_COPY}.tmp"
  fi
}

# The state folder an installer-written shim runs: its exec line is '<state>/venvs/current/bin/octryx-claude'.
shim_state() {
  sed -n "s|^exec '\(.*\)/venvs/current/bin/octryx-claude' .*|\1|p" "$1" 2>/dev/null | head -n 1
}

# A second installation (its own OCTRYX_CLAUDE_HOME) never takes over the shim of another one: it gets its own
# ~/.local/bin/octryx-claude-<state folder name>, and `octryx` stays with the first (a test install with
# OCTRYX_CLAUDE_HOME rewrote a person's octryx-claude to point at the test's state).
OWN_SHIM=1
resolve_shim() {
  local other
  [ -e "$SHIM" ] && grep -qF "$SHIM_MARK" "$SHIM" 2>/dev/null || return 0
  other="$(shim_state "$SHIM")"
  [ -n "$other" ] && [ "$other" != "$STATE_DIR" ] || return 0
  SHIM="${BIN_DIR}/octryx-claude-$(printf '%s' "$(basename "$STATE_DIR")" | tr -c 'A-Za-z0-9_-' '-' | cut -c1-40)"
  OWN_SHIM=''
  say "- kept ${BIN_DIR}/octryx-claude: it runs the installation in ${other}; this one is ${SHIM}"
}

require_own_shim() {
  if [ -e "$SHIM" ] && ! grep -qF "$SHIM_MARK" "$SHIM" 2>/dev/null; then
    die "${SHIM} exists and was not written by this installer; move it away and rerun"
  fi
}

write_shim() {
  require_own_shim
  make_dir "$BIN_DIR"
  {
    printf '#!/bin/sh\n%s\n' "$SHIM_MARK"
    if [ -n "${OCTRYX_CLAUDE_HOME:-}" ]; then
      printf 'OCTRYX_CLAUDE_HOME=%s; export OCTRYX_CLAUDE_HOME\n' "$(sh_quote "$OCTRYX_CLAUDE_HOME")"
    fi
    # Claude Code's own installer puts claude here, also when this shim runs without a login shell (WSL).
    # shellcheck disable=SC2016 # written literally into the shim
    printf '%s\n' 'case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH"; export PATH ;; esac'
    printf 'exec %s "$@"\n' "$(sh_quote "${CURRENT}/bin/octryx-claude")"
  } > "${SHIM}.tmp"
  chmod 755 "${SHIM}.tmp"
  mv -f "${SHIM}.tmp" "$SHIM"
}

write_alias() {
  [ -n "$OWN_SHIM" ] || return 0  # `octryx` belongs to the installation that owns octryx-claude
  if [ -e "$ALIAS" ] && ! grep -qF "$ALIAS_MARK" "$ALIAS" 2>/dev/null; then
    say "- kept ${ALIAS}: not written by this installer (use octryx-claude)"
    return 0
  fi
  {
    printf '#!/bin/sh\n%s\n' "$ALIAS_MARK"
    printf 'exec %s "$@"\n' "$(sh_quote "$SHIM")"
  } > "${ALIAS}.tmp"
  chmod 755 "${ALIAS}.tmp"
  mv -f "${ALIAS}.tmp" "$ALIAS"
}

shell_rc() {
  case "$(basename "${SHELL:-}")" in
    zsh) printf '%s' "${HOME}/.zshrc" ;;
    bash) if [ "$(uname -s)" = Darwin ]; then printf '%s' "${HOME}/.bash_profile"; else printf '%s' "${HOME}/.bashrc"; fi ;;
    *) printf '%s' "${HOME}/.profile" ;;
  esac
}

ensure_path() {
  # shellcheck disable=SC2016 # written literally into the rc file
  local rc line='export PATH="$HOME/.local/bin:$PATH"'
  rc="$(shell_rc)"
  if ! grep -qsF "$PATH_MARK" "$rc" && ! grep -qs '\.local/bin' "$rc"; then
    printf '\n%s\n%s\n' "$PATH_MARK" "$line" >> "$rc"
    say "- added ~/.local/bin to PATH in ${rc}"
  fi
  case ":${PATH}:" in
    *":${BIN_DIR}:"*) ;;
    *) say "- open a new terminal (or run: ${line}) to use octryx-claude here" ;;
  esac
}

remove_path_lines() {
  local rc tmp
  for rc in "${HOME}/.zshrc" "${HOME}/.bash_profile" "${HOME}/.bashrc" "${HOME}/.profile"; do
    grep -qsF "$PATH_MARK" "$rc" || continue
    tmp="$(mktemp "${TMPDIR:-/tmp}/octryx-rc.XXXXXX")"
    awk -v mark="$PATH_MARK" 'skip { skip = 0; next } $0 == mark { skip = 1; next } { print }' "$rc" > "$tmp"
    cat "$tmp" > "$rc"
    rm -f "$tmp"
    say "- removed the octryx-claude PATH line from ${rc}"
  done
}

# --- commands ------------------------------------------------------------------------
cmd_install() {
  # $1 force, $2 no-login, $3 workspace, $4 configure (install, not update: an update keeps the configuration),
  # $5 pet choice (on/off/empty)
  guard_path "$STATE_DIR"; guard_path "$BIN_DIR"
  require_own_shim
  check_claude
  install_package "$1" "$5"
  save_installer_copy
  write_shim
  write_alias
  ensure_path
  local short=''
  # `octryx` names this installation only when it owns the shim and the alias is the installer's (a
  # second installation said "(short: octryx)" while `octryx` kept running the first one).
  if [ -n "$OWN_SHIM" ] && grep -qF "$ALIAS_MARK" "$ALIAS" 2>/dev/null; then short=' (short: octryx)'; fi
  say "- octryx-claude $(cat "$VERSION_FILE") ready: ${SHIM}${short}"
  if [ -n "$4" ]; then
    # The platform (and Workspace) also without a login, so a later plain `octryx-claude login` knows it.
    if [ -n "$3" ]; then
      "$SHIM" configure --base-url "$OCTRYX_BASE_URL" --workspace "$3" >/dev/null || die "could not store the platform URL"
    else
      "$SHIM" configure --base-url "$OCTRYX_BASE_URL" >/dev/null || die "could not store the platform URL"
    fi
  fi
  if [ -z "$2" ]; then
    if [ -n "$3" ]; then
      "$SHIM" login --base-url "$OCTRYX_BASE_URL" --workspace "$3" \
        || die "installed, but the login did not complete; run: octryx-claude login --base-url ${OCTRYX_BASE_URL} --workspace ${3}"
    else
      "$SHIM" login --base-url "$OCTRYX_BASE_URL" \
        || die "installed, but the login did not complete; run: octryx-claude login --base-url ${OCTRYX_BASE_URL}"
    fi
  fi
  start_pet
  "$SHIM" status || true
}

cmd_uninstall() {
  # $1 purge
  local created left=''
  guard_path "$STATE_DIR"; guard_path "$BIN_DIR"
  created="$(cat "$CREATED_DIRS" 2>/dev/null || true)"
  if [ -n "$1" ]; then
    case "$STATE_DIR" in
      "$HOME"|"$HOME/"|"$HOME/.octryx"|"$HOME/.octryx/") die "refused: --purge would delete ${STATE_DIR}" ;;
    esac
    case "$HOME/" in "$STATE_DIR"/*) die "refused: --purge would delete ${STATE_DIR}" ;; esac
    if [ -x "${CURRENT}/bin/python" ]; then
      "${CURRENT}/bin/python" -m octryx_claude.logout || say "- the platform login could not be revoked; it expires by itself"
    fi
  fi
  if [ -e "$SHIM" ]; then
    if grep -qF "$SHIM_MARK" "$SHIM" 2>/dev/null; then rm -f "$SHIM"; say "- removed ${SHIM}"
    else say "- kept ${SHIM}: not written by this installer"
    fi
  fi
  if [ -n "$OWN_SHIM" ] && [ -e "$ALIAS" ] && grep -qF "$ALIAS_MARK" "$ALIAS" 2>/dev/null; then
    rm -f "$ALIAS"; say "- removed ${ALIAS}"
  fi
  remove_path_lines
  remove_pet_agent
  remove_tree "$VENVS_DIR" "${STATE_DIR}/installer" "$VERSION_FILE" || left=1
  if [ -n "$1" ]; then
    remove_tree "$STATE_DIR" || left=1
    remove_created_dirs "$created"  # e.g. ~/.octryx and ~/.local/bin, when this installer created them
    [ -z "$left" ] || die "uninstall did not remove everything (see above); remove what is listed and run it again"
    if [ -e "$STATE_DIR" ]; then say "Uninstalled; login revoked. ${STATE_DIR} holds only the operating system's own files."
    else say "Uninstalled; login revoked and ${STATE_DIR} deleted."
    fi
    if [ "$(uname -s)" = Darwin ]; then
      say "A seat-profile Claude subscription login may remain in the macOS keychain (Claude Code-credentials-*)."
    fi
  else
    remove_created_dirs "$created"
    [ -z "$left" ] || die "uninstall did not remove everything (see above); remove what is listed and run it again"
    say "Uninstalled. Login and settings stay in ${STATE_DIR} (remove them with: uninstall --purge)."
  fi
}

main() {
  local command=install force='' no_login='' purge='' pet='' workspace="$OCTRYX_WORKSPACE"
  case "$OCTRYX_BASE_URL" in *@@*) die "this is the unfilled template; download the installer from your platform" ;; esac
  if [ $# -gt 0 ]; then
    case "$1" in install|update|uninstall) command="$1"; shift ;; esac
  fi
  while [ $# -gt 0 ]; do
    case "$1" in
      --no-login) no_login=1 ;;
      --force) force=1 ;;
      --purge) purge=1 ;;
      --no-pet) pet=off ;;
      --pet) pet=on ;;
      --workspace) [ $# -ge 2 ] || die "--workspace needs a value"; workspace="$2"; shift ;;
      --workspace=*) workspace="${1#--workspace=}" ;;
      -h|--help) say "$USAGE"; return 0 ;;
      *) die "unknown option: $1. ${USAGE}" ;;
    esac
    shift
  done
  resolve_shim
  case "$command" in
    install) cmd_install "$force" "$no_login" "$workspace" 1 "$pet" ;;
    update) cmd_install "$force" 1 "" "" "$pet" ;;
    uninstall) cmd_uninstall "$purge" ;;
  esac
}

main "$@"
