"""A seat call's API equivalent: what it would cost through the API at list price, recorded at the
call, shown per person and per run apart from the real API cost, and never added to it."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import Project, Session, UsageEvent, User, UserProject, WorkflowRun, WorkflowRunSession
from app.services.auth import create_access_token
from app.services.budget.api_equivalent import api_equivalent_usd
from app.services.observability import agent_metrics
from app.services.operations.costs import run_cost_split
from app.services.workflow_runs.octryx import model_guard
from app.time_utils import utc_now

NOW = utc_now()


def uid() -> str:
    return str(uuid.uuid4())


def test_the_equivalent_is_the_official_list_price_per_call_and_tier():
    # Sonnet 5.5: input $2, cache read $0.10, 5-minute write $2.50, 1-hour write $4, output $10 per million.
    sonnet = {"input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 2_000_000,
              "cache_creation": {"ephemeral_1h_input_tokens": 1_000_000}, "output_tokens": 1_000_000}
    assert api_equivalent_usd("claude-sonnet-5-5", sonnet) == Decimal("2") + Decimal("0.1") + Decimal("2.5") \
        + Decimal("4") + Decimal("10")
    # Haiku 5.5 is priced higher above a 100k-token prompt, per call.
    assert api_equivalent_usd("claude-haiku-5-5", {"input_tokens": 100_000, "output_tokens": 0}) == Decimal("0.01")
    assert api_equivalent_usd("claude-haiku-5-5", {"input_tokens": 100_001, "output_tokens": 0}) == \
        Decimal("100001") * Decimal("0.5") / Decimal("1000000")
    # GPT-6.1 Sol above 272k prompt tokens (cached input counts to the prompt).
    long = {"input_tokens": 100_000, "cache_read_input_tokens": 200_000, "output_tokens": 0}
    assert api_equivalent_usd("gpt-6.1-sol", long) == (Decimal("100000") * 4 + Decimal("200000") * Decimal("0.2")) \
        / Decimal("1000000")
    # No list price: no value, never a similar model's price.
    assert api_equivalent_usd("gpt-7-nova", {"input_tokens": 10}) is None


def test_the_run_budget_counts_seat_calls_at_the_same_list_price():
    assert model_guard.list_cost("claude-sonnet-5-5", tokens_in=0, tokens_out=0, cache_read=1_000_000) == \
        pytest.approx(0.1)  # 0.05x input (official), was 0.1x in the guard's own table
    assert model_guard.list_cost("gpt-6.1-terra", tokens_in=200_000, tokens_out=0) == pytest.approx(0.2)  # was $2/M
    assert model_guard.list_cost("gpt-6.1-terra", tokens_in=300_000, tokens_out=0) == pytest.approx(0.6)  # > 272k


async def _person(db, name: str) -> User:
    person = User(id=uid(), username=f"{name}-{uid()[:6]}", email=f"{uid()}@example.test", password_hash="!")
    db.add(person)
    await db.flush()
    return person


async def _session(db, person: User, project: Project) -> Session:
    session = Session(id=uid(), user_id=person.id, project_id=project.id, agent_type="diagnosis", status="active",
                      metadata_={})
    db.add(session)
    await db.flush()
    return session


def _seat_call(session: Session, person: User, model: str, list_cost, provider: str = "anthropic_seat"):
    return UsageEvent(id=uid(), session_id=session.id, user_id=person.id, provider=provider, model=model,
                      tokens_in=1, tokens_out=1, cost=0, list_cost=list_cost, cost_source="seat_subscription",
                      created_at=NOW - timedelta(hours=1))


@pytest.mark.asyncio
async def test_a_run_shows_its_api_cost_and_apart_from_it_the_seat_equivalent(db):
    project = Project(id=uid(), name="Coffee", is_active=True, config={})
    db.add(project)
    await db.flush()
    person = await _person(db, "dev")
    run = WorkflowRun(id=uid(), project_id=project.id, workflow_kind="phased", workflow_key="team-delivery",
                      title="t", status="running", requested_by=person.id)
    db.add(run)
    gateway, governed = await _session(db, person, project), await _session(db, person, project)
    db.add_all([WorkflowRunSession(run_id=run.id, session_id=gateway.id, role="child"),
                WorkflowRunSession(run_id=run.id, session_id=governed.id, role="main"),
                _seat_call(gateway, person, "claude-sonnet-5-5", Decimal("1.25")),
                _seat_call(gateway, person, "gpt-7-nova", None, provider="openai_codex_seat"),
                UsageEvent(id=uid(), session_id=governed.id, user_id=person.id, provider="bedrock", model="m",
                           tokens_in=1, tokens_out=1, cost=Decimal("0.5"))])
    await db.flush()
    cost = (await run_cost_split(db, [run.id]))[run.id]
    assert (cost.api_usd, cost.seat_api_equivalent_usd, cost.seat_unpriced_calls) == (0.5, 1.25, 1)


@pytest.mark.asyncio
async def test_seat_usage_per_person_with_seat_accounts_models_and_workspaces(client, db):
    project = Project(id=uid(), name="Coffee", is_active=True, config={})
    db.add(project)
    await db.flush()
    person = await _person(db, "dev")
    lead = await _person(db, "lead")
    db.add(UserProject(user_id=lead.id, project_id=project.id, role="admin"))
    session = await _session(db, person, project)
    db.add_all([_seat_call(session, person, "claude-sonnet-5-5", Decimal("2.0")),
                _seat_call(session, person, "claude-haiku-5-5", Decimal("0.5")),
                _seat_call(session, person, "gpt-7-nova", None, provider="openai_codex_seat"),
                UsageEvent(id=uid(), session_id=session.id, user_id=person.id, provider="bedrock", model="m",
                           tokens_in=1, tokens_out=1, cost=Decimal("0.75"), created_at=NOW - timedelta(hours=1))])
    await db.commit()
    body = (await client.get("/api/v1/admin/operations/seat-usage",
                             params={"workspace_id": project.id, "days": 7},
                             headers={"Authorization": f"Bearer {create_access_token(lead.id)}"})).json()
    [row] = body["people"]
    assert row["display_name"] == person.username  # no display name set: the username
    assert (row["user_id"], row["api_equivalent_usd"], row["api_cost_usd"], row["seat_calls"], row["unpriced_calls"]) \
        == (person.id, 2.5, 0.75, 3, 1)
    assert body["labels"] == {"api_equivalent_usd": "would cost via API (list price)",
                              "unpriced_calls": "no list price (seat only)"}
    claude = next(seat for seat in row["seats"] if seat["provider"] == "anthropic_seat")
    assert (claude["label"], claude["api_equivalent_usd"], claude["calls"]) == ("Claude", 2.5, 2)
    assert [model["model"] for model in claude["models"]] == ["claude-sonnet-5-5", "claude-haiku-5-5"]
    assert claude["seat"] == agent_metrics.seat_pseudonym(person.id, "anthropic_seat")  # never a name
    assert row["workspaces"] == [{"workspace_id": project.id, "name": "Coffee", "api_equivalent_usd": 2.5,
                                  "api_cost_usd": 0.75}]


@pytest.mark.asyncio
async def test_a_seat_call_counts_its_equivalent_in_the_metric_never_in_the_cost(db):
    project = Project(id=uid(), name="Coffee", is_active=True, config={})
    db.add(project)
    await db.flush()
    person = await _person(db, "dev")
    session = await _session(db, person, project)
    seat = agent_metrics.seat_pseudonym(person.id, "anthropic_seat")
    line = f'octryx_seat_usage_list_usd_total{{seat="{seat}",provider="anthropic_seat",model="claude-sonnet-5-5"}} '
    assert not [row for row in agent_metrics.SEAT_USAGE_LIST_USD.render() if row.startswith(line)]
    db.add(_seat_call(session, person, "claude-sonnet-5-5", Decimal("1.5")))
    await db.commit()
    assert [float(row.rsplit(" ", 1)[1]) for row in agent_metrics.SEAT_USAGE_LIST_USD.render()
            if row.startswith(line)] == [1.5]
    cost = [row for row in agent_metrics.LLM_COST.render() if 'provider="anthropic_seat"' in row
            and 'model="claude-sonnet-5-5"' in row]
    assert all(float(row.rsplit(" ", 1)[1]) == 0 for row in cost)  # never in the cost
