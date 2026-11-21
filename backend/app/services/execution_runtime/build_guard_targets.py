"""Writes into git's internals, redirection targets and HTTP clients' destinations."""

from __future__ import annotations

import re
from collections.abc import Sequence

from .build_guard_rules import (
    _CURL_REFUSED_OPTIONS,
    _GIT_INTERNAL_PATH,
    _INTERNAL_HOST,
    _PATH_READERS,
    _PATH_WRITERS,
    _SECRET_PATH,
    _UNJUDGEABLE_TARGET,
    _WGET_REFUSED_OPTIONS,
    CLASS_CLOUD_CLI,
    CLASS_GIT_INTERNALS,
    CLASS_SECRET_READ,
    ForeignBuildVerdict,
    _blocked,
)


def _git_internals_write(name: str, args: Sequence[str]) -> ForeignBuildVerdict | None:
    """A write into ``.git/`` (hooks, config, info …) or to a target that cannot be judged; archive extraction."""
    if name in {"cd", "pushd"} and any(_GIT_INTERNAL_PATH.search(arg) or _UNJUDGEABLE_TARGET.search(arg)
                                       for arg in args):
        return _blocked(CLASS_GIT_INTERNALS, name, "changes into git's internals or a directory it cannot judge")
    if name not in _PATH_READERS and (target := next((arg for arg in args if _GIT_INTERNAL_PATH.search(arg)),
                                                     None)) is not None:
        return _blocked(CLASS_GIT_INTERNALS, name, f"{name} touches git's internals ({target[:80]})")
    if name in _PATH_WRITERS and (target := next((arg for arg in args if not arg.startswith("-")
                                                  and _UNJUDGEABLE_TARGET.search(arg)), None)) is not None:
        return _blocked(CLASS_GIT_INTERNALS, name, f"{name} writes a target that cannot be judged ({target[:80]})")
    if name == "sed" and any(arg == "-i" or arg.startswith(("-i", "--in-place")) for arg in args):
        files = [arg for arg in args if not arg.startswith("-")]
        files = files if any(arg in {"-e", "--expression"} or arg.startswith("--expression=") for arg in args) \
            else files[1:]
        if any(_UNJUDGEABLE_TARGET.search(arg) for arg in files):
            return _blocked(CLASS_GIT_INTERNALS, name, "sed -i writes a target that cannot be judged")
    if name == "tar" and args and (re.match(r"^-?[A-Za-z]*x", args[0]) or any(
            arg in {"--extract", "--get"} or re.match(r"^-[A-Za-z]*x", arg) for arg in args)):
        return _blocked(CLASS_GIT_INTERNALS, name, "extracting an archive writes paths the command does not name")
    if name == "unzip" and not any(arg in {"-l", "-t", "-v", "-Z", "-p"} for arg in args):
        return _blocked(CLASS_GIT_INTERNALS, name, "extracting an archive writes paths the command does not name")
    return None


def _targets_verdict(output_targets: Sequence[str], input_targets: Sequence[str]) -> ForeignBuildVerdict | None:
    for target in output_targets:
        if _GIT_INTERNAL_PATH.search(target) or _UNJUDGEABLE_TARGET.search(target):
            return _blocked(CLASS_GIT_INTERNALS, ">", f"redirects into git's internals or an unjudgeable target "
                                                        f"({target[:80]})")
        if _SECRET_PATH.search(target):
            return _blocked(CLASS_SECRET_READ, ">", f"redirects into a secret path ({target[:80]})")
    for target in input_targets:
        if _SECRET_PATH.search(target):
            return _blocked(CLASS_SECRET_READ, "<", f"reads the process environment or a mounted secret "
                                                     f"({target[:80]})")
    return None


def _http_verdict(name: str, args: Sequence[str]) -> ForeignBuildVerdict | None:
    """``curl``/``wget`` only to a public host: no metadata, cluster, private or loopback address, no ``file:``."""
    refused_options = _CURL_REFUSED_OPTIONS if name == "curl" else _WGET_REFUSED_OPTIONS
    for index, arg in enumerate(args):
        if arg in refused_options or arg.startswith(tuple(f"{option}=" for option in refused_options if
                                                          option.startswith("--"))):
            return _blocked(CLASS_CLOUD_CLI, name, f"{name} {arg} redirects or scripts the request")
        if "$" in arg or "`" in arg:
            return _blocked(CLASS_CLOUD_CLI, name, f"{name} target is expanded at run time ({arg[:80]})")
        lowered = arg.lower()
        if lowered.startswith(("file:", "dict:", "gopher:", "ldap:", "telnet:", "tftp:", "scp:", "sftp:")):
            return _blocked(CLASS_SECRET_READ, name, f"{name} {lowered.split(':', 1)[0]}: reads or reaches the pod")
        host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", lowered).split("/", 1)[0].rsplit("@", 1)[-1]
        if host.startswith("["):
            host = host.split("]", 1)[0] + "]"
        elif host.count(":") == 1:
            host = host.split(":", 1)[0]
        if host and (index == 0 or not args[index - 1].startswith("-") or "://" in lowered) and \
                _INTERNAL_HOST.match(host):
            return _blocked(CLASS_CLOUD_CLI, name, f"{name} reaches an internal address ({host[:80]})")
    return None
