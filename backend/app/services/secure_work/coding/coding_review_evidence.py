"""Reviewer approval gate from explicit review decisions only.

Requirements (fail closed):
- the latest Change Plan must exist; each active Change Unit is one review scope (the whole Work
  Item when it has no active units), and a unit's required reviewers are its
  ``reviewer_policy.required_reviewers`` or else ``default_reviewers`` (as the plan producer uses);
- every ``code_review`` requirement on the latest plan must map to an active unit of the same
  repository, and its named reviewers are required too; an unmatched or malformed requirement keeps
  the gate open.

Eligible decisions carry the server-owned record (``review_decision_record``, see
``review_decision_record.py``) whose actor, decision, plan id and version, scope and unit update
marker match the event and the current state. Feedback without a decision, prose, free status,
overrides and PR approvals never approve. Per actor and scope the latest eligible decision counts; a timestamp tie
keeps all tied decisions so a negative one wins. A named reviewer is satisfied only by exactly one
authenticated user (by username, e-mail, display name or a linked account of that user); a name
that resolves to several users is ambiguous and not satisfied.

Limit: decisions are bound to the plan version and the Change Unit, not to a pull-request head
commit; the runtime keeps no trustworthy PR head. A pass is not merge readiness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User
from ..review_decision_record import (
    DECISION_EVENT_TYPE,
    DECISION_RECORD_KEY,
    DECISION_RECORD_SCHEMA,
    REVIEW_DECISIONS,
    SCOPE_CHANGE_UNIT,
    SCOPE_WORK_ITEM,
    unit_update_marker,
)
from ..reviewers import user_aliases, users_named

NEGATIVE_DECISIONS = frozenset({"changes_requested", "rejected"})
HEAD_BINDING_LIMIT = (
    "Decisions are bound to the plan version and Change Unit, not to a pull-request head commit; "
    "this is not merge readiness."
)


@dataclass
class ReviewerIdentities:
    """Authenticated identity aliases: lower-cased name or email -> the user ids it names."""

    aliases: dict[str, set[str]] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)

    def add(self, alias: Any, user_id: str) -> None:
        if isinstance(alias, str) and alias.strip():
            self.aliases.setdefault(alias.strip().lower(), set()).add(user_id)

    def resolve(self, name: str) -> set[str]:
        return self.aliases.get(name.strip().lower(), set())


def required_reviewer_names(bundle: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for unit in bundle["change_units"]:
        listed, _ = _unit_required_reviewers(unit)
        names.update(listed)
    plan = bundle["change_plans"][0] if bundle["change_plans"] else None
    for entry in (plan.required_approvals_json if plan and isinstance(plan.required_approvals_json, list) else []):
        if isinstance(entry, dict) and isinstance(entry.get("reviewers"), list):
            names.update(name for name in entry["reviewers"] if isinstance(name, str))
    return {name.strip().lower() for name in names if name.strip()}


async def load_reviewer_identities(db: AsyncSession, bundle: dict[str, Any]) -> ReviewerIdentities:
    """Two batched queries, independent of the number of events or reviewers."""
    return await load_reviewer_identities_for(db, [bundle])


async def load_reviewer_identities_for(db: AsyncSession, bundles: list[dict[str, Any]]) -> ReviewerIdentities:
    """The same two queries for several Work Items at once: actors of their review events and
    names their requirements use; the engineering-profile directory is read once."""
    actor_ids = {event.created_by for bundle in bundles for event in bundle["review_events"] if event.created_by}
    names = set().union(*(required_reviewer_names(bundle) for bundle in bundles)) if bundles else set()
    named = await users_named(db, names)
    user_ids = actor_ids | {user_id for ids in named.values() for user_id in ids}
    users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all() if user_ids else []
    identities = ReviewerIdentities()
    for user in users:
        identities.labels[user.id] = user.display_name or user.username or user.email or user.id
    for alias, ids in named.items():
        for user_id in ids:
            identities.add(alias, user_id)
    for user_id, aliases in (await user_aliases(db, actor_ids)).items():
        for alias in aliases:
            identities.add(alias, user_id)
    return identities


def _unit_required_reviewers(unit: Any) -> tuple[list[str], bool]:
    """(names, well_formed) from the unit policy: required_reviewers, else default_reviewers."""
    policy = unit.reviewer_policy_json if isinstance(unit.reviewer_policy_json, dict) else None
    if policy is None:
        return [], False
    for key in ("required_reviewers", "default_reviewers"):
        value = policy.get(key)
        if value in (None, []):
            continue
        if not isinstance(value, list) or not all(isinstance(name, str) and name.strip() for name in value):
            return [], False
        return [name.strip() for name in value], True
    return [], True


def _eligible_record(event: Any, plan: Any, scope_key: tuple[str, str | None], units: dict[str, Any]) -> dict | None:
    if event.event_type != DECISION_EVENT_TYPE or not isinstance(event.metadata_json, dict):
        return None
    record = event.metadata_json.get(DECISION_RECORD_KEY)
    if not isinstance(record, dict) or record.get("schema") != DECISION_RECORD_SCHEMA:
        return None
    decision = record.get("decision")
    if decision not in REVIEW_DECISIONS or decision != event.status or record.get("actor_id") != event.created_by:
        return None
    if record.get("change_plan_id") != plan.id or record.get("plan_version") != plan.version:
        return None
    scope, unit_id = scope_key
    if record.get("scope") != scope or record.get("change_unit_id") != unit_id or event.change_unit_id != unit_id:
        return None
    if scope == SCOPE_CHANGE_UNIT and record.get("change_unit_marker") != unit_update_marker(units[unit_id]):
        return None
    return record


def _current_decisions(events: list[Any]) -> list[Any]:
    """Latest decision per actor; a timestamp tie keeps every tied decision."""
    latest: dict[str, list[Any]] = {}
    for event in events:
        group = latest.get(event.created_by)
        if group is None or event.created_at > group[0].created_at:
            latest[event.created_by] = [event]
        elif event.created_at == group[0].created_at:
            group.append(event)
    return [event for group in latest.values() for event in group]


def evaluate_reviewer_gate(bundle: dict[str, Any], identities: ReviewerIdentities) -> dict[str, Any]:
    """Return {status, reason, evidence, approvers} for the reviewer_approval gate."""
    plan = bundle["change_plans"][0] if bundle["change_plans"] else None
    events = list(bundle["review_events"])
    overrides = len(bundle.get("reviewer_overrides") or [])
    base = {"limit": HEAD_BINDING_LIMIT, "overrides": overrides}
    if plan is None:
        return _result("missing", "No Change Plan, so no review requirement is known.", base, events)
    units = {unit.id: unit for unit in bundle["change_units"]}
    scopes: list[dict[str, Any]] = []
    open_reasons: list[str] = []
    for unit in units.values():
        names, well_formed = _unit_required_reviewers(unit)
        scopes.append({"key": (SCOPE_CHANGE_UNIT, unit.id), "repository_name": unit.repository_name,
                       "required": names, "well_formed": well_formed})
    if not units:
        scopes.append({"key": (SCOPE_WORK_ITEM, None), "repository_name": None, "required": [], "well_formed": True})
    _apply_plan_requirements(plan, scopes, units, open_reasons)

    eligible_ids: set[str] = set()
    approvers: set[str] = set()
    scope_reports = []
    blocked = False
    all_pass = not open_reasons
    for scope in scopes:
        scoped = [event for event in events if _eligible_record(event, plan, scope["key"], units)]
        eligible_ids.update(event.id for event in scoped)
        current = _current_decisions(scoped)
        negative = [event for event in current if event.status in NEGATIVE_DECISIONS]
        approving = {event.created_by for event in current if event.status == "approved"}
        approving -= {event.created_by for event in negative}
        missing, ambiguous = [], []
        for name in scope["required"]:
            users = identities.resolve(name)
            if len(users) > 1:
                ambiguous.append(name)
            elif not users or not users <= approving:
                missing.append(name)
        satisfied = (
            scope["well_formed"] and not negative and not missing and not ambiguous
            and (bool(scope["required"]) or bool(approving))
        )
        blocked = blocked or bool(negative)
        all_pass = all_pass and satisfied
        if satisfied:
            approvers.update(approving)
        scope_reports.append({
            "scope": scope["key"][0],
            "change_unit_id": scope["key"][1],
            "repository_name": scope["repository_name"],
            "required_reviewers": scope["required"],
            "requirement_readable": scope["well_formed"],
            "missing_reviewers": missing,
            "ambiguous_reviewers": ambiguous,
            "current_decisions": [
                {"reviewer": identities.labels.get(event.created_by, event.created_by), "decision": event.status,
                 "created_at": event.created_at.isoformat() if event.created_at else None}
                for event in current
            ],
            "satisfied": satisfied,
        })
    evidence = {**base, "plan_id": plan.id, "plan_version": plan.version, "scopes": scope_reports,
                "requirement_gaps": open_reasons, "activity_count": len(events) - len(eligible_ids)}
    labels = sorted(identities.labels.get(user_id, user_id) for user_id in approvers)
    if blocked:
        return _result("block", f"A current review decision on plan v{plan.version} requests changes or rejects.",
                       evidence, events, labels)
    if all_pass:
        return _result("pass", f"Every required review of plan v{plan.version} is approved. {HEAD_BINDING_LIMIT}",
                       evidence, events, labels)
    if eligible_ids or events or overrides:
        return _result("review_required", _open_reason(plan, scope_reports, open_reasons), evidence, events, labels)
    return _result("missing", f"No review decision is recorded for plan v{plan.version}.", evidence, events, labels)


def _apply_plan_requirements(plan: Any, scopes: list[dict], units: dict[str, Any], gaps: list[str]) -> None:
    """Explicit code_review requirements on the latest plan are kept, never silently dropped.

    A requirement applies to every active unit of its repository. An unreadable container or entry
    (not a list, not an object, no type) is a gap that keeps the gate open, not "no requirements"."""
    raw = plan.required_approvals_json
    if raw is None:
        return
    if not isinstance(raw, list):
        gaps.append("The plan's approval requirements are not readable.")
        return
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("type"), str):
            gaps.append("An approval requirement on the plan is not readable.")
            continue
        if entry["type"] != "code_review" or entry.get("required") is False:
            continue
        repository = entry.get("repository_name")
        reviewers = entry.get("reviewers", [])
        if not isinstance(repository, str) or not repository.strip() or not isinstance(reviewers, list):
            gaps.append("A code review requirement on the plan is not readable.")
            continue
        matching = [scope for scope in scopes if scope["repository_name"] == repository.strip()]
        if not matching:
            gaps.append(f"The plan requires a code review for {repository.strip()}, but no active Change Unit matches.")
            continue
        for scope in matching:
            for name in reviewers:
                if not isinstance(name, str) or not name.strip():
                    scope["well_formed"] = False
                elif name.strip() not in scope["required"]:
                    scope["required"].append(name.strip())


def _open_reason(plan: Any, scopes: list[dict], gaps: list[str]) -> str:
    if gaps:
        return gaps[0]
    for scope in scopes:
        subject = scope["repository_name"] or "the Work Item"
        if not scope["requirement_readable"]:
            return f"The reviewer requirement for {subject} is not readable."
        if scope["ambiguous_reviewers"]:
            return f"{scope['ambiguous_reviewers'][0]} names more than one user for {subject}."
        if scope["missing_reviewers"]:
            return f"{scope['missing_reviewers'][0]} has no current approval of plan v{plan.version} for {subject}."
        if not scope["satisfied"]:
            return f"No current approval of plan v{plan.version} for {subject}."
    return f"Review of plan v{plan.version} is not complete."


def _result(status: str, reason: str, evidence: dict, events: list, approvers: list[str] | None = None) -> dict:
    evidence = {**evidence, "activity_count": evidence.get("activity_count", len(events))}
    return {"status": status, "reason": reason, "evidence": evidence, "approvers": approvers or []}
