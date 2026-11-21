"""The run's canonical test ids.

Every test id a run stores or compares is canonical (``workflow_checks.test_ids``). A result reported by a dotted
name (JUnit ``classname``, unittest, Jenkins) resolves against the files the run knows:

- the run's working copy on the server (``context.local_path``), when it exists;
- the files the confirmed tests, the submitted test contract and the reproduction name;
- the files of the results earlier runs keyed, and the files the launcher found next to a device report.

A test run is resolved when it is recorded and again whenever it is read (:func:`recorded_runs`): a result left
unresolved in Clarify (before any contract named its file) resolves as soon as the run knows the file. What still
does not resolve stays ``unresolved`` with its reason; the gates never match it (``test_results``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...models import WorkflowRun
from ..workflow_checks.test_ids import Resolver, file_of
from ..workflow_checks.test_output import ParsedTests


def _contract_ids(context: dict[str, Any]) -> list[str]:
    outputs = dict(context.get("outputs") or {})
    contract = dict(dict(outputs.get("test_contract") or {}).get("record") or {})
    reproduction = dict(dict(outputs.get("reproduction") or {}).get("record") or {})
    ids = [str(test) for criterion in contract.get("criteria") or [] if isinstance(criterion, dict)
           for test in criterion.get("tests") or []]
    return ids + [str(test) for test in reproduction.get("tests") or []]


def hint_files(run: WorkflowRun, extra_ids: list[str] | tuple[str, ...] = ()) -> set[str]:
    context = dict(run.context or {})
    files = {file for item in [*(context.get("confirmed_tests") or []), *_contract_ids(context), *extra_ids]
             if (file := file_of(str(item)))}
    for entry in dict(context.get("tests") or {}).get("runs") or []:
        files.update(file for test_id in dict(entry.get("results") or {}) if (file := file_of(test_id)))
        files.update(str(item) for item in entry.get("files") or [])
    return files


def resolver_for(run: WorkflowRun, extra_ids: list[str] | tuple[str, ...] = (),
                 extra_files: list[str] | tuple[str, ...] = ()) -> Resolver:
    local_path = str(dict(run.context or {}).get("local_path") or "")
    root = Path(local_path) if local_path and Path(local_path).is_dir() else None
    return Resolver(hint_files(run, extra_ids) | set(extra_files), root)


def resolve_entry(entry: dict[str, Any], resolver: Resolver) -> dict[str, Any]:
    """``entry`` with each unresolved result keyed when the resolver now knows its file."""
    pending = [item for item in entry.get("unresolved") or [] if isinstance(item, dict)]
    if not pending:
        return entry
    resolver = Resolver(resolver.files | set(entry.get("files") or []), resolver.root)
    parsed = ParsedTests(results=dict(entry.get("results") or {}), problems=list(entry.get("problems") or []))
    for item in pending:
        parsed.add_reported(resolver, classname=str(item.get("classname") or ""), name=str(item.get("name") or ""),
                            file=str(item.get("file") or ""), outcome=str(item.get("outcome") or ""),
                            message=str(item.get("message") or ""), collection=item.get("scope") == "collection")
    rest = {key: value for key, value in entry.items() if key not in ("results", "unresolved", "problems")}
    return {**rest, **parsed.fields()}


def recorded_runs(run: WorkflowRun, extra_ids: list[str] | tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """The run's recorded test runs, oldest first, each resolved with everything the run knows now."""
    runs = [dict(item) for item in dict(dict(run.context or {}).get("tests") or {}).get("runs") or []]
    if not any(item.get("unresolved") for item in runs):
        return runs
    resolver = resolver_for(run, extra_ids)
    return [resolve_entry(item, resolver) for item in runs]


def canonical_ids(raw: list[str], resolver: Resolver) -> tuple[list[str], list[str]]:
    """Submitted test ids as canonical selectors (``(ids, problems)``); one that cannot be is the submitter's to
    fix, so it is refused with the reason, never stored as given."""
    ids: list[str] = []
    problems: list[str] = []
    for item in raw:
        test_id, why = resolver.selector(item)
        if test_id:
            ids.append(test_id)
        else:
            problems.append(why)
    return list(dict.fromkeys(ids)), problems


__all__ = ["canonical_ids", "hint_files", "recorded_runs", "resolve_entry", "resolver_for"]
