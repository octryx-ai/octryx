from __future__ import annotations

import ast
import io
import re
import tokenize
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path

from tests.guards._comment_style_public import PublicIndex, classified_definitions, public_index
from tests.guards._support import REPO_ROOT

SCANNED = ("backend/app", "backend/tests", "clients/octryx-claude")
SKIPPED_DIRS = frozenset({"__pycache__", ".venv", "venv", "node_modules", "build", "dist", ".pytest_cache"})
RULES = ("non-public docstring lines", "docstring lines beyond 2", "narration lines", "comment lines over 15 %")
MAX_DOCSTRING_LINES = 2
MAX_COMMENT_SHARE = 0.15
FREE_COMMENT_LINES = 1
NARRATION = re.compile("|".join((
    r"\bC\d+[A-Z]?-\d+\b",
    r"\bobservability O-?D?\d+\b|\bO-D\d+\b",
    r"\b[BSH]-0\d\b",
    r"\bCut \d+\b",
    r"\(owner \d{1,2}\.\d{1,2}|\bowner decision (of )?\d",
    r"\btrain \d+\b",
    r"\bcodex audit|\baudit finding|\bfinding [A-Z]-?\d|\bticket [A-Z]+-\d+",
    r"\bmoved from\b|\bformerly\b|\bfor backward|\bbackwards? compat",
)), re.IGNORECASE)
# These modules print their own __doc__ as usage text.
LONG_MODULE_DOCSTRING_EXEMPT = frozenset({
    "backend/app/services/knowledge/eval/change_typing.py",
    "backend/app/services/knowledge/eval/library_run.py",
    "backend/app/services/knowledge/eval/run.py",
    "clients/octryx-claude/scripts/render_pet_icons.py",
})
_TOOL_DIRECTIVE = re.compile(r"#!|#\s*(noqa|type:|pragma|fmt:|ruff:|pyright:|mypy:|pylint:|isort:|-\*- coding)")
_SHARE = len(RULES) - 1
REGENERATE = ".venv/bin/python -m tests.guards._comment_style (from backend/)"
# Only these keep a ratchet: docstrings that are schema descriptions, and the files still above the limits;
# everywhere else a finding fails and the baseline may not list it.
RATCHETED = (
    "backend/app/schemas/",
    "backend/app/agent/runtime/types.py", "backend/app/api/routes/knowledge/knowledge_evidence_search.py",
    "backend/app/api/routes/secure_work/secure_work_plan_answers.py", "backend/app/services/agent_reply_contract_model.py",
    "backend/app/services/speaker/voice_enrollment.py", "backend/app/tools/alert_scope.py",
)
BASELINE_FILE = Path(__file__).with_name("_comment_style_baseline.py")

Counts = tuple[int, int, int, int, int]
NO_COUNTS: Counts = (0, 0, 0, 0, 0)


def scanned_files(root: Path) -> Iterator[Path]:
    for top in SCANNED:
        for path in sorted((root / top).rglob("*.py")):
            parts = path.relative_to(root).parts[:-1]
            if not SKIPPED_DIRS.intersection(parts) and not any(part.endswith(".egg-info") for part in parts):
                yield path


def _docstring(node: ast.AST) -> ast.Expr | None:
    body = getattr(node, "body", None)
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return first
    return None


def _docstring_counts(
    tree: ast.Module, relative: str, lines: list[str], index: PublicIndex,
) -> tuple[int, int, set[int]]:
    internal = long = 0
    narrated: set[int] = set()
    for node, public in ((tree, True), *classified_definitions(tree, relative, index)):
        docstring = _docstring(node)
        if docstring is None:
            continue
        span = range(docstring.lineno, docstring.end_lineno + 1)
        narrated.update(number for number in span if NARRATION.search(lines[number - 1]))
        if isinstance(node, ast.Module):
            if relative not in LONG_MODULE_DOCSTRING_EXEMPT:
                long += max(0, len(span) - MAX_DOCSTRING_LINES)
        elif public:
            long += max(0, len(span) - MAX_DOCSTRING_LINES)
        else:
            internal += len(span)
    return internal, long, narrated


def file_counts(source: str, tree: ast.Module, relative: str, index: PublicIndex) -> Counts:
    lines = source.splitlines()
    internal, long, narrated = _docstring_counts(tree, relative, lines, index)
    comment_lines = 0
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        if NARRATION.search(token.string):
            narrated.add(token.start[0])
        if not _TOOL_DIRECTIVE.match(token.string):
            comment_lines += 1
    non_blank = sum(1 for line in lines if line.strip())
    if comment_lines <= max(FREE_COMMENT_LINES, MAX_COMMENT_SHARE * non_blank):
        comment_lines = non_blank = 0
    return internal, long, len(narrated), comment_lines, non_blank


def comment_style_counts(root: Path, files: Iterable[Path]) -> dict[str, Counts]:
    sources = {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8") for path in files}
    index = public_index(root, sources)
    found: dict[str, Counts] = {}
    for relative, source in sources.items():
        counts = file_counts(source, ast.parse(source, filename=relative), relative, index)
        if any(counts):
            found[relative] = counts
    return found


def ratcheted(path: str) -> bool:
    return path.startswith(RATCHETED)


def _strict_problems(key: str, now: Counts, listed: bool) -> list[str]:
    problems = [f"{key}: {rule} {count}: fix them (no baseline outside RATCHETED)"
                for rule, count in zip(RULES[:_SHARE], now, strict=False) if count]
    if now[_SHARE]:
        problems.append(f"{key}: {RULES[_SHARE]} {now[_SHARE]}/{now[_SHARE + 1]}: remove comments")
    if listed:
        problems.append(f"{key}: outside RATCHETED, the baseline may not list it ({REGENERATE})")
    return problems


def ratchet_problems(found: Mapping[str, Counts], baseline: Mapping[str, Counts]) -> list[str]:
    problems: list[str] = []
    for key in sorted(found.keys() | baseline.keys()):
        if not ratcheted(key):
            problems += _strict_problems(key, found.get(key, NO_COUNTS), key in baseline)
            continue
        now, allowed = found.get(key, NO_COUNTS), baseline.get(key, NO_COUNTS)
        for rule, count, limit in zip(RULES[:_SHARE], now, allowed, strict=False):
            if count > limit:
                problems.append(f"{key}: {rule} {count}, baseline {limit}: fix the new ones")
            elif count < limit:
                problems.append(f"{key}: {rule} {count}, baseline {limit}: lower the baseline ({REGENERATE})")
        (comments, lines), (allowed_comments, allowed_lines) = now[_SHARE:], allowed[_SHARE:]
        share = f"{key}: {RULES[_SHARE]} {comments}/{lines}, baseline {allowed_comments}/{allowed_lines}"
        if comments > allowed_comments:
            problems.append(f"{share}: fix the new ones")
        elif comments * allowed_lines > allowed_comments * lines:
            problems.append(f"{share}: the share rose, remove comments")
        elif comments < allowed_comments:
            problems.append(f"{share}: lower the baseline ({REGENERATE})")
    return problems


def baseline_source(found: dict[str, Counts]) -> str:
    rows = "".join(f'    "{path}": {counts},\n' for path, counts in sorted(found.items()))
    return (
        "from __future__ import annotations\n\n"
        f"# Generated by `{REGENERATE}`.\n"
        "# Columns: the first three _comment_style.RULES, then comment lines and non-blank lines over the share.\n"
        f"COMMENT_STYLE_BASELINE: dict[str, tuple[int, int, int, int, int]] = {{\n{rows}}}\n"
    )


# Regenerating only lowers: no new row, and a row that grew keeps its old counts (its growth fails the guard).
def regenerated(found: Mapping[str, Counts], baseline: Mapping[str, Counts]) -> dict[str, Counts]:
    rows: dict[str, Counts] = {}
    for key, old in baseline.items():
        now = found.get(key, NO_COUNTS)
        if not ratcheted(key) or not any(now):
            continue
        grew = any("fix the new ones" in problem or "the share rose" in problem
                   for problem in ratchet_problems({key: now}, {key: old}))
        rows[key] = old if grew else now
    return rows


if __name__ == "__main__":
    from tests.guards._comment_style_baseline import COMMENT_STYLE_BASELINE

    found = comment_style_counts(REPO_ROOT, scanned_files(REPO_ROOT))
    BASELINE_FILE.write_text(baseline_source(regenerated(found, COMMENT_STYLE_BASELINE)), encoding="utf-8")
