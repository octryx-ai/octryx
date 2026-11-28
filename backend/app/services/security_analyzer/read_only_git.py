"""The git read forms a read-only path admits, as CLOSED per-subcommand option tables."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from .read_only_options import FLAG, OPTIONAL, VALUE, OptionTable, _parse

GIT_READ_REFUSED = "git_read_form"


def _flags(names: Iterable[str]) -> dict[str, int]:
    return dict.fromkeys(names, FLAG)


# Git's own argument semantics. Options git defines with an OPTIONAL argument (``[=<n>]``:
# ``-U[<n>]``/``--unified[=<n>]``, ``-M[<n>]``/``--find-renames[=<n>]``, ``--stat[=…]``, ``--abbrev[=<n>]``,
# ``--color[=<when>]``, ``--word-diff[=<mode>]``, ``--relative[=<path>]``, ``--decorate[=…]``, ``--pretty[=…]``) take
# their value only attached; the next word is parsed on its own (``git diff -U --output=out`` writes a file, so
# ``--output`` must be seen). ``--format``/``--date`` are modelled attached-only too (no separate word is consumed).
# Required-argument options (``-n``, ``--author``, ``--diff-filter`` …) take a separate word, but never one that looks
# like an option (``option_like_values=False``). ``-C``/``-B`` (copies/rewrites) are not in the table: refused.
_PATCH_SHAPE_LONG = {
    **_flags(["numstat", "shortstat", "name-only", "name-status", "patch", "no-patch", "no-color",
              "minimal", "summary", "ignore-all-space", "ignore-space-change", "no-ext-diff", "no-textconv",
              "no-renames", "full-index"]),
    **dict.fromkeys(["stat", "abbrev", "color", "word-diff", "find-renames", "unified", "relative"], OPTIONAL),
    "diff-filter": VALUE, "stat-width": VALUE,
}
_PATCH_SHAPE_SHORT = {**_flags("pwbRs"), "U": OPTIONAL, "M": OPTIONAL}

_STATUS = OptionTable(
    option_like_values=False,
    short=_flags("sbv"),
    long={**_flags(["short", "branch", "long", "verbose", "show-stash", "ahead-behind", "no-ahead-behind",
                    "renames", "no-renames"]),
          "porcelain": OPTIONAL, "untracked-files": OPTIONAL, "ignored": OPTIONAL},
)
_DIFF = OptionTable(
    option_like_values=False,
    short=_PATCH_SHAPE_SHORT,
    long={**_PATCH_SHAPE_LONG, **_flags(["cached", "staged", "merge-base", "quiet", "exit-code", "name-only"])},
)
_LOG = OptionTable(
    option_like_values=False,
    short={**_PATCH_SHAPE_SHORT, "n": VALUE, "S": VALUE, "G": VALUE, "i": FLAG},
    long={**_PATCH_SHAPE_LONG,
          **_flags(["oneline", "graph", "all", "reverse", "no-merges", "merges", "first-parent", "abbrev-commit",
                    "follow", "regexp-ignore-case", "all-match", "left-right", "cherry-pick", "date-order",
                    "topo-order", "no-walk", "branches", "tags", "remotes", "source", "boundary", "no-decorate"]),
          **dict.fromkeys(["max-count", "skip", "since", "until", "after", "before", "author", "committer",
                           "grep"], VALUE),
          **dict.fromkeys(["format", "date", "pretty", "decorate"], OPTIONAL)},
    numeric_short=True,
)
_SHOW = OptionTable(
    option_like_values=False,
    short={**_PATCH_SHAPE_SHORT, "q": FLAG},
    long={**_PATCH_SHAPE_LONG, **_flags(["oneline", "abbrev-commit", "quiet", "no-decorate"]),
          **dict.fromkeys(["format", "date", "pretty", "decorate"], OPTIONAL)},
)
_REV_PARSE = OptionTable(
    option_like_values=False,
    short=_flags("q"),
    long={**_flags(["verify", "quiet", "show-toplevel", "git-dir", "git-common-dir", "absolute-git-dir",
                    "is-inside-work-tree", "is-inside-git-dir", "is-bare-repository", "symbolic-full-name",
                    "show-prefix", "show-cdup", "symbolic"]),
          "abbrev-ref": OPTIONAL, "short": OPTIONAL},
)
_BRANCH = OptionTable(
    option_like_values=False,
    short=_flags("larv"),
    long={**_flags(["list", "all", "remotes", "verbose", "show-current", "no-color"]),
          **dict.fromkeys(["contains", "no-contains", "merged", "no-merged"], OPTIONAL),
          **dict.fromkeys(["points-at", "sort", "format"], VALUE), "color": OPTIONAL},
)


def _table(table: OptionTable) -> Callable[[Sequence[str]], bool]:
    return lambda args: _parse(table, args) is not None


def _branch(args: Sequence[str]) -> bool:
    parsed = _parse(_BRANCH, args)
    if parsed is None:
        return False
    listing = any(name in ("--list", "-l") for name, _value in parsed.options)
    return listing or not parsed.operands


def _remote(args: Sequence[str]) -> bool:
    if all(arg in ("-v", "--verbose") for arg in args):
        return True
    verb, rest = args[0], list(args[1:])
    if verb == "show":
        names = [arg for arg in rest if arg != "-n"]
        return len(names) >= 1 and not any(name.startswith("-") for name in names)
    if verb == "get-url":
        names = [arg for arg in rest if arg not in ("--push", "--all")]
        return len(names) == 1 and not names[0].startswith("-")
    return False


_SUBCOMMANDS: dict[str, Callable[[Sequence[str]], bool]] = {
    "branch": _branch,
    "diff": _table(_DIFF),
    "log": _table(_LOG),
    "remote": _remote,
    "rev-parse": _table(_REV_PARSE),
    "show": _table(_SHOW),
    "status": _table(_STATUS),
}
BOUND_GIT_SUBCOMMANDS: frozenset[str] = frozenset(_SUBCOMMANDS)


def _split_globals(args: Sequence[str]) -> tuple[str, list[str]] | None:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        if args[index] == "--no-pager":
            index += 1
        elif args[index] == "-C" and index + 1 < len(args):
            index += 2
        else:
            return None
    if index >= len(args):
        return None
    return args[index], list(args[index + 1 :])


def git_read_refusal(args: Sequence[str], admitted: Iterable[str]) -> str | None:
    split = _split_globals([str(arg) for arg in args])
    if split is None:
        return GIT_READ_REFUSED
    subcommand, rest = split
    check = _SUBCOMMANDS.get(subcommand)
    if check is None or subcommand not in set(admitted) or not check(rest):
        return GIT_READ_REFUSED
    return None


__all__ = ["BOUND_GIT_SUBCOMMANDS", "GIT_READ_REFUSED", "git_read_refusal"]
