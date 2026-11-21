"""A policy denial is no connector failure: repository-policy denials never open the connection's breaker and
block the next, allowed status post."""

from __future__ import annotations

import pytest

import app.tools.registry as registry_module
from app.models import CircuitBreakerState
from app.services import circuit_breaker as circuit_breaker_package
from app.services.circuit_breaker.outcome import FAILURE, IGNORED, SUCCESS, breaker_outcome
from tests.test_connector_breaker_scope import _context, _workspace

POLICY = ("Repository operation 'push' is denied by project repository policy: operation is disabled by the "
          "configured repository policy")


@pytest.mark.parametrize(("result", "outcome"), [
    ({"error": POLICY}, IGNORED),
    ({"error": "blocked", "error_category": "denied_by_policy"}, IGNORED),
    ({"error": "blocked", "policy": "mcp_access_policy"}, IGNORED),
    ({"error": "GitHub API returned 404 Not Found"}, IGNORED),
    ({"error": "forbidden", "status_code": 403}, IGNORED),
    ({"error": "repository is required and must be allowed"}, IGNORED),
    ({"error": "GitHub API returned 502 Bad Gateway"}, FAILURE),
    ({"error": "rate limited", "status_code": 429}, FAILURE),
    ({"error": "Request timed out after 30s"}, FAILURE),
    ({"error": "connection refused"}, FAILURE),
    ({"error": "tool_error"}, FAILURE),
    ({"ok": True}, SUCCESS),
])
def test_only_a_connector_error_counts(result, outcome):
    assert breaker_outcome(result) == outcome


@pytest.mark.asyncio
async def test_policy_denials_never_open_the_breaker_and_a_real_error_still_does(db, monkeypatch):
    project = await _workspace(db)
    answers = []

    async def dispatched(_tool_name, _params, _context):
        return answers.pop(0)

    monkeypatch.setattr(registry_module, "_dispatch_registered_tool", dispatched)
    threshold = circuit_breaker_package.CIRCUIT_BREAKER_FAILURE_THRESHOLD
    answers += [{"error": POLICY}] * (threshold + 2) + [{"issues": []}]
    for _ in range(threshold + 2):
        await registry_module.execute_tool_with_plugins("search_jira_tickets", {}, _context(db, project.id))
    allowed = await registry_module.execute_tool_with_plugins("search_jira_tickets", {}, _context(db, project.id))
    assert "error" not in allowed and allowed.get("circuit_breaker_state") is None
    state = await db.get(CircuitBreakerState, "jira@platform")
    assert state is None or state.state == "closed"

    answers += [{"error": "Jira API returned 503 Service Unavailable"}] * threshold
    for _ in range(threshold):
        await registry_module.execute_tool_with_plugins("search_jira_tickets", {}, _context(db, project.id))
    await db.commit()
    assert (await db.get(CircuitBreakerState, "jira@platform")).state == "open"
