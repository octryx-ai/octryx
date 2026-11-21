"""Calls outside the diff that a pull request breaks: deterministic, without a model.

After the checkout (``actions.prepare``) the bot compares the changed Python files' public signatures between the
merge base and the head (``signatures``) and finds their calls in the checked-out head:

- candidates by ``git grep -w`` over the ``*.py`` files (the code graph's callers take this place once a repository
  is indexed with a graph; today the graph has no caller query);
- a call counts only where the name is bound to the changed module: the module itself, ``from <module> import name``
  (absolute or relative, with ``as``), or ``import <module> [as m]`` then ``m.name(...)``; a method ``Class.method``
  only where ``Class`` is bound that way and the method name is defined once in the repository;
- each call is checked against the new signature (``signatures.call_problem``); a call that no longer fits, or of a
  removed callable, is a deterministic **high** finding on the caller's file and line. Calls that still fit go to the
  reviewer as context (``review_context_sections``), so it can judge behaviour, not only arity.

Changed source files in other languages are named as not checked, never silently passed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..workflow_runs import safe_git
from .signatures import Change, call_problem, changed_signatures

OTHER_SOURCES = (".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".go", ".rb", ".cs", ".php", ".rs", ".swift",
                 ".scala", ".c", ".cc", ".cpp", ".h", ".hpp")


@dataclass(slots=True)
class CallerCheck:
    findings: list[dict[str, Any]] = field(default_factory=list)
    fitting: list[str] = field(default_factory=list)  # "path:line: source" of calls that still fit
    changes: list[str] = field(default_factory=list)  # "path: name(old) -> (new)"
    not_checked: list[str] = field(default_factory=list)  # extensions of changed files in other languages

    def context(self) -> str:
        lines = ["Signatures this change alters:", *self.changes]
        if self.findings:
            # Without these the reviewer can write "behaviour is unchanged" over
            # the deterministic finding. They are facts, already high findings: the summary must not contradict them.
            lines += ["", "Calls outside the diff this change breaks (a deterministic check, already high findings; "
                      "your summary must not say the behaviour is unchanged):",
                      *(f"{item['file']}:{item['line']}: {item['fix']}" for item in self.findings)]
        if self.fitting:
            lines += ["", "Calls outside the diff that still fit the new signature (judge their behaviour):",
                      *self.fitting]
        return "\n".join(lines)


def module_of(path: str) -> str:
    parts = Path(path).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _resolved(node: ast.ImportFrom, path: str) -> str:
    """The absolute module an ``ImportFrom`` names (relative imports against ``path``'s package)."""
    if not node.level:
        return node.module or ""
    package = Path(path).parent.parts
    base = package[:len(package) - (node.level - 1)] if node.level > 1 else package
    return ".".join([*base, *([node.module] if node.module else [])])


def _bindings(tree: ast.Module, path: str, module: str, top: str) -> tuple[set[str], set[str]]:
    """``(names, module aliases)`` under which ``module.top`` is reachable in a file."""
    names, aliases = ({top} if module_of(path) == module else set()), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            source = _resolved(node, path)
            for alias in node.names:
                if source == module and alias.name == top:
                    names.add(alias.asname or alias.name)
                elif f"{source}.{alias.name}" == module:
                    aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module:
                    aliases.add(alias.asname or alias.name)
    return names, aliases


def _calls(tree: ast.Module, change: Change, names: set[str], aliases: set[str], unique_method: bool):
    top, _, method = change.name.partition(".")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if method:
            if (unique_method and isinstance(func, ast.Attribute) and func.attr == method and (names or aliases)):
                yield node
        elif isinstance(func, ast.Name) and func.id in names:
            yield node
        elif isinstance(func, ast.Attribute) and func.attr == top and isinstance(func.value, ast.Name) \
                and func.value.id in aliases:
            yield node


async def _grep(root: str, word: str) -> list[str]:
    code, out, _err = await safe_git.git(root, "grep", "-l", "-w", "-I", "-e", word, "--", "*.py")
    return [line.strip() for line in out.splitlines() if line.strip()] if code == 0 else []


async def _definitions(root: str, method: str) -> int:
    """How often the head defines ``method`` (``git grep`` exits 1 when there is none: 0)."""
    code, out, _err = await safe_git.git(root, "grep", "-c", "-w", "-e", f"def {method}", "--", "*.py")
    return sum(int(line.rsplit(":", 1)[-1]) for line in out.splitlines() if ":" in line) if code == 0 else 0


async def _changes(root: str, base: str) -> tuple[list[tuple[str, Change]], list[str]]:
    code, out, _err = await safe_git.git(root, "diff", "--name-status", "--no-renames", base, "HEAD")
    found, other = [], set()
    for line in out.splitlines() if code == 0 else []:
        status, _, path = line.partition("\t")
        if Path(path).suffix in OTHER_SOURCES:
            other.add(Path(path).suffix)
        if Path(path).suffix != ".py" or status not in ("M", "D"):
            continue
        base_code, before, _err = await safe_git.git(root, "show", f"{base}:{path}")
        after = "" if status == "D" else (Path(root) / path).read_text(encoding="utf-8", errors="replace")
        if base_code == 0:
            found += [(path, change) for change in changed_signatures(before, after or "\n")]
    return found, sorted(other)


async def check_callers(root: str, base: str) -> CallerCheck:
    """Every call in the checked-out head that a changed signature breaks, and the ones that still fit."""
    result = CallerCheck()
    changes, result.not_checked = await _changes(root, base)
    for path, change in changes:
        new = change.new.render() if change.new is not None else " (removed)"
        result.changes.append(f"{path}: {change.name}{change.old.render()} -> {change.name}{new}")
        top, _, method = change.name.partition(".")
        # A method is judged by name only where that name is defined once (none left: the removed method itself).
        unique = bool(method) and await _definitions(root, method) == (0 if change.new is None else 1)
        for caller in await _grep(root, change.short):
            source = (Path(root) / caller).read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(source)
            except (SyntaxError, ValueError):
                continue
            names, aliases = _bindings(tree, caller, module_of(path), top)
            lines = source.splitlines()
            for call in _calls(tree, change, names, aliases, unique):
                _judge(result, change, path, caller, call, lines)
    return result


def _judge(result: CallerCheck, change: Change, path: str, caller: str, call: ast.Call, lines: list[str]) -> None:
    text = lines[call.lineno - 1].strip() if 0 < call.lineno <= len(lines) else ""
    problem = "still uses it" if change.new is None else call_problem(call, change.new)
    if not problem:
        result.fitting.append(f"{caller}:{call.lineno}: {text}")
        return
    before = f"`{change.name}{change.old.render()}`"
    fix = (f"{before} was removed from {path}, but this call {problem}." if change.new is None else
           f"{before} became `{change.name}{change.new.render()}` in {path}; this call {problem}. Update the call "
           "or keep the change compatible (for example a default for a new parameter).")
    result.findings.append({"severity": "high", "file": caller, "line": call.lineno, "fix": fix,
                            "id": f"C{len(result.findings) + 1}", "source": "caller_check"})


__all__ = ["CallerCheck", "check_callers", "module_of"]
