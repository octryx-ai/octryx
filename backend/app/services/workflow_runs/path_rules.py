"""A phase's path rules join the workspace write decision.

A phase may declare ``workflow_contract.path_rules.write``: the only paths its turns may change (e.g. a
"tests first" phase writes test paths only). The coding agent's edit and patch tools already ask one
decision for every write (``coding_policy_runtime.enforce_workspace_path_policy``); while the session
follows a phased run whose current node is such a phase, a path outside the patterns is blocked there.

``path_rules.protect_confirmed_tests: true`` (TDD fix / implement phases) blocks every write to a test file a person
confirmed (``test_runs.snapshot_confirmed_tests``); such a phase changes only existing non-test, non-config files and
creates new files only under its ``path_rules.create`` patterns (``protected_paths``, an allow-list). A write to a
confirmed test file whose new content the tool states passes only when it is formatting only — the same Python
syntax tree (``format_only``; e.g. a CI lint fix in the confirmed test file). git's own files and
environments are never written in any phase.

Shell tools (``bash``, CLI and validation commands) write paths no decision sees, so a phase with path rules may not
offer them: refused at publish (``graph``) and denied in the phase's tool policy at runtime.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .graph import NODE_PARALLEL, NODE_PHASE, graph_for_run
from .records import active_run_for_session
from .states import KIND_PHASED, STATUS_RUNNING

RULE_SOURCE = "workflow_phase_path_rule"
PROTECT_CONFIRMED_TESTS = "protect_confirmed_tests"
WRITE_TESTS = "write_tests"
# Tools that write through a shell: their paths never reach the workspace write decision.
PATH_UNCHECKED_TOOLS = frozenset({"bash", "run_cli_command", "run_validation_commands"})


def _rules(config: dict[str, Any]) -> dict[str, Any]:
    contract = config.get("workflow_contract") if isinstance(config.get("workflow_contract"), dict) else {}
    return contract.get("path_rules") if isinstance(contract.get("path_rules"), dict) else {}


def phase_write_patterns(config: dict[str, Any]) -> list[str]:
    return [str(item).strip() for item in _rules(config).get("write") or [] if str(item or "").strip()]


def phase_create_patterns(config: dict[str, Any]) -> list[str]:
    """Where a phase that protects the confirmed tests may create new files (``path_rules.create``)."""
    return [str(item).strip() for item in _rules(config).get("create") or [] if str(item or "").strip()]


def protects_confirmed_tests(config: dict[str, Any]) -> bool:
    return _rules(config).get(PROTECT_CONFIRMED_TESTS) is True


def writes_tests(config: dict[str, Any]) -> bool:
    """Every test file but the confirmed ones stays writable under ``protect_confirmed_tests`` (a merged phase)."""
    return _rules(config).get(WRITE_TESTS) is True


def has_path_rules(config: dict[str, Any]) -> bool:
    return bool(phase_write_patterns(config)) or protects_confirmed_tests(config)


def _outcome(run: Any, node: Any, path: str, reason: str) -> dict[str, Any]:
    return {
        "policy_id": f"{run.workflow_key}:{node.id}", "name": f"Phase '{node.title}' path rule",
        "policy_type": RULE_SOURCE, "severity": "high", "enforcement_mode": "block", "effect": "block",
        "blocking": True, "reason": reason, "remediation": "Change this path in a later phase of the workflow run.",
        "evidence": {"paths": [path], "run_id": run.id, "phase": node.id},
    }


async def _protected_writes(db: AsyncSession, session_id: str | None, run: Any, paths: list[str], *,
                            protect_tests: bool, create: list[str], tests_free: bool = False,
                            proposed: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """``(path, kind)`` of the paths (relative to the turn's tool root) the phase never lets change.

    Each path is resolved (symlinks, ``..``) and taken relative to the working copy it is in — the run's own, a
    slice's worktree (the child edits its own) or the session's workspace — then compared case-folded
    (``protected_paths``)."""
    from pathlib import Path

    from ...models import Session
    from ..session.workspace import resolve_session_workspace_root
    from .format_only import formatting_only
    from .phase_workspace import phase_rules_root
    from .protected_paths import (
        KIND_CONFIRMED_TEST,
        environment_names,
        is_flat_repository,
        protected_kind,
        shadows_installed,
    )
    from .test_runs import confirmed_baseline_intact

    session = await db.get(Session, session_id) if session_id else None
    if session is None:
        return []
    # The root the turn's tools wrote relative to: the run's working copy on the server, else the session's folder.
    root = await phase_rules_root(db, session, run) or Path(
        str(await resolve_session_workspace_root(db, session))).resolve()
    context = dict(run.context or {})
    files = [str(entry.get("file")) for entry in dict(context.get("confirmed_test_files") or {}).values()
             if isinstance(entry, dict) and entry.get("file")]
    copies = [Path(str(item.get("path"))).resolve()
              for item in [*dict(context.get("slices") or {}).values(),
                           *dict(dict(context.get("work") or {}).get("items") or {}).values()]
              if isinstance(item, dict) and item.get("path")]
    local = str(context.get("local_path") or "")
    copies += [Path(local).resolve()] if local else []
    copies.append(root)

    known: dict[Path, frozenset[str]] = {}

    def environment(copy: Path) -> frozenset[str]:
        if copy not in known:
            known[copy] = environment_names(copy)
        return known[copy]

    def kind_of(path: str) -> str | None:
        target = (root / path).resolve()
        for copy in copies:
            if target.is_relative_to(copy):
                relative = str(target.relative_to(copy))
                exists = target.exists()
                shadows = protect_tests and not exists and shadows_installed(copy, relative, environment(copy))
                kind = protected_kind(relative, confirmed_files=files, protect_tests=protect_tests, exists=exists,
                                      create=create, shadows=shadows, flat=is_flat_repository(copy, create),
                                      tests_free=tests_free)
                # Formatting only of the confirmed content: the file must first be provably intact (confirmed bytes,
                # or the syntax tree fingerprinted at confirmation); a drifted or unprovable file is refused before
                # the write.
                if (kind == KIND_CONFIRMED_TEST and confirmed_baseline_intact(run, target)
                        and formatting_only(target, (proposed or {}).get(path))):
                    continue
                if kind:
                    return kind
        return None

    return [(path, kind) for path in paths if (kind := kind_of(path))]


def blocked_paths(paths: list[str], patterns: list[str]) -> list[str]:
    from .protected_paths import path_matches

    return [path for path in paths if not any(path_matches(path, pattern) for pattern in patterns)]


async def phase_path_outcomes(db: AsyncSession, session_id: str | None, paths: list[str], *,
                              proposed: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """The phase's blocking outcomes for ``paths``; ``proposed`` maps a path to the content the write leaves."""
    run = await active_run_for_session(db, session_id)
    if run is None or run.workflow_kind != KIND_PHASED or run.status != STATUS_RUNNING:
        return []
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
    if node is not None and node.kind == NODE_PARALLEL:
        from .teamwork.item_definition import session_item_node

        node = await session_item_node(db, run, node, session_id)  # an item writes only its own paths
    if node is None or node.kind != NODE_PHASE:
        return []
    outcomes = []
    patterns = phase_write_patterns(node.config)
    if patterns:
        outcomes += [_outcome(run, node, path, f"Phase '{node.title}' may only change: {', '.join(patterns)}.")
                     for path in blocked_paths(paths, patterns)]
    from .protected_paths import protected_message
    from .test_runs import confirmed_by

    outcomes += [_outcome(run, node, path, protected_message(kind, path, node.title, confirmed_by(run)))
                 for path, kind in await _protected_writes(db, session_id, run, paths,
                                                           protect_tests=protects_confirmed_tests(node.config),
                                                           create=phase_create_patterns(node.config),
                                                           tests_free=writes_tests(node.config),
                                                           proposed=proposed)]
    return outcomes


__all__ = ["PATH_UNCHECKED_TOOLS", "PROTECT_CONFIRMED_TESTS", "blocked_paths", "has_path_rules",
           "phase_create_patterns", "phase_path_outcomes", "phase_write_patterns", "protects_confirmed_tests",
           "writes_tests"]
