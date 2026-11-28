"""Shell tokenizing shared by the gateway's command matchers. Heredoc bodies are data: ``without_data_heredocs`` drops
the bodies a shell does not read as commands."""

from __future__ import annotations

import posixpath
import re
import shlex

MAX_COMMAND_CHARS = 64_000
MAX_SEGMENTS = 400
MAX_NESTING = 3

_PUNCTUATION = ";&|()<>\n`"
_SEPARATOR_CHARS = frozenset("();|\n`")
_REDIRECT_CHARS = frozenset("<>")
_SHELLS = frozenset({"sh", "bash", "zsh", "dash"})
_WRAPPERS = frozenset({"env", "sudo", "command", "exec", "nohup", "time"})
# Syntax, not intent: the delimiter word of a heredoc operator (``<<EOF``, ``<<-'EOF'``).
_HEREDOC = re.compile(r"(?<!<)<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

Segment = tuple[str, ...]


def _tokenize(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _strip_heredoc_bodies(command: str, *, keep_shell_input: bool = False) -> str:
    lines = command.split("\n")
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        if keep_shell_input and _feeds_a_shell(line):
            continue  # ``bash <<EOF`` / ``cat <<EOF | sh``: the body is commands, parsed as such
        for match in _HEREDOC.finditer(line):
            delimiter = match.group(2)
            end = next((i for i in range(index, len(lines)) if lines[i].strip() == delimiter), None)
            if end is not None:
                index = end + 1
    return "\n".join(kept)


_SHELL_INPUT_WORDS = _SHELLS | {"eval", "source", ".", "xargs"}


def _feeds_a_shell(line: str) -> bool:
    # Conservative: a heredoc body a shell reads is parsed like any other command.
    return any(posixpath.basename(word.strip("'\"()")) in _SHELL_INPUT_WORDS
               for word in re.split(r"[\s;&|]+", line) if word)


def without_data_heredocs(command: str) -> str:
    # Parsed as shell, a data body is refused: ``shutdown`` in a written file reads as a destructive command.
    return _strip_heredoc_bodies(str(command or ""), keep_shell_input=True)


def _is_operator(token: str) -> bool:
    return bool(token) and all(char in _PUNCTUATION for char in token)


def _is_env_assignment(token: str) -> bool:
    name, sep, _ = token.partition("=")
    return (
        bool(sep)
        and bool(name)
        and (name[0].isalpha() or name[0] == "_")
        and all(char.isalnum() or char == "_" for char in name)
    )
