"""Shell expansion in a read-only command string: refused unless the text is provably literal."""

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
