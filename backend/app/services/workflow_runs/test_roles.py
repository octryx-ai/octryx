"""The role of every test in a test contract: ``new`` or ``regression``."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.services.workflow_checks.test_output import ERROR, FAILED, PASSED

from ..workflow_checks.test_results import confirmed_outcomes

ROLE_NEW, ROLE_REGRESSION = "new", "regression"
ROLES = (ROLE_NEW, ROLE_REGRESSION)
ROLES_KEY = "test_roles"
SEEN_PASSING, SEEN_FAILING = "passing", "failing"


def parse_tests(raw: Any, *, limit: int = 30, chars: int = 300) -> tuple[list[str], dict[str, str], list[str]]:
    ids: list[str] = []
    roles: dict[str, str] = {}
    problems: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        test_id = str((item.get("id") if isinstance(item, Mapping) else item) or "").strip()[:chars]
        if not test_id:
            continue
        ids.append(test_id)
        role = str(item.get("role") or "").strip().lower() if isinstance(item, Mapping) else ""
        if role and role not in ROLES:
            problems.append(f"{test_id}: role is new or regression, not '{role[:40]}'")
        elif role:
            roles[test_id] = role
    return list(dict.fromkeys(ids))[:limit], roles, problems


def observed(runs: Iterable[Mapping[str, Any]], test_id: str) -> str | None:
    for run in reversed(list(runs)):
        outcomes = confirmed_outcomes(run, [test_id])[test_id]
        if not outcomes:
            continue
        if any(value.get("outcome") in (FAILED, ERROR) for value in outcomes):
            return SEEN_FAILING
        return SEEN_PASSING if all(value.get("outcome") == PASSED for value in outcomes) else None
    return None


def conflict(test_id: str, role: str, seen: str | None) -> str | None:
    if role == ROLE_NEW and seen == SEEN_PASSING:
        return (f"{test_id} is marked new but already passes on the branch: a new test must fail before the change "
                "(an existing test that must keep passing is a regression test)")
    if role == ROLE_REGRESSION and seen == SEEN_FAILING:
        return f"{test_id} is marked regression but fails on the branch: a regression test must pass before the change"
    return None


def resolve_contract(record: dict[str, Any], runs: list[Mapping[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    problems: list[str] = []
    chosen: dict[str, str] = {}
    criteria = []
    for criterion in record.get("criteria") or []:
        criterion = dict(criterion)
        if criterion.get("manual_only"):
            criteria.append(criterion)
            continue
        declared = dict(criterion.get(ROLES_KEY) or {})
        roles: dict[str, str] = {}
        for test_id in criterion.get("tests") or []:
            seen = observed(runs, test_id)
            role = declared.get(test_id) or (ROLE_REGRESSION if seen == SEEN_PASSING else ROLE_NEW)
            if (why := conflict(test_id, role, seen)) is not None:
                problems.append(why)
            if chosen.setdefault(test_id, role) != role:
                problems.append(f"{test_id}: one test has one role in the contract (new in one criterion, "
                                "regression in another)")
            roles[test_id] = role
        criterion[ROLES_KEY] = roles
        criteria.append(criterion)
    return {**record, "criteria": criteria}, list(dict.fromkeys(problems))


def contract_roles(criteria: Iterable[Any], test_ids: Iterable[str]) -> dict[str, str]:
    roles: dict[str, str] = {}
    for criterion in criteria:
        if isinstance(criterion, Mapping):
            roles.update({str(key): str(value) for key, value in dict(criterion.get(ROLES_KEY) or {}).items()
                          if value in ROLES})
    return {test_id: roles.get(test_id, ROLE_NEW) for test_id in test_ids}


def role_conflicts(roles: Mapping[str, str], runs: list[Mapping[str, Any]]) -> list[str]:
    return [why for test_id, role in roles.items() if (why := conflict(test_id, role, observed(runs, test_id)))]


__all__ = ["ROLES", "ROLES_KEY", "ROLE_NEW", "ROLE_REGRESSION", "conflict", "contract_roles", "observed",
           "parse_tests", "resolve_contract", "role_conflicts"]
