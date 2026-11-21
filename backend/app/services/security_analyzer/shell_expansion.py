"""Shell expansion in a read-only command string: refused unless the text is provably literal.

The read-only rules judge the words of a command. bash, however, expands the ORIGINAL text before it
runs anything: ``uniq glob-*`` can become ``uniq in out``, ``sort $FLAGS in`` can become ``sort -o
out in``, and ``$'\\x2ddelete'`` is ``-delete``. A check on tokenized (``shlex``) or re-quoted words
cannot see that. So the original string is scanned once with bash's quoting rules, before any
tokenization, normalization or re-quoting, and any expansion that is not inside single quotes fails
closed:

- ``$`` in any form (parameter ``$X``/``${X}``, command ``$(…)``, arithmetic ``$((…))``, ANSI-C
  ``$'…'``, localized ``$"…"``) and backticks, also inside double quotes;
- unquoted pathname expansion characters ``*``, ``?``, ``[`` and brace expansion ``{``;
- unquoted ``~`` (tilde expansion) and ``!`` (history expansion, also inside double quotes);
- an unquoted ``#`` at the start of a word (a comment drops the rest of the line);
- unquoted process substitution ``<(…)`` and ``>(…)`` (it runs a command); zsh's ``=(…)`` falls under
  the next rule;
- zsh forms: an unquoted ``=`` at the start of a word (``=cmd``, ``=(…)``) and any unquoted ``^``;
- a backslash inside double quotes (bash and the tokenizer disagree on what it escapes);
- an unterminated quote.

Single-quoted text is literal (``find . -name '*.py'``, ``sed -n '$p'``); an unquoted backslash makes
the next character literal (``\\*.py``). Field splitting only happens on expansion results, so it is
covered by the ``$`` rule. This is a check that the judged words are the words bash runs. It is not a
shell sandbox.

Shells: the rules are bash's (verified against GNU bash 3.2.57, macOS ``/bin/bash`` and ``/bin/sh``), a
superset of POSIX ``sh``/dash (the platform runs commands with ``/bin/sh -c`` on the host and ``/bin/sh -lc``
in the default ``python:3.11-slim`` runtime, i.e. dash); for zsh (an external client's shell) its extra
``=cmd`` and ``^`` forms are refused too. Other shells (fish, csh, PowerShell) are not covered.
"""

from __future__ import annotations

EXPANSION_PARAMETER = "parameter_or_command_expansion"
EXPANSION_GLOB = "pathname_expansion"
EXPANSION_BRACE = "brace_expansion"
EXPANSION_TILDE = "tilde_expansion"
EXPANSION_HISTORY = "history_expansion"
EXPANSION_COMMENT = "comment"
EXPANSION_ESCAPE = "escape_in_double_quotes"
EXPANSION_UNTERMINATED = "unterminated_quote"
EXPANSION_ZSH = "zsh_expansion"
EXPANSION_PROCESS = "process_substitution"

SHELL_EXPANSION_REASONS: frozenset[str] = frozenset({
    EXPANSION_PARAMETER, EXPANSION_GLOB, EXPANSION_BRACE, EXPANSION_TILDE, EXPANSION_HISTORY, EXPANSION_COMMENT,
    EXPANSION_ESCAPE, EXPANSION_UNTERMINATED, EXPANSION_ZSH, EXPANSION_PROCESS,
})

_WORD_BREAKS = frozenset(" \t\n;&|()<>")


def shell_expansion_refusal(command: str) -> str | None:
    """Why bash would expand ``command`` into other words than the literal ones (``None``: it would not)."""
    text = str(command or "")
    index = 0
    word_start = True
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2  # the next character is literal
            word_start = False
            continue
        if char == "'":
            end = text.find("'", index + 1)
            if end < 0:
                return EXPANSION_UNTERMINATED
            index = end + 1
            word_start = False
            continue
        if char == '"':
            index += 1
            while index < len(text) and text[index] != '"':
                inner = text[index]
                if inner in "$`":
                    return EXPANSION_PARAMETER
                if inner == "!":
                    return EXPANSION_HISTORY
                if inner == "\\":
                    return EXPANSION_ESCAPE
                index += 1
            if index >= len(text):
                return EXPANSION_UNTERMINATED
            index += 1
            word_start = False
            continue
        if char in "$`":
            return EXPANSION_PARAMETER
        if char in "*?[":
            return EXPANSION_GLOB
        if char in "<>" and text[index + 1 : index + 2] == "(":
            return EXPANSION_PROCESS  # ``<(cmd)`` / ``>(cmd)`` run a command and pass its pipe as a word
        if char == "{":
            return EXPANSION_BRACE
        if char == "~":
            return EXPANSION_TILDE
        if char == "!":
            return EXPANSION_HISTORY
        if char == "#" and word_start:
            return EXPANSION_COMMENT
        if char == "=" and word_start:
            return EXPANSION_ZSH  # zsh ``=cmd`` expands to the command's path
        if char == "^":
            return EXPANSION_ZSH  # zsh extended-glob negation / csh-style history substitution
        word_start = char in _WORD_BREAKS
        index += 1
    return None


__all__ = ["SHELL_EXPANSION_REASONS", "shell_expansion_refusal"]
