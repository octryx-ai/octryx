#!/bin/bash
# dev-migration-gate.sh — the Alembic migration gate of the local dev launcher.
#
# Sourced by dev-start.sh after scripts/dev-process-ownership.sh, whose dev_say it uses. The caller
# sets BACKEND_DIR (the checkout's backend/) and VENV_DIR (its venv) before sourcing it and calls
# check_migrations before anything starts, as `check_migrations || exit 1`: errexit is then off in
# here, so every step checks its own exit status. Written for bash 3.2 (macOS /bin/bash).
#
# App startup runs Base.metadata.create_all, which papers over a failed or skipped migration, so
# nothing may start unless the database provably sits at the Alembic head. Every step is judged by
# its exit status, never by its wording, and only a revision graph that loaded and is genuinely
# empty may skip. Raw output stays in memory and is never printed or stored: messages can carry
# setting values (pydantic echoes its input, validators quote values), credentials and SQL
# parameters. A failure is reported in launcher words plus facts parsed to a narrow character set.
ALEMBIC_VERSIONS_DIR="$BACKEND_DIR/alembic/versions"

# Messages go through dev_say (printf %s), not the launcher's echo -e helpers: a URL or path in a
# message must not be read as escape sequences.
migration_failed() {  # <reason> [<cause>] [<command that shows the full output>]
  dev_say error "$1"
  if [ -n "${2:-}" ]; then
    dev_say error "Cause: $2"
  fi
  if [ -n "${3:-}" ]; then
    dev_say info "For the full output, which can include secrets, run in $BACKEND_DIR: $3"
  fi
  dev_say error "The backend and frontend were not started."
}

alembic_command() {  # <step>; the command that shows the full output of that Alembic step
  printf 'DATABASE_URL=<the database above> .venv/bin/python -m alembic %s' "$1"
}

# Every awk and sed over tool output runs with LC_ALL=C and a silenced standard error: in a UTF-8
# locale, invalid bytes make awk fail with a message that quotes the input line.

# Revision IDs for display: anything but a [A-Za-z0-9_] token of at most 32 characters (the width
# of alembic_version.version_num) shows as "?".
shown_revisions() {  # <space-separated IDs>
  printf '%s\n' "$1" | LC_ALL=C awk '{
    for (i = 1; i <= NF; i++) printf "%s%s", (i > 1 ? " " : ""), \
      ((length($i) <= 32 && $i ~ /^[A-Za-z0-9_]+$/) ? $i : "?")
  }' 2>/dev/null
}

# Runs `alembic <args>` against <database_url> and prints all it wrote, each standard output line
# marked with a leading "@", so revision listings stay apart from log lines and tracebacks.
# PYTHON_COLORS=0 keeps tracebacks plain for the parser below (Python 3.13+ colors on request).
run_alembic() {  # <database_url> <args...>
  local database_url=$1
  shift
  {
    PYTHON_COLORS=0 DATABASE_URL="$database_url" "$VENV_DIR/bin/python" -m alembic "$@" | LC_ALL=C sed 's/^/@/'
    return "${PIPESTATUS[0]}"
  } 2>&1
}

# The revision IDs that `alembic heads` or `alembic current` listed on standard output, sorted and
# space-separated, so two listings compare regardless of order. Only listing lines count, of the
# form "<id>[ (<annotation>)...]"; with "heads", a line must carry Alembic's head mark. Anything
# else that a revision module or env.py printed is not compared, and shown_revisions masks IDs.
migration_revisions() {  # <run_alembic output> <heads|current>
  local ids
  ids=$(printf '%s\n' "$1" | LC_ALL=C sed -n 's/^@//p' 2>/dev/null | LC_ALL=C awk -v kind="$2" '
    /^[^ ()]+( \([A-Za-z0-9_ .-]+\))*$/ {
      if (kind != "heads" || / \(head\)/ || / \(effective head\)/) print $1
    }' 2>/dev/null | LC_ALL=C sort -u | LC_ALL=C tr '\n' ' ')
  printf '%s' "${ids% }"
}

# Why an Alembic step failed, told only by facts that cannot carry a secret: the exception class
# and the file, line and function of this backend's own code that raised it (a revision script
# first, else the innermost project frame; never the venv or site-packages). Only the first
# unindented line after the frames is read as the exception line, so the rest of a multi-line
# message never is. A command error ("FAILED: <message>") without a traceback is reported as
# CommandError, naming only a revision ID parsed from its one known shape.
alembic_failure_cause() {  # <run_alembic output>
  printf '%s\n' "$1" | LC_ALL=C awk -v backend="$(pwd -P)/" '
    /^Traceback \(most recent call last\):$/ { in_trace = 1; last = ""; script = ""; error = ""; next }
    in_trace && /^  File "/ {
      if (index($0, "  File \"" backend) == 1 && index($0, "  File \"" backend ".venv/") != 1 &&
          !index($0, "/site-packages/") && !index($0, "/dist-packages/")) {
        last = $0
        if (index($0, "/alembic/versions/")) script = $0
      }
      next
    }
    in_trace && /^ / { next }
    in_trace {
      in_trace = 0
      if ($0 ~ /^[A-Za-z_][A-Za-z0-9_.<>]*$/) error = $0
      else if ($0 ~ /^[A-Za-z_][A-Za-z0-9_.<>]*: / || $0 ~ /^[A-Za-z_][A-Za-z0-9_.<>]*:$/) {
        error = $0; sub(/:.*$/, "", error)
      }
      next
    }
    /^@FAILED: / {
      failed = "CommandError"
      if ($0 ~ /^@FAILED: Can.t locate revision identified by .[A-Za-z0-9_]+.$/) {
        revision = $0; sub(/^@FAILED: Can.t locate revision identified by ./, "", revision); sub(/.$/, "", revision)
        if (length(revision) <= 32) failed = failed ": revision " revision " is not in the revision graph of this checkout"
      }
    }
    END {
      if (error == "" || length(error) > 128) { if (failed != "") print failed; exit }
      # `  File "<path>", line <n>, in <function>`; a SyntaxError frame has no function part.
      frame = (script != "") ? script : last
      path = frame; sub(/^  File "/, "", path); sub(/", line [0-9]+(, in .*)?$/, "", path)
      path = substr(path, length(backend) + 1)
      number = frame; sub(/^.*", line /, "", number); sub(/, in .*$/, "", number)
      name = index(frame, ", in ") ? frame : ""; sub(/^.*, in /, "", name)
      if (frame != "" && path ~ "^[A-Za-z0-9_./-]+$" && number ~ "^[0-9]+$") {
        error = error " at " path ":" number
        if (name ~ "^[A-Za-z0-9_<>]+$") error = error " (in " name ")"
      }
      print error
    }' 2>/dev/null
}

has_revision_scripts() {  # <dir>; true when it holds a *.py revision script (__init__.py aside)
  local script
  for script in "$1"/*.py; do
    case ${script##*/} in
      __init__.py) ;;
      *) [ -e "$script" ] && return 0 ;;
    esac
  done
  return 1
}

check_migrations() {
  dev_say info "Checking Alembic migrations..."
  if ! cd "$BACKEND_DIR"; then
    migration_failed "Could not change into $BACKEND_DIR."
    return 1
  fi

  local urls database_url display_database_url output heads current status=0
  # Prints exactly the lines "url=<URL the app will use>" and "display=<it without password,
  # query and fragment>", or "error=<cause>" and fails. Standard error is dropped unread. The raw
  # URL stays in this shell and in the DATABASE_URL of the Alembic processes: never in output, a
  # file or a command line, where `ps` would show it to every local user.
  urls=$("$VENV_DIR/bin/python" - 2>/dev/null <<'PY'
import contextlib
import os
import re
import sys
import traceback


def token(value):
    # Only short identifier-like values are shown; anything else could be a setting value.
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_]{1,64}", text) else "?"


try:
    # Output printed while the settings load must not reach the protocol lines below.
    with contextlib.redirect_stdout(sys.stderr):
        from sqlalchemy.engine import make_url

        from app.config import get_settings

        url = get_settings().database_url
except Exception as error:
    # Error messages are never shown: pydantic echoes every setting value into them, and a
    # validator can quote a value in its own message. Only the error class, the backend frame
    # that raised it, and the pydantic error types with the field names they concern.
    cause = token(type(error).__name__)
    project, venv = os.getcwd() + os.sep, os.path.join(os.getcwd(), ".venv") + os.sep
    own = [
        frame
        for frame in traceback.extract_tb(error.__traceback__)
        if frame.filename.startswith(project) and not frame.filename.startswith(venv)
    ]
    if own:
        path, name = os.path.relpath(own[-1].filename), own[-1].name
        if re.fullmatch(r"[A-Za-z0-9_./-]+", path) and re.fullmatch(r"[A-Za-z0-9_<>]+", name):
            cause += " at " + path + ":" + str(own[-1].lineno) + " (in " + name + ")"
    # app.settings_validation_policy is the boundary that renders a
    # settings failure, and it offers the same field/reason pairs as narrow tokens.
    # Its text is still not printed: only the tokens, through the same filter.
    problems = []
    reasons = getattr(error, "safe_field_reasons", None)
    if isinstance(reasons, tuple):
        for pair in reasons:
            if isinstance(pair, tuple) and len(pair) == 2:
                field = ".".join(token(part) for part in str(pair[0]).split("."))
                problems.append(field + " (" + token(pair[1]) + ")")
    if not problems and type(error).__module__.startswith("pydantic") and hasattr(error, "errors"):
        for item in error.errors(include_input=False, include_url=False, include_context=False):
            field = ".".join(token(part) for part in item["loc"]) or "settings"
            problems.append(field + " (" + token(item["type"]) + ")")
    if problems:
        cause += ": " + ", ".join(problems)
    print("error=" + cause)
    sys.exit(1)
display_url = ""
if url:
    # Parsed as SQLAlchemy parses it for the app and Alembic (a password may hold "?" or "#").
    # The password is masked; query and fragment can carry credentials, tokens or key paths
    # too, so they are dropped and only marked.
    try:
        parsed = make_url(url)
        hidden = bool(parsed.query)
        parsed = parsed.set(query={})
        if parsed.database and "#" in parsed.database:
            hidden = True
            parsed = parsed.set(database=parsed.database.split("#", 1)[0])
        display_url = parsed.render_as_string(hide_password=True) + ("?…" if hidden else "")
    except Exception as error:
        print("error=" + token(type(error).__name__) + ": database_url does not parse as a database URL")
        sys.exit(1)
print("url=" + url)
print("display=" + display_url)
PY
) || status=$?
  if [ "$status" -ne 0 ]; then
    migration_failed "app.config could not resolve the database URL (exit status $status), so no migration ran." \
      "$(printf '%s\n' "$urls" | LC_ALL=C sed -n 's/^error=//p' 2>/dev/null)" \
      '.venv/bin/python -c "from app.config import get_settings; get_settings()"'
    return 1
  fi
  # Exactly two lines, url= then display=. Anything else (a URL spanning lines included) could put
  # the raw URL where the masked one belongs, so it fails closed.
  if ! printf '%s\n' "$urls" | LC_ALL=C awk 'NR == 1 && /^url=/ { u = 1 } NR == 2 && /^display=/ { d = 1 }
      END { exit !(NR == 2 && u && d) }' 2>/dev/null; then
    migration_failed "app.config printed no well-formed database URL, so no migration ran."
    return 1
  fi
  database_url=${urls%%$'\n'*}
  database_url=${database_url#url=}
  display_database_url=${urls#*$'\n'}
  display_database_url=${display_database_url#display=}
  # An empty DATABASE_URL would make alembic/env.py fall back to alembic.ini: another database.
  if [ -z "$database_url" ]; then
    migration_failed "app.config resolved an empty database URL, so no migration ran."
    return 1
  fi
  dev_say info "Using database: $display_database_url"

  output=$(run_alembic "$database_url" heads) || status=$?
  if [ "$status" -ne 0 ]; then
    migration_failed "'alembic heads' exited with status $status: Alembic could not load the revision graph, so no migration ran." \
      "$(alembic_failure_cause "$output")" "$(alembic_command heads)"
    return 1
  fi
  heads=$(migration_revisions "$output" heads)
  if [ -z "$heads" ]; then
    # Alembic lists no revision for a missing or misconfigured versions directory as well.
    if [ ! -d "$ALEMBIC_VERSIONS_DIR" ]; then
      migration_failed "'alembic heads' listed no revision because $ALEMBIC_VERSIONS_DIR is missing."
      return 1
    fi
    if has_revision_scripts "$ALEMBIC_VERSIONS_DIR"; then
      migration_failed "'alembic heads' listed no revision although $ALEMBIC_VERSIONS_DIR holds revision scripts; check version_locations in backend/alembic.ini."
      return 1
    fi
    dev_say warn "No Alembic revisions in $ALEMBIC_VERSIONS_DIR — skipping migrations."
    return 0
  fi
  case $heads in
    *" "*)
      migration_failed "'alembic heads' lists several heads ($(shown_revisions "$heads")), and 'alembic upgrade head' needs exactly one. Merge them first ('alembic merge heads')."
      return 1
      ;;
  esac

  output=$(run_alembic "$database_url" upgrade head) || status=$?
  if [ "$status" -ne 0 ]; then
    migration_failed "'alembic upgrade head' exited with status $status; the database is not at the Alembic head." \
      "$(alembic_failure_cause "$output")" "$(alembic_command "upgrade head")"
    return 1
  fi
  output=$(run_alembic "$database_url" current) || status=$?
  if [ "$status" -ne 0 ]; then
    migration_failed "'alembic current' exited with status $status after the upgrade, so the schema version is unverified." \
      "$(alembic_failure_cause "$output")" "$(alembic_command current)"
    return 1
  fi
  # The current revisions are compared, never shown: a line a revision module printed on its own
  # looks just like a revision that is not a head.
  current=$(migration_revisions "$output" current)
  if [ "$current" != "$heads" ]; then
    migration_failed "The database is not at the Alembic head '$(shown_revisions "$heads")', although 'alembic upgrade head' reported success." \
      "" "$(alembic_command current)"
    return 1
  fi
  dev_say ok "Database is at Alembic head $(shown_revisions "$heads")"
  return 0
}
