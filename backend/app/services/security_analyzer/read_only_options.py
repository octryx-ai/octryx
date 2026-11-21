"""The read commands a read-only path admits, as a CLOSED allowlist of their reading options.

A read command is admitted by name (``exec_policy`` ``diagnosis_read_only_commands``), but several of
them can also write a file, run a program or change state through an option (``sort -o``, ``sort
--compress-program``, ``uniq IN OUT``, ``find -delete``, ``rg --pre``, ``date -s``, ``sed 'w f'``). So
every admitted command is parsed against its own table, the way getopt/getopt_long would, and only
reading options pass:

- short options: each character of a cluster must be in the table; a value-taking character takes the
  rest of the word or the next word;
- long options: the EXACT name must be in the table. GNU getopt_long also accepts any unambiguous
  prefix (``--out`` for ``--output``); a prefix is never an exact entry, so it is refused, whatever
  option it would abbreviate;
- ``--`` ends the options: every later word is an operand, also one that starts with ``-``;
- an option outside the table, a missing value, a value given to a flag that takes none, or an operand
  the command would treat as an output or a setting is refused (fail closed).

Commands with their own grammar are checked by it: ``find`` (a closed set of tests, operators and
printing actions), ``sed`` (print-style scripts only), ``date`` (``+FORMAT`` is the only operand). An
admitted command without a table here is refused by the command rules on read-only paths
(:data:`BOUND_READ_COMMANDS`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

READ_OPTION_REFUSED = "read_command_option"

# Arity: 0 = flag, 1 = takes a value (next word or ``=value``), 2 = optional value: a long option's only via
# ``=value``, a short option's only ATTACHED (``-U3``) — a separate following word is never its value.
FLAG, VALUE, OPTIONAL = 0, 1, 2


@dataclass(frozen=True)
class OptionTable:
    short: dict[str, int] = field(default_factory=dict)
    long: dict[str, int] = field(default_factory=dict)
    numeric_short: bool = False  # ``head -5``
    max_operands: int | None = None
    operand_ok: Callable[[str], bool] | None = None
    # ``False``: a value given as a separate word must not look like an option (``--author --output=x``): refused,
    # so a following option is never hidden as a value (git's tables; fail closed).
    option_like_values: bool = True


@dataclass
class _Parsed:
    options: list[tuple[str, str | None]] = field(default_factory=list)
    operands: list[str] = field(default_factory=list)


def _parse(table: OptionTable, args: Sequence[str]) -> _Parsed | None:
    """The words split like getopt_long with ``table`` (permuting, ``--`` terminates); ``None`` refuses."""
    parsed = _Parsed()
    index = 0
    ended = False
    while index < len(args):
        word = args[index]
        if ended or word == "-" or not word.startswith("-"):
            parsed.operands.append(word)
            index += 1
            continue
        if word == "--":
            ended = True
            index += 1
            continue
        if word.startswith("--"):
            name, has_value, value = word[2:].partition("=")
            arity = table.long.get(name)
            if arity is None or (arity == FLAG and has_value):
                return None
            if arity == VALUE and not has_value:
                if index + 1 >= len(args) or (not table.option_like_values and args[index + 1].startswith("-")):
                    return None
                index += 1
                value = args[index]
            parsed.options.append((f"--{name}", value if (has_value or arity == VALUE) else None))
            index += 1
            continue
        if table.numeric_short and re.fullmatch(r"-\d+", word):
            index += 1
            continue
        cluster = word[1:]
        position = 0
        while position < len(cluster):
            arity = table.short.get(cluster[position])
            if arity is None:
                return None
            rest = cluster[position + 1 :]
            if arity == OPTIONAL:  # the rest of the cluster is its value; the next word never is
                parsed.options.append((f"-{cluster[position]}", rest or None))
                break
            if arity == VALUE:
                if not rest:
                    if index + 1 >= len(args) or (not table.option_like_values and args[index + 1].startswith("-")):
                        return None
                    index += 1
                    rest = args[index]
                parsed.options.append((f"-{cluster[position]}", rest))
                break
            parsed.options.append((f"-{cluster[position]}", None))
            position += 1
        index += 1
    if table.max_operands is not None and len(parsed.operands) > table.max_operands:
        return None
    if table.operand_ok is not None and not all(table.operand_ok(operand) for operand in parsed.operands):
        return None
    return parsed


_CAT = OptionTable(
    short=dict.fromkeys("AbeEnstTuv", FLAG),
    long=dict.fromkeys(["show-all", "number-nonblank", "show-ends", "number", "squeeze-blank", "show-tabs",
                        "show-nonprinting"], FLAG),
)
_HEAD = OptionTable(
    short={"c": VALUE, "n": VALUE, "q": FLAG, "v": FLAG, "z": FLAG},
    long={"bytes": VALUE, "lines": VALUE, "quiet": FLAG, "silent": FLAG, "verbose": FLAG, "zero-terminated": FLAG},
    numeric_short=True,
)
_TAIL = OptionTable(
    short={"c": VALUE, "n": VALUE, "f": FLAG, "F": FLAG, "q": FLAG, "v": FLAG, "z": FLAG, "s": VALUE},
    long={"bytes": VALUE, "lines": VALUE, "follow": OPTIONAL, "retry": FLAG, "quiet": FLAG, "silent": FLAG,
          "verbose": FLAG, "zero-terminated": FLAG, "sleep-interval": VALUE, "pid": VALUE},
    numeric_short=True,
)
_WC = OptionTable(
    short=dict.fromkeys("cmlLw", FLAG),
    long={"bytes": FLAG, "chars": FLAG, "lines": FLAG, "max-line-length": FLAG, "words": FLAG, "total": VALUE},
)
_LS = OptionTable(
    short={**dict.fromkeys("aAbBcCdfFgGhHiklLmnNopqQrRsStuUvxXZ1", FLAG), "w": VALUE, "I": VALUE, "T": VALUE},
    long={**dict.fromkeys(["all", "almost-all", "author", "escape", "directory", "classify", "no-group",
                           "human-readable", "si", "dereference", "dereference-command-line", "inode",
                           "literal", "numeric-uid-gid", "hide-control-chars", "show-control-chars",
                           "quote-name", "reverse", "recursive", "size", "full-time", "group-directories-first",
                           "zero", "context"], FLAG),
          **dict.fromkeys(["color", "hyperlink", "indicator-style"], OPTIONAL),
          **dict.fromkeys(["block-size", "format", "hide", "ignore", "quoting-style", "sort", "time",
                           "time-style", "tabsize", "width"], VALUE)},
)
_SORT = OptionTable(
    short={**dict.fromkeys("bdfgiMhnRrVcCsumz", FLAG), "k": VALUE, "t": VALUE, "S": VALUE},
    long={**dict.fromkeys(["ignore-leading-blanks", "dictionary-order", "ignore-case", "general-numeric-sort",
                           "ignore-nonprinting", "month-sort", "human-numeric-sort", "numeric-sort", "random-sort",
                           "reverse", "version-sort", "merge", "stable", "unique", "zero-terminated", "debug"],
                          FLAG),
          "check": OPTIONAL, "key": VALUE, "field-separator": VALUE, "buffer-size": VALUE, "parallel": VALUE,
          "sort": VALUE},
)
_UNIQ = OptionTable(
    short={**dict.fromkeys("cdDiuz", FLAG), "f": VALUE, "s": VALUE, "w": VALUE},
    long={**dict.fromkeys(["count", "repeated", "unique", "ignore-case", "zero-terminated"], FLAG),
          "all-repeated": OPTIONAL, "group": OPTIONAL,
          "skip-fields": VALUE, "skip-chars": VALUE, "check-chars": VALUE},
    max_operands=1,  # a second operand is the OUTPUT file
)
_RG = OptionTable(
    short={**dict.fromkeys("iSsnNlcwxvFHIoLUPa0qu", FLAG),
           **dict.fromkeys("eEgtTABCmMjdr", VALUE)},
    long={**dict.fromkeys(["ignore-case", "smart-case", "case-sensitive", "line-number", "no-line-number",
                           "files-with-matches", "files-without-match", "count", "count-matches", "word-regexp",
                           "line-regexp", "invert-match", "fixed-strings", "only-matching", "with-filename",
                           "no-filename", "hidden", "no-ignore", "no-ignore-vcs", "follow", "multiline",
                           "multiline-dotall", "pcre2", "text", "files", "json", "vimgrep", "trim", "stats",
                           "heading", "no-heading", "column", "no-messages", "quiet", "null", "byte-offset",
                           "type-list", "unrestricted", "passthru", "sort-files", "binary", "crlf"], FLAG),
          **dict.fromkeys(["regexp", "glob", "iglob", "type", "type-not", "after-context", "before-context",
                           "context", "max-count", "max-depth", "max-columns", "max-filesize", "sort", "sortr",
                           "replace", "threads", "color", "colors", "encoding", "engine", "path-separator",
                           "field-match-separator", "field-context-separator", "context-separator"], VALUE)},
)
_ID = OptionTable(
    short=dict.fromkeys("ugGnrza", FLAG),
    long=dict.fromkeys(["user", "group", "groups", "name", "real", "zero"], FLAG),
    max_operands=1,
)
_PRINTENV = OptionTable(short={"0": FLAG}, long={"null": FLAG})
_PWD = OptionTable(short=dict.fromkeys("LP", FLAG), long=dict.fromkeys(["logical", "physical"], FLAG),
                   max_operands=0)
_WHOAMI = OptionTable(max_operands=0)
_DATE = OptionTable(
    short={"u": FLAG, "R": FLAG, "d": VALUE},
    long={"utc": FLAG, "universal": FLAG, "rfc-email": FLAG, "date": VALUE, "rfc-3339": VALUE,
          "iso-8601": OPTIONAL},
    max_operands=1,
    operand_ok=lambda operand: operand.startswith("+"),  # any other operand SETS the clock
)

# find: starting points, then an expression from a closed set (no -exec*/-ok*/-delete/-fprint*/-fls/-newerXY).
_FIND_LEADING = frozenset({"-H", "-L", "-P"})
_FIND_VALUE = frozenset({
    "-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-regex", "-iregex", "-lname", "-ilname",
    "-type", "-xtype", "-size", "-mtime", "-mmin", "-atime", "-amin", "-ctime", "-cmin", "-newer", "-anewer",
    "-cnewer", "-user", "-group", "-uid", "-gid", "-perm", "-links", "-inum", "-samefile", "-maxdepth",
    "-mindepth", "-regextype", "-printf", "-used", "-fstype",
})
_FIND_FLAG = frozenset({
    "-empty", "-readable", "-writable", "-executable", "-nouser", "-nogroup", "-true", "-false", "-depth",
    "-follow", "-xdev", "-mount", "-noleaf", "-daystart", "-ignore_readdir_race", "-noignore_readdir_race",
    "-print", "-print0", "-ls", "-prune", "-quit", "!", "-not", "-a", "-and", "-o", "-or", "(", ")", ",",
})


def _find(args: Sequence[str]) -> bool:
    index = 0
    while index < len(args) and args[index] in _FIND_LEADING:
        index += 1
    while index < len(args) and not args[index].startswith("-") and args[index] not in ("!", "(", ")", ","):
        index += 1  # starting points
    while index < len(args):
        word = args[index]
        if word in _FIND_VALUE:
            if index + 1 >= len(args):
                return False
            index += 2
        elif word in _FIND_FLAG:
            index += 1
        else:
            return False
    return True


# sed: only print-style scripts, inline or with -e/--expression; options from a closed set.
_SED_SHORT = {**dict.fromkeys("nErsuz", FLAG), "e": VALUE}
_SED_LONG = {**dict.fromkeys(["quiet", "silent", "regexp-extended", "separate", "unbuffered", "null-data",
                              "posix", "debug", "sandbox"], FLAG), "expression": VALUE}
_ADDRESS = r"(?:\d+|\$|/(?:[^/\\]|\\.)*/)"
_SED_SCRIPT = re.compile(
    rf"^\s*(?:{_ADDRESS}(?:\s*,\s*{_ADDRESS})?\s*)?(?:[p=]|s/(?:[^/\\\n]|\\.)*/(?:[^/\\\n]|\\.)*/[gpiI0-9]*)\s*$"
)


def _sed(args: Sequence[str]) -> bool:
    parsed = _parse(OptionTable(short=_SED_SHORT, long=_SED_LONG), args)
    if parsed is None:
        return False
    scripts = [value or "" for name, value in parsed.options if name in ("-e", "--expression")]
    operands = list(parsed.operands)
    if not scripts:
        if not operands:
            return False
        scripts.append(operands.pop(0))
    if any(operand.startswith("-") and operand != "-" for operand in operands):
        return False  # a file named like an option: refuse rather than guess what sed reads
    return all(_SED_SCRIPT.match(command) for script in scripts for command in _sed_commands(script))


def _sed_commands(script: str) -> list[str]:
    """The commands of one sed script, split where sed itself splits them (``;`` and new lines); each must be a
    print-style command on its own, so a split inside a regex or a replacement only ever refuses (fail closed).

    Refusing ``sed -n '44,66p;217,251p' SPEC.md`` makes the model read a whole long specification instead (many
    thousand tokens, in every session and again after each compaction)."""
    commands = [command for command in re.split(r"[;\n]", script) if command.strip()]
    return commands or [script]


def _table_check(table: OptionTable) -> Callable[[Sequence[str]], bool]:
    return lambda args: _parse(table, args) is not None


_BINDINGS: dict[str, Callable[[Sequence[str]], bool]] = {
    "cat": _table_check(_CAT),
    # ``cd`` only changes the shell's folder (each further command is judged by itself); ``grep`` has no option that
    # writes or runs anything, so ``cd <repo>; git status`` and ``grep -c`` must not be
    # refused.
    "cd": lambda args: len(args) <= 1,
    "grep": lambda args: True,
    "date": _table_check(_DATE),
    "echo": lambda args: True,  # echo prints its words; redirects are checked before this rule
    "env": lambda args: not args,  # bare ``env`` prints the environment; anything else runs a program
    "find": _find,
    "head": _table_check(_HEAD),
    "id": _table_check(_ID),
    "ls": _table_check(_LS),
    "printenv": _table_check(_PRINTENV),
    "pwd": _table_check(_PWD),
    "rg": _table_check(_RG),
    "sed": _sed,
    "sort": _table_check(_SORT),
    "tail": _table_check(_TAIL),
    "uniq": _table_check(_UNIQ),
    "wc": _table_check(_WC),
    "whoami": _table_check(_WHOAMI),
}
BOUND_READ_COMMANDS: frozenset[str] = frozenset(_BINDINGS)


def read_option_refusal(segment: Sequence[str]) -> str | None:
    """``READ_OPTION_REFUSED`` when a bound read command uses anything outside its reading options."""
    if not segment:
        return None
    check = _BINDINGS.get(str(segment[0]))
    if check is not None and not check([str(token) for token in segment[1:]]):
        return READ_OPTION_REFUSED
    return None


__all__ = ["BOUND_READ_COMMANDS", "READ_OPTION_REFUSED", "read_option_refusal"]
