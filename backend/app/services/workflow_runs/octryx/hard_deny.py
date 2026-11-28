"""The short hard-deny list: credentials, environment dumps, uploads and writes outside the repository or app."""

from __future__ import annotations

import posixpath
import re

from app.services.agent_gateway.command_tokens import Segment, without_data_heredocs

from ...agent_gateway.command_match import command_segments

_CREDENTIAL_FILE = re.compile(
    r"(?:^|[\s/'\"=])(?:\.env(?:\.(?!example\b|sample\b|template\b|dist\b)[\w-]+)?|id_rsa|id_dsa|id_ecdsa|"
    r"id_ed25519|[\w.-]+\.pem|[\w.-]+\.p12|\.netrc|\.git-credentials|\.pypirc|\.npmrc|\.aws/credentials|"
    r"\.kube/config|\.docker/config\.json|\.ssh/[\w.-]+)(?=$|[\s'\"|;&)])")


# An environment dump (bare ``env``; ``printenv`` with or without a name): the segment parser drops ``env`` as a
# wrapper, so the text decides.
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


# A write to the app under test on loopback is allowed; a file sent anywhere stays refused, loopback included.
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
    # A heredoc body written into a file is data; a body a shell reads is still checked.
    text = without_data_heredocs(command or "")
    if _CREDENTIAL_FILE.search(text):
        return "it reads a credential file"
    if _ENVIRONMENT_DUMP.search(text):
        return "it reads credentials"
    for segment in command_segments(command) or []:
        if (why := _hard_segment(tuple(segment))) is not None:
            return why
    return None
