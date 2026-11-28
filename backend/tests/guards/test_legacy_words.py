from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from tests.guards._legacy_words import ALLOWED_WORDS
from tests.guards._support import REPO_ROOT, assert_guard, comparison_problems

PATTERN = re.compile(r"\b(legacy|deprecated|backward[- ]compat\w*|retired)\b", re.IGNORECASE)
SCANNED = ("backend/app", "frontend/chat/src", "clients")
SKIPPED_DIRS = frozenset({
    "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "static",  # the built frontend bundle
})
MODULE = "<module>"
# A top-level declaration of a TypeScript or JavaScript file: the definition an occurrence below it belongs to.
_DECLARATION = re.compile(r"^(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:async\s+)?"
                          r"(?:function\*?|class|interface|type|enum|const|let|var)\s+([A-Za-z_$][\w$]*)")


def scanned_files(root: Path) -> Iterable[Path]:
    for top in SCANNED:
        for path in sorted((root / top).rglob("*")):
            relative = path.relative_to(root)
            if path.is_file() and not SKIPPED_DIRS.intersection(relative.parts[:-1]) \
                    and not any(part.endswith(".egg-info") for part in relative.parts):
                yield path


def _python_definitions(text: str) -> dict[int, str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    owners: dict[int, str] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                name = f"{prefix}.{child.name}" if prefix else child.name
                for line in range(child.lineno, (child.end_lineno or child.lineno) + 1):
                    owners[line] = name  # inner definitions are visited later and overwrite
                visit(child, name)
            else:
                visit(child, prefix)

    visit(tree, "")
    return owners


def definitions(path: Path, text: str) -> list[str]:
    lines = text.splitlines()
    if path.suffix == ".py":
        owners = _python_definitions(text)
        return [MODULE, *(owners.get(number, MODULE) for number in range(1, len(lines) + 1))]
    current, found = MODULE, [MODULE]
    for raw in lines:
        match = _DECLARATION.match(raw)
        current = match.group(1) if match else current
        found.append(current)
    return found


def occurrences(path: Path, text: str) -> Iterable[str]:
    owners = definitions(path, text)
    for number, raw in enumerate(text.splitlines(), start=1):
        line = " ".join(raw.split())
        for _match in PATTERN.finditer(line):
            yield f"[{owners[number]}]: {line}"


def counted_words(found: Counter[str]) -> set[str]:
    # A normalized line holds no tab, so the count can never be confused with the line's own text.
    return {key if count == 1 else f"{key}\t(x{count})" for key, count in found.items()}


def legacy_words(root: Path, files: Iterable[Path]) -> set[str]:
    found: Counter[str] = Counter()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(root).as_posix()
        found.update(f"{relative} {occurrence}" for occurrence in occurrences(path, text))
    return counted_words(found)


def test_legacy_words_equal_the_allowlist() -> None:
    assert_guard(legacy_words(REPO_ROOT, scanned_files(REPO_ROOT)), ALLOWED_WORDS, what="legacy word")


def test_mutation_planted_words_are_reported(tmp_path: Path) -> None:
    planted = tmp_path / "backend/app/services/planted.py"
    planted.parent.mkdir(parents=True)
    planted.write_text("# Legacy shim kept for backward-compatibility.\nRETIRED = 'retired'\n", encoding="utf-8")
    (tmp_path / "frontend/chat/src").mkdir(parents=True)
    (tmp_path / "frontend/chat/src/old.ts").write_text("/** @deprecated use next() */\n", encoding="utf-8")
    (tmp_path / "clients").mkdir()
    found = legacy_words(tmp_path, scanned_files(tmp_path))
    assert found == {
        "backend/app/services/planted.py [<module>]: # Legacy shim kept for backward-compatibility.\t(x2)",
        "backend/app/services/planted.py [<module>]: RETIRED = 'retired'\t(x2)",
        "frontend/chat/src/old.ts [<module>]: /** @deprecated use next() */",
    }
    assert comparison_problems(found, ALLOWED_WORDS, what="legacy word")


def test_mutation_new_hit_in_a_listed_file_is_reported(tmp_path: Path) -> None:
    relative = "backend/app/services/knowledge/temporal/changes.py"
    planted = tmp_path / relative
    planted.parent.mkdir(parents=True)
    planted.write_text((REPO_ROOT / relative).read_text(encoding="utf-8") + "# deprecated shim\n", encoding="utf-8")
    others = [path for path in scanned_files(REPO_ROOT) if path != REPO_ROOT / relative]
    found = legacy_words(REPO_ROOT, others) | legacy_words(tmp_path, [planted])
    assert comparison_problems(found, ALLOWED_WORDS, what="legacy word") == [
        f"new legacy word: {relative} [<module>]: # deprecated shim",
    ]


def test_mutation_an_approved_occurrence_moved_into_another_definition_is_reported(tmp_path: Path) -> None:
    # The plant is Python: a definition is recognised in a .py file only.
    key = next(entry.key for entry in ALLOWED_WORDS
               if entry.key.startswith("backend/app/") and " [<module>]: " in entry.key and "\t" not in entry.key
               and entry.key.partition(" [")[0].endswith(".py"))
    relative, _, text = key.partition(" [<module>]: ")
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    approved = next(line for line in source.splitlines() if " ".join(line.split()) == text)
    planted = tmp_path / relative
    planted.parent.mkdir(parents=True)
    moved = source.replace(approved + "\n", "", 1) + f"\n\ndef unrelated():\n    pass  # {approved.strip()}\n"
    planted.write_text(moved, encoding="utf-8")
    others = [path for path in scanned_files(REPO_ROOT) if path != REPO_ROOT / relative]
    problems = comparison_problems(legacy_words(REPO_ROOT, others) | legacy_words(tmp_path, [planted]),
                                   ALLOWED_WORDS, what="legacy word")
    assert any(problem.startswith(f"new legacy word: {relative} [unrelated]:") for problem in problems), problems


def test_mutation_a_literal_count_suffix_is_not_a_count(tmp_path: Path) -> None:
    once = tmp_path / "backend/app/once.py"
    once.parent.mkdir(parents=True)
    once.write_text("# deprecated shim (x2)\n", encoding="utf-8")
    twice = tmp_path / "backend/app/twice.py"
    twice.write_text("# deprecated shim\n# deprecated shim\n", encoding="utf-8")
    keys = {key.partition(" ")[2] for key in legacy_words(tmp_path, [once, twice])}
    assert keys == {"[<module>]: # deprecated shim (x2)", "[<module>]: # deprecated shim\t(x2)"}


def test_mutation_word_parts_are_not_whole_words(tmp_path: Path) -> None:
    planted = tmp_path / "backend/app/planted.py"
    planted.parent.mkdir(parents=True)
    planted.write_text("legacy_decision = retired_at = legacyReason = 'nonretired'\n", encoding="utf-8")
    assert legacy_words(tmp_path, [planted]) == set()
