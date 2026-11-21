"""Where a run's tokens went, to see where tokens could be saved: the split by category, the top consumers and the
savings rules from data, the run's Tokens view and the Prometheus counters at the event.

The shapes follow a real run: the run contract read 38× at 4 KB and more each, `flutter test`
run again and again, the same file read 9×.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import (
    DeviceJob,
    DeviceJobEvent,
    Project,
    Session,
    User,
    UserDevice,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunSession,
)
from app.services.devices.job_events import apply_event
from app.services.observability import agent_metrics
from app.services.observability.token_profile import metrics
from app.services.observability.token_profile.assemble import PROFILE_KIND, SUBAGENT_LABEL, TurnFacts
from app.services.observability.token_profile.read_model import profile_of
from app.services.observability.token_profile.rules import hints
from app.services.observability.token_profile.split import Call, ToolResult, Turn, fixed_start, split_turn
from app.time_utils import utc_now
from tests.policy_engine_support import bearer

STATUS = "mcp__octryx-knowledge__workflow_run_status"
NOW = utc_now()


def _measured(**extra) -> Turn:
    # Call 0 asks for a 40 KB result (10,000 tokens); calls 1 and 2 carry it; the session compacts before call 3.
    calls = [Call(5, 0, 30_000, 100), Call(2, 30_000, 10_500, 50), Call(1, 40_500, 500, 20), Call(1, 32_000, 0, 10),
             Call(3, 0, 0, 7, subagent=True)]
    tools = [ToolResult("Bash", 40_000, call=0, key="Bash\nd1", label="flutter test")]
    return Turn("dj_1", "t1", node_id="Reproduce", measured=True, calls=calls, tools=tools, compactions=[3],
                prompt_chars=4_000, **extra)


def test_a_tool_result_costs_its_size_in_every_later_call_until_the_compaction():
    turn = _measured()
    fixed = fixed_start([turn])
    assert fixed == 30_005 - 1_000  # the first call minus the prompt: system prompt and tool definitions
    split = split_turn(turn, fixed)
    assert split.carried == [20_000]  # calls 1 and 2, not call 0 (it asked) nor call 3 (after the compaction)
    assert split.by_tool == {"Bash": 20_000}
    assert split.categories["prompt"] == 4 * 1_000
    assert split.categories["subagents"] == 3 and split.categories["output"] == 187
    main_input = sum(call.total_input for call in turn.main_calls)
    assert sum(value for name, value in split.categories.items() if name not in ("subagents", "output")) == main_input
    assert split.cache == {"read": 102_500, "write": 41_000, "uncached": 12, "output": 187}


def test_parts_never_exceed_the_measured_input_and_runs_before_the_profile_are_estimates():
    tight = split_turn(Turn("dj", "t", measured=True, calls=[Call(0, 0, 100, 0), Call(0, 100, 0, 0)],
                            tools=[ToolResult("Read", 40_000, call=0)]), fixed=60)
    assert tight.carried == [40]  # scaled into the 100 tokens of call 1, after the fixed start
    assert tight.categories["history"] == 40  # call 0: nothing carried yet
    old = Turn("dj", "t", usage=Call(10, 50_000, 5_000, 300), first_context=2_000,
               tools=[ToolResult("Bash", 4_000, call=0, clipped=True), ToolResult("Read", 400, call=1)])
    split = split_turn(old)
    assert split.calls == 3 and split.carried == [2_000, 100]
    assert split.categories["system_and_tools"] == 6_000 and split.categories["prompt"] == 0
    assert split.categories["history"] == 55_010 - 6_000 - 2_100


def test_the_cache_hit_rate_is_the_read_share_of_the_input_per_phase_and_run():
    """Prompt debt: first measure how much of a run's input comes from the prompt cache."""
    from app.services.observability.token_profile.split import hit_rate

    assert hit_rate({"read": 90, "write": 5, "uncached": 5, "output": 1_000}) == 0.9  # output is no input
    assert hit_rate({"read": 0, "write": 0, "uncached": 0, "output": 7}) is None
    profile = profile_of([_measured()])
    cache = profile["totals"]
    assert cache["cache_hit_rate"] == round(cache["read"] / cache["input"], 4)
    assert profile["phases"][0]["cache_hit_rate"] == cache["cache_hit_rate"]  # one phase: the run's rate


def _oe72_like() -> list[Turn]:
    status = [ToolResult(STATUS, 4_000, call=index, key=f"{STATUS}\n{{}}", label="{}", clipped=True)
              for index in range(4)]
    reads = [ToolResult("Read", 2_000, call=4 + index, key=f"Read\n/repo/lib/form.dart {index}",
                        path_key="/repo/lib/form.dart", label="/repo/lib/form.dart") for index in range(3)]
    return [Turn("dj_1", "t1", node_id="Reproduce", usage=Call(10, 400_000, 20_000, 900), first_context=10_000,
                 tools=status + reads), _measured()]


def test_consumers_and_hints_come_from_the_rules_data():
    payload = profile_of(_oe72_like())
    assert payload["basis"] == "mixed"
    labels = [row["label"] for row in payload["consumers"]]
    assert labels[0] == "workflow_run_status {}" and "Bash flutter test" in labels
    status = payload["consumers"][0]
    assert (status["count"], status["max_kb"], status["at_least"], status["estimated"]) == (4, 4, True, True)
    rules = {hint["rule"] for hint in payload["hints"]}
    assert {"contract_reread", "same_file_read", "large_tool_result"} <= rules
    same_file = next(hint for hint in payload["hints"] if hint["rule"] == "same_file_read")
    assert same_file["text"].startswith("Read /repo/lib/form.dart was read 3×")
    phase = payload["phases"][0]
    assert phase["phase"] == "Reproduce" and phase["turns"] == 2 and phase["basis"] == "mixed"
    # A threshold is data: the same facts under another rule set give other hints.
    stricter = [{"id": "x", "scope": "group", "match": {"tool": ["Read"]}, "when": {"count": {">=": 2}},
                 "text": "{label} {count}× {unknown}"},
                {"id": "y", "scope": "group", "match": {"tool": ["Read"]}, "when": {"count": {">": 50}}, "text": "-"}]
    assert hints([(turn, split_turn(turn)) for turn in _oe72_like()], stricter) == []  # unknown fact: no broken line


def uid() -> str:
    return str(uuid.uuid4())


async def _run_with_turns(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=uid(), name=f"Tokens {uid()[:6]}", is_active=True, config={})
    device = UserDevice(owner_user_id=admin.id, name="Mac", name_key=f"mac-{uid()[:6]}", os="macos", public_key="k",
                        last_seen_at=NOW)
    run = WorkflowRun(id=uid(), project_id=project.id, workflow_kind="phased", workflow_key="bug-fix-reproduction",
                      title="OCX-72", status="running", requested_by=admin.id, current_node_id="reproduce",
                      context={"size_class": {"class": "M", "initial": "S"}})
    session = Session(id=uid(), user_id=admin.id, agent_type="diagnosis", status="active", metadata_={})
    db.add_all([project, device, run, session])
    await db.flush()
    job = DeviceJob(device_id=device.id, owner_user_id=admin.id, session_id=session.id, folder="/repo",
                    profile="seat", status="running", turn_id="t2")
    db.add_all([job, WorkflowRunSession(run_id=run.id, session_id=session.id, role="octryx", runtime="octryx_claude")])
    await db.flush()
    db.add(WorkflowRunEvent(run_id=run.id, kind="device_continuation_started", node_id="reproduce",
                            detail={"job_id": job.id}, created_at=NOW - timedelta(minutes=10)))
    bodies = [("job_event", {"turn_id": "t1", "kind": "context", "tokens": 10_000})]
    for index in range(3):  # a turn without a token profile: the stored results only
        bodies += [("job_event", {"turn_id": "t1", "kind": "tool_use", "tool": STATUS, "tool_use_id": f"s{index}",
                                  "input_preview": "{}"}),
                   ("job_event", {"turn_id": "t1", "kind": "tool_result", "tool_use_id": f"s{index}",
                                  "output": "x" * 4_000 + "…"})]
    bodies += [("turn_finished", {"turn_id": "t1", "usage": {"input_tokens": 9, "cache_read_input_tokens": 90_000,
                                                             "cache_creation_input_tokens": 9_000}}),
               ("job_event", {"turn_id": "t2", "kind": "tool_use", "tool": "Bash", "tool_use_id": "b1",
                              "input_preview": "flutter test"}),
               ("job_event", {"turn_id": "t2", "kind": "token_profile", "part": 0, "parts": 1, "prompt_chars": 400,
                              "compactions": [], "calls": [[5, 0, 30_000, 100, 0], [2, 30_000, 20_000, 50, 0]],
                              "tools": [["b1", "Bash", 69_000, "d1", "", 0, 0]]}),
               # A turn that reported no tool events, only its usage, still counts.
               ("job_accepted", {"turn_id": "t3"}),
               ("turn_finished", {"turn_id": "t3", "usage": {"input_tokens": 1, "cache_read_input_tokens": 700_000}})]
    for seq, (kind, body) in enumerate(bodies, start=1):
        db.add(DeviceJobEvent(job_id=job.id, seq=seq, type=kind, body=body,
                              created_at=NOW - timedelta(minutes=5) + timedelta(seconds=seq)))
    await db.flush()
    return run, job


@pytest.mark.asyncio
async def test_the_runs_tokens_view_reads_its_own_events_and_needs_read_access(client, db):
    run, _job = await _run_with_turns(db)
    outsider = User(id=uid(), username=f"out-{uid()[:6]}", email=f"{uid()[:6]}@example.com", password_hash="x",
                    is_active=True)
    db.add(outsider)
    await db.commit()
    admin_id = run.requested_by
    response = await client.get(f"/api/v1/workflow-runs/{run.id}/token-profile", headers=bearer(admin_id))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["basis"] == "mixed" and payload["ticket_key"] is None
    assert [(phase["phase"], phase["turns"]) for phase in payload["phases"]] == [("reproduce", 3)]
    assert payload["totals"]["read"] == 90_000 + 30_000 + 700_000
    assert payload["consumers"][0]["label"] == "Bash flutter test" and payload["consumers"][0]["max_kb"] == 68
    rules = {hint["rule"] for hint in payload["hints"]}
    assert {"contract_reread", "large_tool_result"} <= rules
    assert "long_history" not in rules  # 820K in a phase with estimated turns: the calls are a guess, no hint
    denied = await client.get(f"/api/v1/workflow-runs/{run.id}/token-profile", headers=bearer(outsider.id))
    assert denied.status_code in (403, 404)


@pytest.mark.asyncio
async def test_a_profile_is_counted_by_workflow_class_phase_and_category_when_it_arrives(db):
    agent_metrics.reset()
    run, job = await _run_with_turns(db)
    body = {"turn_id": "t2", "kind": "token_profile", "part": 0, "parts": 2, "prompt_chars": 400, "compactions": [],
            "calls": [[5, 0, 30_000, 100, 0], [2, 30_000, 20_000, 50, 0]], "tools": []}
    await apply_event(db, job, "job_event", body, limits={})
    await db.commit()
    assert not metrics.TOKENS.series  # the first of two parts: nothing counted yet
    await apply_event(db, job, "job_event", {"turn_id": "t2", "kind": "token_profile", "part": 1, "parts": 2,
                                             "calls": [], "tools": [["b1", "Bash", 69_000, "d1", "", 0, 0]]},
                      limits={})
    await db.commit()
    labels = {"workflow": "bug-fix-reproduction", "size_class": "S", "phase": "reproduce", "effort": "default"}
    tokens = {key[4:]: value for key, value in _series(metrics.TOKENS, labels).items()}
    # The fixed start is the first call minus the prompt (30,005 - 100); call 1 carries the 69 KB result whole.
    assert tokens[("tool_results", "Bash")] == 17_250 and tokens[("prompt", "none")] == 200
    assert _series(metrics.CACHE, labels)[(*labels.values(), "write")] == 50_000
    assert _series(metrics.CALLS, labels)[tuple(labels.values())] == 2  # tokens per call = sum / calls
    counts, total = metrics.HIT_RATIO.series[tuple(labels.values())]  # read 30,000 of 80,007 input tokens
    assert counts[-1] == 1 and total == 0.375 and counts[metrics.HIT_RATIO.buckets.index(0.25)] == 0
    assert run.current_node_id == "reproduce"  # the phase label is the run's phase when the profile arrived


def _series(metric, labels) -> dict:
    wanted = tuple(labels.values())
    return {key: value for key, value in metric.series.items() if tuple(key[:len(wanted)]) == wanted}


def test_a_subagents_tool_result_is_labelled_as_such_since_its_preview_never_arrives():
    facts = TurnFacts("job", "t1")
    facts.add({"kind": "tool_use", "tool": "Grep", "tool_use_id": "g1", "input_preview": "lib"})
    facts.add({"kind": PROFILE_KIND, "part": 0, "parts": 1, "prompt_chars": 0, "compactions": [],
               "calls": [[5, 0, 30_000, 100, 0], [2, 0, 9_000, 50, 1]],
               "tools": [["g1", "Grep", 4_000, "d1", "", 0, 0], ["s1", "Bash", 8_000, "d2", "", 1, 0]]})
    assert [tool.label for tool in facts.build().tools] == ["lib", SUBAGENT_LABEL]
