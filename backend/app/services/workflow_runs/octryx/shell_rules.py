"""The shell an octryx-claude session may use in a workflow run's phase: structure, not string matching.

A shell command's text cannot be matched safely (``git -C . push``, ``x=gh; $x pr create``, ``pytest > file``), so:

- **free shell** only in a ``deliver`` phase that offers ``bash`` and has no path rules (:func:`free_shell`); there
  the run rules (``tool_policy``) and the capability decision are a guardrail against mistakes, not a boundary;
- **every other phase** runs plain argv commands only (``command_match.strict_argv``: no redirection, variable,
  substitution, environment assignment, wrapper or nested shell), each of them either
  - one of the Workspace's test commands, when the phase runs tests, with an **allow-list** of arguments: pytest
    takes test paths / node ids and ``-k -m -r --tb -x -q -v --lf`` only; other runners take test paths only and
    are refused in phases that protect confirmed tests, or
  - a closed set of read-only commands with their writing or executing options refused (:data:`READ_ONLY`);
  - a path-qualified first word (``./ls``, ``scripts/git``) only when it names a known interpreter;
  - in a phase that runs tests, also the repository's **declared** test and lint commands exactly as the repository
    registration declares them (``workspace/spec``; the same argv, word for word — the declaration is a person's,
    the agent changes nothing about it; a CI-derived proposal is no declaration) (:func:`declared_command`).
- a ``git push`` never runs on the device during a run: the platform pushes the reviewed change
  (``workflow_action_request`` → ``scm.push``).

**Relaxed** after benchmark runs (Claude Haiku: 34 PreToolUse refusals
``outside-phase-tools`` in 7 stories, each one a lost turn for a harmless read or test run). The safety intent stays:
nothing writes outside the repository, nothing reaches the network, nothing loads foreign code or reads secrets.

- pytest takes the common options that only change what it prints or which tests it selects (:data:`PYTEST_FLAGS`,
  :data:`PYTEST_VALUE_OPTIONS`, combined short flags such as ``-xvs``, ``-p no:<plugin>`` which only switches a plugin
  off, ``--ignore`` / ``--deselect`` of repository paths): the agent ran ``pytest -s``, ``--no-header``,
  ``-p no:cacheprovider``, ``--maxfail=1`` and was refused each time. Options that load code or write files
  (``-p <plugin>``, ``-c``, ``-o``, ``-W``, ``--rootdir``, ``--basetemp``, ``--junitxml``, ``@args``) stay refused;
- read-only text tools at the end of a pipe (``sort`` without its output options, ``uniq`` with at most an input file,
  ``cut``, ``tr``, ``nl``, ``basename``, ``dirname``, ``realpath``, ``du``, ``jq``) and ``cd`` into a folder of the
  repository (a relative path without ``..``): ``cd frontend && ls``, ``grep -c x f | sort`` were refused;
- output thrown away (``2>/dev/null``) is no redirection to a file (``command_match.strict_argv``);
- the declared test command followed by read-only pipe stages (``<declared> 2>&1 | tail -30``) runs in a phase that
  runs tests (:func:`declared_with_readers`); the phase's evidence still counts only the verbatim command;
- before a CI pipeline step (``pipeline_after``) ``pytest -q`` is not asked again with ``-v``: the pipeline
  writes its own JUnit report, the agent's output names nothing the platform needs (``tool_policy``).

**Admin policy, short hard-deny list (too much security blocks the system; an admin sets what a
phase may run).** Without it, ``git -C <repo> log``, ``git status | head``, ``cd <repo>; ls``
would be refused in the coordinator's and the items' phases. So:

- a command segment also runs when the Workspace's **command safety** read-only lists admit it
  (:func:`workspace_reads`: Settings → Security → Command safety, platform-wide with a per-Workspace override —
  ``diagnosis_read_only_commands`` and ``diagnosis_git_subcommands`` with their closed option tables, so
  ``git -C <dir> status|log|diff|show|branch --list|rev-parse``, ``cd``, ``grep``, ``ls``, ``cat``, ``find``,
  ``wc``, ``head``, ``tail`` and the like by default); the admin widens or narrows it there, nothing here is fixed;
- a short **hard-deny list** holds in every phase, free shell too (:func:`hard_denied`): reading credentials
  (environment dumps, ``.env``, keys, cloud and git credential files), a recursive or forced ``rm`` of anything
  outside the work folder, and uploads to the network (``curl -d/-T/-F``, ``wget --post-*``, ``scp``, ``sftp``,
  ``rsync`` to a host, ``nc``); ``git push`` (also ``--force``) never runs during a run (``tool_policy``). The
  Workspace's own blocked patterns (``always_deny_patterns``) apply on top (``capability_decision``).

**Test runs and the app under test.** Without these rules
``timeout 300 python -m pytest -v tests/x.py 2>&1 | tail -60`` was refused, the app could not be started
for a manual check, and the browser could not start in Claude Code's sandbox. In a phase that runs tests now:

- a test command may stand behind ``timeout <duration>`` (:func:`test_command`);
- the app under test may be started, also in the background (a trailing ``&``): ``<python> -m <module> …``,
  ``<python> <file>.py …`` of the repository, ``uvicorn`` / ``flask run`` (:func:`app_start`) — it binds 127.0.0.1
  on any port inside the sandbox; the test code the same phase runs is the repository's code just as much;
- ``curl`` / ``wget`` may read from the app on 127.0.0.1 / localhost (:func:`loopback_read`; anything that sends
  data stays on the hard-deny list); ``sleep <seconds>`` waits for it;
- the launcher runs every test run outside Claude Code's sandbox (``octryx-claude`` ``local_tests``), so the
  device's Chrome starts in any test command form.

A **full run** of a declared test command (:func:`full_suite_run`) is the command with the same selection: its own
words, plus options that only change the output or stop at the first failure, behind ``timeout`` and piped into
readers; a piped run is green only by the summary pytest printed (:func:`run_green`), since the pipe hides the exit
code.
"""

from __future__ import annotations

import posixpath
import re
import shlex
from typing import Any

from app.services.agent_gateway.command_strict import strict_argv
from app.services.agent_gateway.command_tokens import Segment

from .pytest_args import _DURATION, _test_path, test_command, without_timeout
from .read_only_commands import _KNOWN_BINARY, _PYTHON_NAME, _command_name, read_only

SHELL_FREE = "free"
SHELL_STRICT = "strict"  # the team's choice per node; the Workspace's is tool_defaults


def free_shell(phase: dict[str, Any]) -> bool:
    """Free ``bash`` in a deliver phase that offers it and protects no path, or in a phase whose node asks for it
    (``config.shell: "free"``, epic-delivery's story session) and protects no path either.

    Without it, the story session's ``python --version`` was refused as "not a
    plain test or read-only command"; plain Claude Code, which this session is meant to equal (26 min, 0
    interventions), runs its shell freely. The hard-deny list (push, credentials, SCM and upload clients) and Claude
    Code's own sandbox still hold there."""
    tools = phase.get("tools") or {}
    rules = phase.get("path_rules") or {}
    if rules.get("write") or rules.get("protect_confirmed_tests"):
        return False
    if phase.get("shell") == SHELL_FREE:
        return True
    return ("bash" in set(tools.get("allow") or []) and "bash" not in set(tools.get("deny") or [])
            and phase.get("capability_class") == "deliver")


def workspace_reads(segment: Segment, exec_config: dict[str, Any] | None) -> bool:
    """The Workspace's command safety admits ``segment`` as a read (its read-only lists and their closed option
    tables, ``security_analyzer.read_only_command_finding``); the admin changes the lists, not this code."""
    if not exec_config or "diagnosis_read_only_commands" not in exec_config:
        return False
    from ...security_analyzer.builtins import read_only_command_finding

    return read_only_command_finding(shlex.join(segment), exec_config).action == "allow"


_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
# Modules that install, build environments or open an interactive tool: never "the app".
_NOT_AN_APP = frozenset({"pip", "ensurepip", "venv", "virtualenv", "site", "pydoc", "idlelib", "code", "pdb",
                         "pytest", "unittest", "build", "twine", "uv", "poetry", "pipx"})
_APP_SERVERS = frozenset({"uvicorn", "flask", "gunicorn", "hypercorn"})
_LOOPBACK_URL = re.compile(r"^(?:https?://)?(?:127\.0\.0\.1|localhost|\[::1\])(?::\d{1,5})?(?:[/?#]\S*)?$")
_PROBE_OPTIONS = frozenset({"-s", "-S", "-f", "-i", "-I", "-v", "-L", "-sS", "-fsS", "-sf", "-fs", "-sSf", "-q",
                            "--silent", "--show-error", "--fail", "--include", "--head", "--location", "--verbose",
                            "--compressed", "-O-", "--quiet", "-qO-"})
_PROBE_VALUE_OPTIONS = frozenset({"--max-time", "-m", "--connect-timeout", "-w", "--write-out", "-H", "--header",
                                  "-o", "--output", "--retry", "--retry-delay", "-T", "--timeout", "--tries"})


def _interpreter(word: str) -> bool:
    name = posixpath.basename(word)
    return bool(_PYTHON_NAME.match(name)) and ("/" not in word or bool(_KNOWN_BINARY.match(word))
                                                or ".." not in word.split("/") and not word.startswith(("/", "~")))


def app_start(segment: Segment) -> bool:
    """Starting the repository's app: ``<python> -m <module> …``, ``<python> <file>.py …`` inside the repository,
    or an app server (``uvicorn``, ``flask run``, ``gunicorn``, ``hypercorn``) by name or from the folder's venv."""
    segment = without_timeout(segment)
    if len(segment) < 2:
        return False
    first = segment[0]
    if _interpreter(first):
        if segment[1] == "-m":
            return len(segment) > 2 and bool(_MODULE.match(segment[2])) and segment[2].split(".")[0] not in _NOT_AN_APP
        script = segment[1]
        return script.endswith(".py") and _test_path(script)
    name = posixpath.basename(first)
    in_venv = "/" not in first or (".." not in first.split("/") and not first.startswith(("/", "~")))
    return name in _APP_SERVERS and in_venv and (name != "flask" or "run" in segment[1:3])


def loopback_read(segment: Segment) -> bool:
    """``curl`` / ``wget`` reading from the app on this machine only (every URL on 127.0.0.1, localhost or ::1;
    output to the terminal or ``/dev/null``)."""
    name = _command_name(segment)
    if name not in ("curl", "wget"):
        return False
    urls, index, args = 0, 0, list(segment[1:])
    while index < len(args):
        token = args[index]
        option, _sep, value = token.partition("=")
        if option in _PROBE_VALUE_OPTIONS:
            target = value if _sep else (args[index + 1] if index + 1 < len(args) else "")
            if option in ("-o", "--output") and target not in ("/dev/null", "-"):
                return False
            if option in ("-T",) and name == "curl":
                return False  # curl -T uploads
            index += 1 if _sep else 2
            continue
        if token in _PROBE_OPTIONS:
            index += 1
            continue
        if token.startswith("-") or not _LOOPBACK_URL.match(token):
            return False
        urls += 1
        index += 1
    return urls > 0


def _sleep(segment: Segment) -> bool:
    return len(segment) == 2 and segment[0] == "sleep" and bool(_DURATION.match(segment[1]))


def _background(command: str) -> tuple[str, bool]:
    """``command`` without one trailing ``&`` (run in the background), and whether it had one."""
    text = str(command or "").rstrip()
    if text.endswith("&") and not text.endswith("&&") and not text.endswith(">&"):
        return text[:-1].rstrip(), True
    return text, False


def strict_shell_allows(command: str, *, runs_tests: bool, test_prefixes: tuple[tuple[str, ...], ...],
                        protected: bool = False, exec_config: dict[str, Any] | None = None) -> bool:
    """A command of a phase without free shell: plain argv, each a test command (if the phase runs tests), a
    read-only command, or a read the Workspace's command safety admits; in a phase that runs tests also the app
    under test started (in the background too), read from on loopback, and waited for."""
    text, background = _background(command)
    if background and not runs_tests:
        return False
    segments = strict_argv(text)
    if segments is None:
        return False
    if background:
        return all(app_start(segment) or (_command_name(segment) == "cd" and read_only(segment))
                   for segment in segments) and any(app_start(segment) for segment in segments)
    return all(
        read_only(segment) or workspace_reads(segment, exec_config)
        or (runs_tests and (test_command(segment, test_prefixes, protected=protected) or app_start(segment)
                            or loopback_read(segment) or _sleep(segment)))
        for segment in segments)


__all__ = ["SHELL_STRICT", "app_start", "free_shell", "loopback_read", "strict_shell_allows", "workspace_reads"]
