"""git subcommands, global options and ``git config`` keys that would make git run a program."""

from __future__ import annotations

from collections.abc import Sequence

from .build_guard_rules import (
    _ALLOW,
    _GIT_CONFIG_WRITE_ONLY,
    _GIT_EXEC_KEY,
    _GIT_EXECUTING_GLOBALS,
    _GIT_SUBCOMMANDS,
    _UNJUDGEABLE_TARGET,
    CLASS_EXECUTING_OPTION,
    CLASS_GIT_COMMAND,
    ForeignBuildVerdict,
    _blocked,
)


def _git_config_verdict(args: Sequence[str]) -> ForeignBuildVerdict:
    """``git config``: reads run; a write of a key that makes git run a program, an edit or a rename never does."""
    if any(arg in _GIT_CONFIG_WRITE_ONLY for arg in args):
        return _blocked(CLASS_GIT_COMMAND, "git", "git config --edit/--rename-section changes git's configuration")
    words = [arg for arg in args if not arg.startswith("-")]
    options = [arg for arg in args if arg.startswith("-")]
    if words[:1] in (["get"], ["list"]) or (any(option.startswith(("--get", "--list")) or option == "-l"
                                                 for option in options) and words[:1] not in (["set"], ["unset"])):
        return _ALLOW
    if any(option.startswith(("--file", "-f", "--blob")) for option in options) and not words:
        return _ALLOW
    keys = words[1:2] if words[:1] in (["set"], ["unset"]) else words[:1]
    if not keys:
        return _ALLOW  # ``git config`` alone prints its usage
    key = keys[0]
    if _GIT_EXEC_KEY.match(key) or _UNJUDGEABLE_TARGET.search(key):
        return _blocked(CLASS_GIT_COMMAND, "git", f"git config {key[:60]} makes git run a program")
    if len(words) > 1 or words[:1] in (["set"], ["unset"]) or any(option in {"--add", "--replace-all", "--unset",
                                                                              "--unset-all"} for option in options):
        return _ALLOW  # another key (``user.name`` …) is plain data
    return _ALLOW  # ``git config <key>`` reads it


def _git_verdict(args: Sequence[str], depth: int) -> ForeignBuildVerdict:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        option = args[index]
        if option in {"-c", "--config"} and index + 1 < len(args) or option.startswith("--config="):
            value = args[index + 1] if not option.startswith("--config=") else option.split("=", 1)[1]
            if _GIT_EXEC_KEY.match(value.split("=", 1)[0].strip()):
                return _blocked(CLASS_EXECUTING_OPTION, "git", f"git -c {value[:60]} runs a program")
            index += 1 if option.startswith("--config=") else 2
            continue
        if option.startswith(_GIT_EXECUTING_GLOBALS) or option.startswith(("--git-dir", "--namespace",
                                                                            "--super-prefix", "--list-cmds")):
            return _blocked(CLASS_EXECUTING_OPTION, "git", f"git {option} points git elsewhere or runs a program")
        index += 2 if option in {"-C", "--work-tree"} else 1
    subcommand = args[index] if index < len(args) else ""
    rest = list(args[index + 1:])
    if not subcommand:
        return _ALLOW
    if subcommand not in _GIT_SUBCOMMANDS:
        return _blocked(CLASS_GIT_COMMAND, "git", f"git {subcommand[:40]} is not a known git command (an alias of the "
                                                  "working copy's configuration would run)")
    if subcommand == "config":
        return _git_config_verdict(rest)
    if subcommand in {"clone", "init", "submodule", "worktree"} and any(
            word.startswith(("--template", "--separate-git-dir")) for word in rest):
        return _blocked(CLASS_EXECUTING_OPTION, "git", f"git {subcommand} --template copies hooks and configuration")
    for position, word in enumerate(rest):
        if word in {"-c", "--config"} and position + 1 < len(rest) or word.startswith("--config="):
            value = rest[position + 1] if not word.startswith("--config=") else word.split("=", 1)[1]
            if _GIT_EXEC_KEY.match(value.split("=", 1)[0].strip()):
                return _blocked(CLASS_EXECUTING_OPTION, "git", f"git {subcommand} -c {value[:60]} runs a program")
    if subcommand == "rebase" and any(word in {"-x", "--exec"} or word.startswith("--exec=") for word in rest):
        return _blocked(CLASS_EXECUTING_OPTION, "git", "git rebase --exec runs a command")
    if subcommand == "grep" and any(word.startswith(("-O", "--open-files-in-pager")) for word in rest):
        return _blocked(CLASS_EXECUTING_OPTION, "git", "git grep -O runs a pager")
    if subcommand == "remote" and rest[:1] not in ([], ["-v"], ["--verbose"], ["show"], ["get-url"]):
        return _blocked(CLASS_GIT_COMMAND, "git", f"git remote {rest[0][:20]} changes the remotes")
    if any(word.startswith(("--upload-pack", "--receive-pack", "--exec=", "--ext-diff", "--exec-path"))
           or word in {"-u"} and subcommand in {"fetch", "pull", "clone", "ls-remote", "archive"} for word in rest):
        return _blocked(CLASS_EXECUTING_OPTION, "git", f"git {subcommand} option runs a program")
    return _ALLOW
