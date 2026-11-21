#!/bin/bash
# dev-process-ownership.sh — process ownership for the local dev launcher.
#
# Sourced by dev-start.sh and dev-stop.sh. The launcher may only signal a process it can prove
# it started from this checkout. The proof is a launch record written next to the PID file:
#
#   pids/<service>.pid     the PID (plain integer)
#   pids/<service>.launch  pid=<PID> and start=<process start time>
#
# A recorded process counts as owned only when all of these hold; anything else fails closed:
#   - the PID file holds a PID other than 1 and that process is alive
#   - the launch record names the same PID
#   - the live process start time equals the recorded one (a reused PID starts later)
#   - the process leads its own process group (launches always start a new session)
#   - its working directory is the expected service directory of this checkout
# Owned services are stopped as a whole process group (npm -> vite, uvicorn reloader -> worker),
# but never from a shell inside that group: the group signal would end the stop midway.
# Only a proven mismatch removes the PID file and launch record. A failed lookup (ps or lsof error)
# proves nothing either way, so both files stay for a later run and nothing is signalled.
# Every other process, including any other listener on the dev ports, is reported and left running.
#
# Written for bash 3.2 (macOS /bin/bash) and safe under `set -eu`: value lookups always
# succeed and print an empty string when the value is unknown.

: "${DEV_LAUNCHER_TAG:=dev-launcher}"
: "${DEV_LAUNCHER_STOP_TIMEOUT:=10}"

# Set by dev_verify_owned when it refuses a process.
DEV_OWNERSHIP_REASON=""

dev_say() {  # <info|ok|warn|error> <message>
  local color label=""
  case "$1" in
    ok) color='\033[0;32m'; label=' ✓' ;;
    warn) color='\033[1;33m'; label=' WARNING:' ;;
    error) color='\033[0;31m'; label=' ✗' ;;
    *) color='\033[0;36m' ;;
  esac
  printf '%b[%s]%s\033[0m %s\n' "$color" "$DEV_LAUNCHER_TAG" "$label" "$2"
}

dev_trim() {
  local value=$1
  value=${value#"${value%%[![:space:]]*}"}
  value=${value%"${value##*[![:space:]]}"}
  printf '%s' "$value"
}

dev_is_positive_integer() {
  case "$1" in
    '' | *[!0-9]* | 0*) return 1 ;;
  esac
  return 0
}

dev_launch_record_path() {  # <pid_file>
  printf '%s' "${1%.pid}.launch"
}

dev_read_pid_file() {  # <pid_file>; prints the PID, or nothing when the file holds no valid PID
  local content=""
  if [ -f "$1" ]; then
    content=$(dev_trim "$(cat "$1" 2>/dev/null || true)")
  fi
  # PID 1 is never a launched dev server, and `kill -- -1` would signal every process of the user.
  # Over 9 digits is no PID and must never reach a signal call where a 32-bit pid_t could wrap it.
  if dev_is_positive_integer "$content" && [ "$content" != 1 ] && [ "${#content}" -le 9 ]; then
    printf '%s' "$content"
  fi
}

dev_record_value() {  # <record_file> <key>
  local line
  [ -f "$1" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    case "$line" in
      "$2="*)
        printf '%s' "${line#"$2="}"
        return 0
        ;;
    esac
  done <"$1"
  return 0
}

# Prints alive, gone or unknown. `ps -p` exits 1 both for a PID that does not exist and for its
# own errors, so "gone" is only concluded from a full listing that still shows this shell.
dev_process_state() {  # <pid>; sees processes of other users too, unlike kill -0
  local listing listed seen_self=""
  listing=$(ps -A -o pid= 2>/dev/null) || listing=""
  for listed in $listing; do
    if [ "$listed" = "$1" ]; then
      printf 'alive'
      return 0
    fi
    if [ "$listed" = "$$" ]; then
      seen_self=1
    fi
  done
  if [ -n "$seen_self" ]; then
    printf 'gone'
  else
    printf 'unknown'
  fi
}

dev_process_start_time() {  # <pid>; pinned TZ/locale so the value compares stably
  local out
  out=$(TZ=UTC LC_ALL=C ps -p "$1" -o lstart= 2>/dev/null) || out=""
  dev_trim "$out"
}

dev_process_pgid() {  # <pid>
  local out
  out=$(ps -p "$1" -o pgid= 2>/dev/null) || out=""
  dev_trim "$out"
}

dev_process_user() {  # <pid>
  local out
  out=$(ps -p "$1" -o user= 2>/dev/null) || out=""
  dev_trim "$out"
}

dev_process_program() {  # <pid>; the executable only, as full command lines can carry secrets
  local out
  out=$(ps -p "$1" -o comm= 2>/dev/null) || out=""
  dev_trim "$out"
}

dev_process_cwd() {  # <pid>; empty when it cannot be determined
  local out=""
  if [ -d /proc ] && [ -e "/proc/$1/cwd" ]; then
    out=$(readlink "/proc/$1/cwd" 2>/dev/null) || out=""
  elif command -v lsof >/dev/null 2>&1; then
    out=$(lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1) || out=""
  fi
  printf '%s' "$out"
}

dev_describe_process() {  # <pid>
  local user program cwd
  user=$(dev_process_user "$1")
  program=$(dev_process_program "$1")
  cwd=$(dev_process_cwd "$1")
  printf '      PID %s (user %s)\n' "$1" "${user:-unknown}"
  printf '      program: %s\n' "${program:-unknown}"
  printf '      cwd:     %s\n' "${cwd:-unknown}"
}

# Starts <command...> detached in <work_dir> as a new session, so it leads its own process
# group, appends its output to <log_file>, then writes the launch record and the PID file.
# Both files are written via rename, so readers never see a partial file, and the record is
# in place before the PID file that points to it.
dev_launch_detached() {  # <python> <work_dir> <pid_file> <log_file> <command...>
  local python_bin=$1 work_dir=$2 pid_file=$3 log_file=$4
  shift 4
  local record staged pid start
  record=$(dev_launch_record_path "$pid_file")
  staged="$pid_file.new"
  # Staging files left by an interrupted launch go first: writing into a leftover symlink would
  # put the new content wherever it points.
  rm -f "$staged" "$record.new"
  "$python_bin" - "$work_dir" "$staged" "$log_file" "$@" <<'PY' || return 1
import subprocess
import sys

work_dir, pid_path, log_path, *command = sys.argv[1:]
with open(log_path, "ab", buffering=0) as log:
    process = subprocess.Popen(
        command,
        cwd=work_dir,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        close_fds=True,
        start_new_session=True,
    )
with open(pid_path, "w", encoding="utf-8") as handle:
    handle.write(f"{process.pid}\n")
PY
  pid=$(dev_read_pid_file "$staged")
  if [ -z "$pid" ]; then
    rm -f "$staged"
    dev_say error "Launching '$*' did not produce a PID."
    return 1
  fi
  start=$(dev_process_start_time "$pid")
  printf 'pid=%s\nstart=%s\n' "$pid" "$start" >"$record.new" || return 1
  mv -f "$record.new" "$record" || return 1
  mv -f "$staged" "$pid_file"
}

# True while the process recorded in <pid_file> is still the one that was launched: same PID in
# PID file and launch record, and the recorded start time. A bare PID would accept a reused PID.
dev_launched_process_running() {  # <pid_file>
  local pid record recorded_start
  pid=$(dev_read_pid_file "$1")
  [ -n "$pid" ] || return 1
  record=$(dev_launch_record_path "$1")
  [ "$(dev_record_value "$record" pid)" = "$pid" ] || return 1
  recorded_start=$(dev_record_value "$record" start)
  [ -n "$recorded_start" ] && [ "$(dev_process_start_time "$pid")" = "$recorded_start" ]
}

# Returns 0 only when <pid> is the process this checkout launched in <service_dir>. Otherwise sets
# DEV_OWNERSHIP_REASON and returns 1 when the launch record provably does not describe <pid>, or 2
# when a lookup failed, which proves nothing either way.
dev_verify_owned() {  # <pid> <launch_record> <service_dir>
  local pid=$1 record=$2 service_dir=$3
  local recorded_pid recorded_start live_start pgid cwd
  DEV_OWNERSHIP_REASON=""
  if [ ! -f "$record" ]; then
    DEV_OWNERSHIP_REASON="there is no launch record for it (the PID file was not written by this launcher, e.g. by hand)"
    return 1
  fi
  recorded_pid=$(dev_record_value "$record" pid)
  recorded_start=$(dev_record_value "$record" start)
  if [ "$recorded_pid" != "$pid" ] || [ -z "$recorded_start" ]; then
    DEV_OWNERSHIP_REASON="its launch record is incomplete or names another PID"
    return 1
  fi
  live_start=$(dev_process_start_time "$pid")
  if [ -z "$live_start" ]; then
    DEV_OWNERSHIP_REASON="its start time could not be read"
    return 2
  fi
  if [ "$live_start" != "$recorded_start" ]; then
    DEV_OWNERSHIP_REASON="it started at '$live_start', not at the recorded '$recorded_start' (the PID now belongs to another process)"
    return 1
  fi
  pgid=$(dev_process_pgid "$pid")
  if [ -z "$pgid" ]; then
    DEV_OWNERSHIP_REASON="its process group could not be read"
    return 2
  fi
  if [ "$pgid" != "$pid" ]; then
    DEV_OWNERSHIP_REASON="it does not lead its own process group (group $pgid)"
    return 1
  fi
  cwd=$(dev_process_cwd "$pid")
  if [ -z "$cwd" ]; then
    DEV_OWNERSHIP_REASON="its working directory could not be read"
    return 2
  fi
  # -ef compares device and inode, so symlinked or differently spelled paths still match.
  if ! [ "$cwd" -ef "$service_dir" ]; then
    DEV_OWNERSHIP_REASON="its working directory is '$cwd', not '$service_dir'"
    return 1
  fi
  return 0
}

dev_group_alive() {  # <pgid>
  kill -0 -- "-$1" 2>/dev/null
}

# Seconds an owned group gets between SIGTERM and SIGKILL: DEV_LAUNCHER_STOP_TIMEOUT when it is a
# whole number from 1 to 300, else 10. Unbounded values overflowed the poll count below.
dev_stop_timeout() {  # prints the timeout; returns 1 when DEV_LAUNCHER_STOP_TIMEOUT was rejected
  local value=${DEV_LAUNCHER_STOP_TIMEOUT:-}
  if dev_is_positive_integer "$value" && [ "${#value}" -le 3 ] && [ "$value" -le 300 ]; then
    printf '%s' "$value"
    return 0
  fi
  printf '10'
  return 1
}

dev_wait_group_exit() {  # <pgid> <seconds, 1-300>; returns 0 once no process of the group is left
  local tries=$(($2 * 5))
  while [ "$tries" -gt 0 ]; do
    dev_group_alive "$1" || return 0
    sleep 0.2
    tries=$((tries - 1))
  done
  ! dev_group_alive "$1"
}

# Stops the service recorded in <pid_file> if, and only if, this checkout provably launched it.
# Records that provably do not describe the live process are removed; the processes they point
# to are never signalled. Returns 1 when the service may still be running: a lookup failed, this
# shell runs inside the owned group, or the group survived SIGTERM and SIGKILL.
dev_stop_owned() {  # <label> <pid_file> <service_dir>
  local label=$1 pid_file=$2 service_dir=$3
  local record pid verdict=0 self_pid caller_pgid grace
  record=$(dev_launch_record_path "$pid_file")
  if [ ! -e "$pid_file" ]; then
    rm -f "$record"
    dev_say info "$label: no PID file, nothing to stop."
    return 0
  fi
  pid=$(dev_read_pid_file "$pid_file")
  if [ -z "$pid" ]; then
    rm -f "$pid_file" "$record"
    dev_say warn "$label: $pid_file did not hold a valid PID; removed it without signalling anything."
    return 0
  fi
  case $(dev_process_state "$pid") in
    gone)
      rm -f "$pid_file" "$record"
      dev_say info "$label: PID $pid is no longer running; removed the stale PID file."
      return 0
      ;;
    unknown)
      dev_say error "$label: could not tell whether PID $pid is still running (ps failed); kept $pid_file and its launch record, nothing was signalled."
      return 1
      ;;
  esac
  dev_verify_owned "$pid" "$record" "$service_dir" || verdict=$?
  if [ "$verdict" -eq 1 ]; then
    rm -f "$pid_file" "$record"
    dev_say warn "$label: PID $pid from $pid_file was left running because $DEV_OWNERSHIP_REASON."
    dev_describe_process "$pid"
    dev_say warn "Removed the stale PID file. Stop PID $pid yourself only if you know it is yours."
    return 0
  fi
  if [ "$verdict" -ne 0 ]; then
    dev_say error "$label: PID $pid from $pid_file was not stopped because $DEV_OWNERSHIP_REASON, so its ownership is unknown."
    dev_describe_process "$pid"
    dev_say error "Kept $pid_file and its launch record for a later run; nothing was signalled."
    return 1
  fi
  # A group signal also reaches the sender when it belongs to that group (for example dev-stop.sh
  # run by a command the server spawned), which would end this script in the middle of the stop.
  self_pid=${BASHPID:-$$}
  caller_pgid=$(dev_process_pgid "$self_pid")
  if [ -z "$caller_pgid" ]; then
    dev_say error "$label (PID $pid) was not stopped because the process group of this shell could not be read, so the stop might hit this shell. Kept $pid_file and its launch record."
    return 1
  fi
  if [ "$caller_pgid" = "$pid" ]; then
    dev_say error "$label (PID $pid) was not stopped: this shell runs inside its process group, and the group signal would end this script too. Run ./dev-stop.sh from a terminal outside the dev servers."
    return 1
  fi
  if ! grace=$(dev_stop_timeout); then
    dev_say warn "DEV_LAUNCHER_STOP_TIMEOUT must be a whole number of seconds from 1 to 300; using $grace."
  fi

  dev_say info "Stopping $label (PID $pid and its process group)..."
  kill -TERM -- "-$pid" 2>/dev/null || true
  if ! dev_wait_group_exit "$pid" "$grace"; then
    # The group existed at every poll since the validated SIGTERM, and a process group ID is
    # not reused while the group exists, so this still targets the owned group only.
    dev_say warn "$label did not exit within ${grace}s after SIGTERM; sending SIGKILL to its process group."
    kill -KILL -- "-$pid" 2>/dev/null || true
    if ! dev_wait_group_exit "$pid" 5; then
      dev_say error "$label (process group $pid) is still running after SIGKILL; stop it manually."
      return 1
    fi
  fi
  rm -f "$pid_file" "$record"
  dev_say ok "$label stopped (was PID $pid)."
  return 0
}

dev_port_listeners() {  # <port>; PIDs with a LISTEN socket on the port (client sockets excluded)
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null || true
}

# Start-time guard: fails with diagnostics and a manual action when anything listens on
# <port>. The listener is never signalled.
dev_require_port_free() {  # <port> <label>
  local port=$1 label=$2 pids pid
  if ! command -v lsof >/dev/null 2>&1; then
    dev_say error "lsof is required to check who listens on port $port ($label); install it, then rerun ./dev-start.sh."
    return 1
  fi
  pids=$(dev_port_listeners "$port")
  [ -n "$pids" ] || return 0
  dev_say error "Port $port ($label) is already in use by a process this launcher does not own. It was left running:"
  for pid in $pids; do
    dev_describe_process "$pid"
  done
  pids=$(printf '%s' "$pids" | tr '\n' ' ')
  dev_say error "Stop it yourself if that is safe (kill $(dev_trim "$pids")) or free port $port another way, then rerun ./dev-start.sh."
  return 1
}

# Stop-time report: names every remaining listener on <port> and leaves it running.
dev_report_port_listeners() {  # <port> <label>
  local port=$1 label=$2 pids pid
  if ! command -v lsof >/dev/null 2>&1; then
    dev_say warn "lsof is not installed; cannot report who still listens on port $port ($label)."
    return 0
  fi
  pids=$(dev_port_listeners "$port")
  [ -n "$pids" ] || return 0
  dev_say warn "Port $port ($label) is still in use. Left running:"
  for pid in $pids; do
    dev_describe_process "$pid"
  done
  return 0
}
