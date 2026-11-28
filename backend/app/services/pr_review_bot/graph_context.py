"""Code graph and agent-run context for the reviewer."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ..workflow_runs import safe_git

logger = logging.getLogger(__name__)
MAX_SYMBOLS, MAX_PER_SYMBOL, MAX_GRAPH_CHARS = 10, 15, 12_000
_DEFINED = re.compile(r"^[+-]\s*(?:export\s+)?(?:async\s+)?(?:(?:def|class|function|fun|func|interface|struct|enum)\s+|"
                      r"(?:(?:public|private|protected|static|final|override|internal|abstract)\s+)+"
                      r"(?:[\w<>\[\],.?]+\s+)?)([A-Za-z_][A-Za-z0-9_]{2,})\s*[(<:{]", re.MULTILINE)


def changed_symbols(diff: str) -> list[str]:
    found: list[str] = []
    for line in diff.splitlines():
        if line.startswith(("+++", "---")):
            continue
        match = _DEFINED.match(line)
        if match and match.group(1) not in found and match.group(1) not in ("self", "return"):
            found.append(match.group(1))
    return found[:MAX_SYMBOLS]


def _where(item: dict[str, Any]) -> str:
    return f"{item.get('path')}:{item.get('line') or item.get('line_start') or '?'}"


def graph_text(impacts: dict[str, dict[str, Any]], changed: set[str]) -> tuple[str, int, set[str]]:
    lines, count, files = [], 0, set()
    for symbol, impact in impacts.items():
        seen, rows = set(), []
        for item in [*(impact.get("callers") or []), *(impact.get("references") or [])]:
            path = str(item.get("path") or "")
            if not path or path in changed or _where(item) in seen:
                continue
            seen.add(_where(item))
            rows.append(f"  {_where(item)}" + (f" {str(item.get('text') or item.get('name') or '').strip()[:120]}"
                                               if item.get("text") or item.get("name") else ""))
            files.add(path)
        if rows:
            count += len(rows)
            lines.append(f"{symbol} (risk {impact.get('risk', '?')}): used outside this change at")
            lines += rows[:MAX_PER_SYMBOL]
    return "\n".join(lines)[:MAX_GRAPH_CHARS], count, files


async def code_graph(db: AsyncSession, run: WorkflowRun, root: str, base: str, head: str) -> dict[str, Any]:
    from ..code_intelligence.queries import build_impact_analysis
    from .settings import repository_record

    record = await repository_record(db, str(run.project_id), str(run.repository))
    if not root or not base:
        return {}
    diff = (await safe_git.git(root, *safe_git.DIFF, base, head))[1]
    changed = {path for path in (await safe_git.git(root, "diff", "--name-only", base, head))[1].splitlines()}
    impacts: dict[str, dict[str, Any]] = {}
    unavailable = False
    for symbol in changed_symbols(diff) if record is not None else []:
        try:
            impacts[symbol] = await build_impact_analysis(db=db, repository_id=record.id, cwd=Path(root),
                                                          project_id=str(run.project_id), symbol=symbol,
                                                          limit=MAX_PER_SYMBOL)
        except Exception:  # noqa: BLE001 - a repository the graph does not index: the review goes on without it
            logger.info("pr_review_bot.graph_unavailable repository=%s symbol=%s", run.repository, symbol)
            impacts, unavailable = {}, True
            break
    text, count, files = graph_text(impacts, changed)
    if text:
        _add_section(run, "callers and references of the changed symbols (code graph, outside this change)", text)
    # What the change calls, defined outside it (a helper in another module is not in the diff,
    # and without it the reviewer can only judge a criterion "partial").
    callees = await callee_definitions(root, called_names(diff), changed)
    if callees:
        body = "\n\n".join(f"{name} at {where}:\n{code}" for name, where, code in callees)[:MAX_CALLEE_CHARS]
        _add_section(run, "definitions of the functions this change calls (outside this change)", body)
    facts = {"symbols": len(impacts), "callers": count, "files": len(files)} if impacts else {}
    return {**facts, **({"callees": len(callees)} if callees else {}), **({"unavailable": True} if unavailable else {})}


_CALL = re.compile(r"(?<![\w.])(?:[A-Za-z_][A-Za-z0-9_]*\.)?([A-Za-z_][A-Za-z0-9_]{2,})\s*\(")
_NOT_CALLS = frozenset({
    "and", "assert", "await", "catch", "class", "def", "elif", "else", "for", "function", "if", "lambda", "not",
    "return", "switch", "while", "with", "yield", "print", "len", "sum", "min", "max", "int", "str", "float",
    "bool", "list", "dict", "set", "tuple", "range", "sorted", "reversed", "enumerate", "zip", "map", "filter",
    "isinstance", "getattr", "setattr", "hasattr", "super", "type", "repr", "round", "abs", "any", "all", "open",
    "format", "append", "extend", "update", "items", "keys", "values", "get", "join", "split", "strip", "replace",
    "startswith", "endswith", "lower", "upper", "require", "console", "log", "push", "then", "Decimal"})
MAX_CALLEES, MAX_CALLEE_LINES, MAX_CALLEE_CHARS = 10, 40, 10_000


def called_names(diff: str) -> list[str]:
    defined = set(changed_symbols(diff))
    found: list[str] = []
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++") or _DEFINED.match(line):
            continue
        for match in _CALL.finditer(line[1:]):
            name = match.group(1)
            if name not in _NOT_CALLS and name not in defined and name not in found:
                found.append(name)
    return found[:MAX_CALLEES]


def _python_definition(path: Path, name: str, line: int) -> str:
    import ast

    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name and (
                    node.lineno == line):
                lines = source.splitlines()[node.lineno - 1:(node.end_lineno or node.lineno)]
                return "\n".join(lines[:MAX_CALLEE_LINES])
    except (OSError, SyntaxError, ValueError):
        return ""
    return ""


async def callee_definitions(root: str, names: list[str], changed: set[str]) -> list[tuple[str, str, str]]:
    found = []
    for name in names:
        code, out, _err = await safe_git.git(root, "grep", "-n", "-I", "-E",
                                             rf"(def|function|fun|func|class)[[:space:]]+{re.escape(name)}"
                                             r"([^A-Za-z0-9_]|$)")  # POSIX classes: git grep -E has no \s or \b
        for row in out.splitlines() if code == 0 else []:
            path, _, rest = row.partition(":")
            number, _, _text = rest.partition(":")
            if not number.isdigit() or path in changed:
                continue
            target = Path(root) / path
            text = _python_definition(target, name, int(number)) if path.endswith(".py") else ""
            if not text:
                try:
                    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                text = "\n".join(lines[int(number) - 1:int(number) - 1 + 25])
            found.append((name, f"{path}:{number}", text))
            break
    return found


async def authoring_run(db: AsyncSession, run: WorkflowRun, run_id: str) -> dict[str, Any]:
    from ..workflow_runs.review.evidence import _test_facts, confirmed_contract

    author = await db.get(WorkflowRun, run_id) if run_id else None
    if author is None or author.project_id != run.project_id:
        return {}
    text = _test_facts(author, await confirmed_contract(db, author))
    if text.strip():
        _add_section(run, f"the Octryx run {author.id[:8]} that opened this pull request: its confirmed acceptance "
                          "criteria and test facts", text)
    return {"run": author.id, "workflow": author.workflow_key}


def _add_section(run: WorkflowRun, title: str, text: str) -> None:
    context = dict(run.context or {})
    context["review_context_sections"] = [*(context.get("review_context_sections") or []),
                                          {"title": title, "text": text}]
    run.context = context


__all__ = ["authoring_run", "callee_definitions", "called_names", "changed_symbols", "code_graph", "graph_text"]
