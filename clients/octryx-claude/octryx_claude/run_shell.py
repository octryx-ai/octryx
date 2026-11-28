"""The platform's hard-deny list of a workflow run, evaluated on the device (stdlib only, no I/O)."""

from __future__ import annotations

import posixpath
import re

from .shell_parse import Segment, command_segments, git_normalized, segment_matches, without_data_heredocs

# --- workflow_runs.octryx.shell_rules: the hard-deny list -----------------------------------------------------------

_CREDENTIAL_FILE = re.compile(
    r"(?:^|[\s/'\"=])(?:\.env(?:\.(?!example\b|sample\b|template\b|dist\b)[\w-]+)?|id_rsa|id_dsa|id_ecdsa|"
    r"id_ed25519|[\w.-]+\.pem|[\w.-]+\.p12|\.netrc|\.git-credentials|\.pypirc|\.npmrc|\.aws/credentials|"
    r"\.kube/config|\.docker/config\.json|\.ssh/[\w.-]+)(?=$|[\s'\"|;&)])")
_ENVIRONMENT_DUMP = re.compile(r"(?:^|[;&|(\n]\s*)(?:env\s*(?=$|[;&|)\n])|printenv\b)")
_CREDENTIAL_COMMANDS = (("printenv",), ("git", "credential"), ("security", "find-generic-password"),
                        ("security", "find-internet-password"), ("security", "dump-keychain"))
_UPLOAD_CLIENTS = frozenset({"scp", "sftp", "ftp", "nc", "ncat", "netcat", "socat"})
_CURL_UPLOAD = re.compile(
    r"^(?:-T|--upload-file|-d|--data(?:-[a-z]+)?|-F|--form(?:-string)?|--json)(?:=.*)?$|^-[dFT].+")
_WGET_UPLOAD = re.compile(r"^--(?:post-data|post-file|body-data|body-file|method)(?:=.*)?$")
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _outside(path: str) -> bool:
    return path.startswith(("/", "~")) or ".." in path.split("/") or path in ("*", ".", "./")


# A write to the app under test on this machine: every URL is loopback and no file is read into the request. Live
# (local epic-delivery run 1, S1): ``curl -s -X PUT http://127.0.0.1:$P/api/profile`` (the session checking
# its own API's 405 and 413 answers) was refused as an upload. A file sent anywhere (``-d @x``, ``-T``, ``-F f=@x``)
# stays refused, loopback included.
_LOOPBACK_HOST = re.compile(r"^(?:https?://)?(?:127\.0\.0\.1|localhost|\[::1\])(?:[:/?#]\S*)?$", re.IGNORECASE)
_HOST_LIKE = re.compile(r"^(?:[a-z][a-z0-9+.-]*://\S+|localhost(?:[:/?#]\S*)?|\[[0-9a-fA-F:]+\](?:[:/?#]\S*)?|"
                        r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?::[^/\s]*)?(?:/\S*)?)$", re.IGNORECASE)


def _app_write(args: list[str]) -> bool:
    if any(arg in ("-T", "--upload-file") or arg.startswith(("-T", "@", "-d@", "-F")) and "@" in arg
           or "=@" in arg for arg in args):
        return False
    targets = [arg for arg in args if not arg.startswith("-") and _HOST_LIKE.match(arg)]
    return bool(targets) and all(_LOOPBACK_HOST.match(arg) for arg in targets)


def _hard_segment(segment: Segment) -> str | None:
    name = posixpath.basename(segment[0]) if segment else ""
    args = list(segment[1:])
    if any(tuple(segment[:len(words)]) == words for words in _CREDENTIAL_COMMANDS):
        return "it reads credentials"
    if name == "rm" and any(flag.startswith("-") and ("r" in flag.lower() or "f" in flag) for flag in args) and any(
            _outside(arg) for arg in args if not arg.startswith("-")):
        return "it removes files outside the work folder"
    if name in _UPLOAD_CLIENTS:
        return "it sends data over the network"
    remote = [arg for arg in args if ":" in arg and not arg.startswith(("/", ".", "-"))]
    if name == "rsync" and remote:
        return "it sends data over the network"
    if name == "curl" and (any(_CURL_UPLOAD.match(arg) for arg in args) or any(
            arg in ("-X", "--request") and index + 1 < len(args) and args[index + 1].upper() in _WRITE_METHODS
            for index, arg in enumerate(args))) and not _app_write(args):
        return "it sends data over the network"
    if name == "wget" and any(_WGET_UPLOAD.match(arg) for arg in args):
        return "it sends data over the network"
    return None


def hard_denied(command: str) -> str | None:
    text = without_data_heredocs(command or "")
    if _CREDENTIAL_FILE.search(text):
        return "it reads a credential file"
    if _ENVIRONMENT_DUMP.search(text):
        return "it reads credentials"
    for segment in command_segments(command) or []:
        if (why := _hard_segment(tuple(segment))) is not None:
            return why
    return None


# --- workflow_runs.octryx.tool_policy: push, SCM and Jira clients -----------------------------------------------------

REASON_HARD_DENY = "run_hard_deny"
REASON_SCM_CLIENT = "platform_action_required"
REASON_PUSH_BY_PLATFORM = "push_by_platform"
SCM_CLIENTS = frozenset({"gh", "glab", "hub", "jira", "acli", "bb"})
HTTP_CLIENTS = frozenset({"curl", "wget", "http", "https", "xh", "httpie"})
DEFAULT_SCM_HOSTS = frozenset({"github.com", "api.github.com", "gitlab.com", "bitbucket.org", "api.bitbucket.org",
                               "atlassian.net", "atlassian.com"})
SCM_MESSAGE = ("During a workflow run, Jira, pull requests and CI go through the platform (workflow_action_request): "
               "no SCM or Jira client on this device.")
PUSH_MESSAGE = ("During a workflow run the platform pushes the reviewed change (workflow_action_request scm.push); git "
                "push never runs here.")


def _host(argument: str) -> str:
    from urllib.parse import urlparse  # noqa: PLC0415

    candidate = argument if "://" in argument else f"https://{argument}"
    try:
        return (urlparse(candidate).hostname or "").lower()
    except ValueError:
        return ""


def _host_matches(argument: str, hosts: frozenset[str]) -> bool:
    host = _host(argument)
    return bool(host) and any(host == item or host.endswith("." + item) for item in hosts)


def bash_run_rules(command: str, *, hosts: frozenset[str] = DEFAULT_SCM_HOSTS) -> tuple[str, str] | None:
    if (why := hard_denied(command)) is not None:
        return REASON_HARD_DENY, f"This command never runs during a workflow run: {why}."
    for segment in command_segments(command) or []:
        name = posixpath.basename(segment[0]) if segment else ""
        if name in SCM_CLIENTS or (name in HTTP_CLIENTS and any(_host_matches(arg, hosts) for arg in segment[1:])):
            return REASON_SCM_CLIENT, SCM_MESSAGE
        if segment_matches(segment, ("git", "push")) or git_normalized(segment)[1:2] == ("send-pack",):
            return REASON_PUSH_BY_PLATFORM, PUSH_MESSAGE
    return None


# --- agent_gateway.self_protection ------------------------------------------------------------------------------------

PROTECTED_MARKERS = ("/api/v1/agent-gateway", "/api/v1/mcp/", "/api/v1/model-gateway", "/oauth/token",
                     "/oauth/authorize", ".octryx/claude", "OCTRYX_CLAUDE_HOME")
LAUNCHER_COMMANDS = frozenset({"octryx-claude", "octryx_claude_entry.py"})
LAUNCHER_MODULE = "octryx_claude"
OPEN_SUBCOMMANDS = frozenset({"l10n-merge"})  # no token, no state: a repository build step (self_protection)


def names_platform_credentials(command_or_path: str, state_root: str = "") -> bool:
    markers = (*PROTECTED_MARKERS, state_root) if state_root else PROTECTED_MARKERS
    return any(marker in command_or_path for marker in markers)


def runs_the_launcher(segments: list[Segment]) -> bool:
    for segment in segments:
        if not segment:
            continue
        if posixpath.basename(segment[0]) in LAUNCHER_COMMANDS:
            if not (len(segment) > 1 and segment[1] in OPEN_SUBCOMMANDS):
                return True
        elif LAUNCHER_MODULE in segment[1:3] or any(
                LAUNCHER_MODULE in posixpath.basename(token) for token in segment[1:3]):
            return True
    return False


__all__ = [
    "DEFAULT_SCM_HOSTS",
    "bash_run_rules",
    "hard_denied",
    "names_platform_credentials",
    "runs_the_launcher",
]
