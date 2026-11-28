"""The specification's decisions checked against the code, so a decided technology cannot silently stay unbuilt."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .decision_evidence import (
    AppFiles,
    decided_technologies,
    literal_evidence,
    literals,
    read_lines,
    technology_evidence,
)

IMPLEMENTED, MISSING, UNCLEAR, CONTEXT = "implemented", "missing", "unclear", "context"
MAX_DECISIONS = 60
MARK = {IMPLEMENTED: "✓", MISSING: "✗", UNCLEAR: "?", CONTEXT: "·"}
_HEADING = re.compile(r"^(#{1,4})\s+(?:[\d.]+\s+)?(.+?)\s*$")
_DECISION_TITLE = re.compile(r"^(decisions?|entscheidungen|technical requirements|technische anforderungen|"
                             r"technische entscheidungen|architecture decisions)\b", re.IGNORECASE)
_ITEM = re.compile(r"^\s{0,3}(?:(\d{1,3})[.)]|[-*])\s+(.+)$")


@dataclass
class Decision:
    number: int
    text: str
    hard: bool = False
    state: str = UNCLEAR
    technologies: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    reason: str = ""

    def line(self) -> str:
        where = "; ".join(self.evidence[:4]) or self.reason
        return f"{MARK[self.state]} {self.number}. {self.text[:300]} [{self.state}{', hard' if self.hard else ''}]" \
               + (f" - {where}" if where else "")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "text": self.text[:500], "evidence": self.evidence[:8]}


@dataclass
class DecisionCheck:
    spec: str
    decisions: list[Decision]
    scope: str = "whole_spec"

    @property
    def missing(self) -> list[Decision]:
        return [item for item in self.decisions if item.hard and item.state == MISSING]

    def table(self) -> str:
        return "\n".join(item.line() for item in self.decisions)

    def to_dict(self) -> dict[str, Any]:
        return {"spec": self.spec, "scope": self.scope, "decisions": [item.to_dict() for item in self.decisions]}


def decision_items(text: str) -> list[str]:
    items: list[str] = []
    level = 0
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            depth = len(heading.group(1))
            if level and depth <= level:
                level = 0
            if not level and _DECISION_TITLE.match(heading.group(2)):
                level = depth
            continue
        if not level or not line.strip():
            continue
        item = _ITEM.match(line)
        if item:
            items.append(item.group(2).strip())
        elif items and line.startswith((" ", "\t")):
            items[-1] = f"{items[-1]} {line.strip()}"
    return items[:MAX_DECISIONS]


def spec_for_change(root: Path, changed: tuple[str, ...]) -> Path | None:
    specs = [path for path in (*root.glob("SPEC.md"), *root.glob("*/SPEC.md"), *root.glob("*/*/SPEC.md"),
                               *root.glob("*/*/*/SPEC.md"), *root.glob("*/*/*/*/SPEC.md")) if path.is_file()]
    if not specs:
        return None

    def score(spec: Path) -> tuple[int, int]:
        folder = spec.parent.relative_to(root).as_posix()
        prefix = "" if folder == "." else f"{folder}/"
        return sum(1 for path in changed if path.startswith(prefix)), len(spec.parts)

    best = max(specs, key=score)
    return best if score(best)[0] or best.parent == root else None


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def check_decisions(root: Path | None, changed: tuple[str, ...], *, introduced: set[str] | None = None,
                    scope: str = "whole_spec", catalog: dict[str, dict[str, Any]] | None = None,
                    stacks: dict[str, Any] | None = None) -> DecisionCheck | None:
    if root is None:
        return None
    spec = spec_for_change(root, changed)
    if spec is None:
        return None
    items = decision_items("\n".join(read_lines(spec)))
    if not items:
        return None
    if catalog is None:
        from ...code_style.technologies import catalog as built_in_catalog

        catalog = built_in_catalog()
    files = AppFiles.read(spec.parent, root, stacks)
    folder = spec.parent.relative_to(root).as_posix() or "."
    cache: dict[str, tuple[list[str], list[str]]] = {}
    decisions = []
    for number, text in enumerate(items, 1):
        decision = Decision(number, text, technologies=decided_technologies(text, catalog))
        if introduced is not None and _key(text) not in introduced:
            decision.state, decision.reason = CONTEXT, "an existing decision: context for this work, not checked"
        elif decision.technologies:
            _technologies(decision, files, catalog, cache, folder)
        else:
            _values(decision, files)
        decisions.append(decision)
    return DecisionCheck(spec.relative_to(root).as_posix(), decisions, scope)


def _technologies(decision: Decision, files: AppFiles, catalog: dict[str, dict[str, Any]],
                  cache: dict[str, tuple[list[str], list[str]]], folder: str) -> None:
    decision.hard = True
    states, reasons = [], []
    for key in decision.technologies:
        entry = catalog[key]
        if key not in cache:
            cache[key] = technology_evidence(files, entry)
        dependencies, uses = cache[key]
        decision.evidence += dependencies[:2] + uses[:2]
        if entry.get("kind") == "platform_api":
            states.append(IMPLEMENTED if uses else MISSING)
            if not uses:
                reasons.append(f"{key}: not used in the app's code")
            continue
        states.append(IMPLEMENTED if dependencies and uses else MISSING if not (dependencies or uses) else UNCLEAR)
        if not (dependencies or uses):
            reasons.append(f"{key}: no dependency in the app's manifest and no use in its code")
        elif not uses:
            reasons.append(f"{key}: declared but never used")
        elif not dependencies:
            reasons.append(f"{key}: used but not declared as a dependency")
    # A platform API the decision names next to a package that is there is used through that package: unclear for the
    # reviewer, never missing.
    provided = [key for key, state in zip(decision.technologies, states, strict=True)
                if state == IMPLEMENTED and catalog[key].get("kind") != "platform_api"]
    if provided:
        for index, key in enumerate(decision.technologies):
            if states[index] == MISSING and catalog[key].get("kind") == "platform_api":
                states[index] = UNCLEAR
                reasons = [reason if not reason.startswith(f"{key}:") else
                           f"{key}: not used directly, possibly through {', '.join(provided)}" for reason in reasons]
    decision.reason = "; ".join(reasons) + (f" ({folder})" if reasons else "")
    decision.state = MISSING if MISSING in states else UNCLEAR if UNCLEAR in states else IMPLEMENTED


def _values(decision: Decision, files: AppFiles) -> None:
    stated = literals(decision.text)
    if not stated:
        decision.reason = "not provable by a code search: the reviewer checks it"
        return
    states = []
    for literal in stated:
        state, found = literal_evidence(files, literal)
        states.append(state)
        decision.evidence += found
        if state == "differs":
            decision.reason = f"{' '.join(literal.terms)}: decided {literal.value}, the code has another value"
    if "differs" in states:
        decision.state = MISSING
    elif all(state == "found" for state in states):
        decision.state = IMPLEMENTED
    else:
        decision.reason = decision.reason or "values not found near their terms: the reviewer checks them"


async def _git_text(root: Path, *args: str) -> str | None:
    from .. import safe_git

    code, out, _err = await safe_git.git(root, *args)
    return out if code == 0 else None


async def feature_decisions(root: Path | None, changed: tuple[str, ...], keys: tuple[str, ...],
                            base: str = "", *, recorded: dict[str, Any] | None = None,
                            catalog: dict[str, dict[str, Any]] | None = None,
                            stacks: dict[str, Any] | None = None) -> DecisionCheck | None:
    if root is None:
        return None
    spec = spec_for_change(root, changed)
    if spec is None:
        return None
    path = spec.relative_to(root).as_posix()
    introduced: set[str] = set()
    scoped = False
    commit = subject = ""
    if recorded and recorded.get("path") == path and isinstance(recorded.get("introduced"), list):
        scoped = True
        commit, subject = str(recorded.get("sha") or ""), "recorded at the spec push"
        introduced |= {_key(str(item)) for item in recorded["introduced"]}
    else:
        log = await _git_text(root, "log", "--format=%H%x1f%s", "-n", "200", "--", path)
        for line in (log or "").splitlines():
            sha, _sep, text = line.partition("\x1f")
            if any(key and re.search(rf"(?<![\w-]){re.escape(key)}(?![\w-])", text) for key in keys):
                commit, subject = sha, text
                break
    if commit and not scoped:
        after = await _git_text(root, "show", f"{commit}:{path}")
        before = await _git_text(root, "show", f"{commit}^:{path}")
        if after is not None:
            scoped = True
            introduced |= {_key(item) for item in decision_items(after)} - {
                _key(item) for item in decision_items(before or "")}
    if path in changed:
        old = await _git_text(root, "show", f"{base or 'HEAD'}:{path}")
        if old is not None:
            scoped = True
            current = "\n".join(read_lines(spec))
            introduced |= {_key(item) for item in decision_items(current)} - {
                _key(item) for item in decision_items(old)}
    if not scoped:
        check = check_decisions(root, changed, catalog=catalog, stacks=stacks)
        if check is not None and base:
            await _base_open(check, root, spec, base, catalog)
        return check
    scope = f"feature: {commit[:12]} {subject[:120]}" if commit else "feature: the change's own spec edit"
    return check_decisions(root, changed, introduced=introduced, scope=scope, catalog=catalog, stacks=stacks)


async def _base_open(check: DecisionCheck, root: Path, spec: Path, base: str,
                     catalog: dict[str, dict[str, Any]] | None) -> None:
    # A technology decision the base does not implement either is the app's open decision: context, never blocking.
    import asyncio  # noqa: PLC0415
    import io  # noqa: PLC0415
    import tarfile  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    from .decision_evidence import AppFiles  # noqa: PLC0415

    missing = [item for item in check.decisions if item.state == MISSING and item.technologies]
    if not missing or not re.fullmatch(r"[0-9a-f]{7,40}", base):
        return
    folder = spec.parent.relative_to(root).as_posix() or "."
    process = await asyncio.create_subprocess_exec("git", "-C", str(root), "archive", "--format=tar", base, "--",
                                                   folder, stdout=asyncio.subprocess.PIPE,
                                                   stderr=asyncio.subprocess.DEVNULL)
    archive, _err = await process.communicate()
    if process.returncode != 0 or not archive:
        return
    if catalog is None:
        from ...code_style.technologies import catalog as built_in_catalog  # noqa: PLC0415

        catalog = built_in_catalog()
    with tempfile.TemporaryDirectory(prefix="octryx-decisions-base-") as scratch:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(scratch, filter="data")
        base_root = Path(scratch)
        files = AppFiles.read(base_root / folder, base_root)
        cache: dict[str, tuple[list[str], list[str]]] = {}
        for decision in missing:
            before = Decision(decision.number, decision.text, technologies=decision.technologies)
            _technologies(before, files, catalog, cache, folder)
            if before.state == MISSING:
                decision.state = CONTEXT
                decision.reason = (f"{decision.reason}; not implemented at the base either: the app's open decision, "
                                   "not this change's")


__all__ = ["CONTEXT", "IMPLEMENTED", "MISSING", "UNCLEAR", "Decision",
           "DecisionCheck", "check_decisions", "decision_items", "feature_decisions", "spec_for_change"]
