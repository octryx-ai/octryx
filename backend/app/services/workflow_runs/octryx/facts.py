"""What the octryx-claude launcher reports from the device's working copy."""

from __future__ import annotations

import copy
import re
from typing import Any

from ....models import WorkflowRun
from ....time_utils import utc_now

FACTS_KEY = "workflow_run_facts"
# A guard against a runaway, never a cut of a real story: screenshot baselines can make a patch tens of MB.
MAX_PATCH = 64_000_000
MISSING = "missing"
MAX_TEST_TEXT = 200_000
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _program(text: Any, file: str, digest: str) -> str | None:
    # A text that does not match its digest proves nothing.
    from hashlib import sha256

    from .format_only import program_fingerprint

    if not isinstance(text, str) or len(text) > MAX_TEST_TEXT:
        return None
    if "sha256:" + sha256(text.encode("utf-8")).hexdigest() != digest:
        return None
    return program_fingerprint(text, file)


def _current_pass(run: WorkflowRun, facts: dict[str, Any]) -> bool:
    state = dict(run.node_state or {})
    return (bool(run.current_node_id) and facts.get("node_id") == run.current_node_id
            and facts.get("entry") is not None and facts.get("entry") == state.get("entry"))


def _apply(run: WorkflowRun, facts: Any) -> dict[str, Any] | None:
    if not isinstance(facts, dict) or not _current_pass(run, facts):
        return None
    context = copy.deepcopy(dict(run.context or {}))
    files = {key: dict(value) for key, value in dict(context.get("confirmed_test_files") or {}).items()
             if isinstance(value, dict)}
    digests = facts.get("confirmed_test_digests") if isinstance(facts.get("confirmed_test_digests"), dict) else {}
    checked = {str(name) for name in facts.get("checked_files") or [] if isinstance(name, str)}
    texts = facts.get("confirmed_test_texts") if isinstance(facts.get("confirmed_test_texts"), dict) else {}
    for entry in files.values():
        if not entry.get("device"):
            continue
        reported = digests.get(entry.get("file"))
        if isinstance(reported, str) and _DIGEST.match(reported):
            program = _program(texts.get(entry.get("file")), str(entry.get("file") or ""), reported)
            if "device_sha256" not in entry:
                entry["device_sha256"] = reported
                entry["device_program"] = program
            entry["device_latest"] = reported
            entry["device_program_latest"] = program
        elif entry.get("device_sha256") and entry.get("file") in checked:
            entry["device_latest"] = MISSING  # checked and gone: a deleted confirmed test is drift
    context["confirmed_test_files"] = files
    change = facts.get("change")
    if isinstance(change, dict):
        base = str(change.get("base") or "")
        patch = change.get("patch") if isinstance(change.get("patch"), str) else ""
        unavailable = bool(change.get("base_unavailable")) or base != str(context.get("base_sha") or "")
        context["device_change"] = {
            "node_id": run.current_node_id, "entry": facts.get("entry"), "base": base,
            # The device's own ``truncated`` counts: a patch it cut at exactly the bound is no whole change.
            "patch": "" if unavailable else patch[:MAX_PATCH],
            "truncated": change.get("truncated") is True or len(patch) > MAX_PATCH,
            "base_unavailable": unavailable, "at": utc_now().isoformat(),
            # Why there is no change, from the device (the git step and its words) or the base it named; without
            # it nobody can tell afterwards.
            **({"reason": str(change.get("reason") or "")[:300] or f"the device diffed against {base or 'no base'}, "
                f"the run's base is {context.get('base_sha') or 'unknown'}"} if unavailable else {}),
            **({"attempts": int(change["attempts"])} if isinstance(change.get("attempts"), int) else {})}
    if context == dict(run.context or {}):
        return None
    return context


def _from_item(session: Any) -> bool:
    # An item's facts are its worktree's, never the run's.
    from ..teamwork import item_marker

    marker = item_marker(session) if session is not None else None
    return marker is not None and not marker.get("sequential")  # a sequential item works in the main folder


def facts_change(run: WorkflowRun, facts: Any, *, session: Any = None) -> bool:
    return not _from_item(session) and _apply(run, facts) is not None


def record_facts(run: WorkflowRun, facts: Any, *, session: Any = None) -> bool:
    if _from_item(session):
        return False
    applied = _apply(run, facts)
    if applied is None:
        return False
    run.context = applied
    if isinstance(facts, dict) and isinstance(facts.get("change"), dict):
        from ...observability.device_report_metrics import device_change_reported

        device_change_reported({**dict(applied.get("device_change") or {}),
                                **{key: facts["change"][key] for key in ("attempts",) if key in facts["change"]}})
    return True


__all__ = ["FACTS_KEY", "MAX_PATCH", "MISSING", "facts_change", "record_facts"]
