"""Team delivery: the coordinator splits a story into items built side by side by ``parallel_work``; pipeline, reviewer
and product owner close it. The seed's config keys asserted here are the interface its consumers read."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.runtime.secure_work import WorkItem
from app.services.flow_definitions import validate_flow_definition
from app.services.workflow_runs.graph import parse_phased_definition
from app.services.workflow_runs.graph_validation import validate_phased_definition
from tests.agent_definition_revision_fixtures import make_project
from tests.phased_workflow_fixtures import admin_user, phase_turn, publish_phased
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.teamwork_engine_support import fake, finish_item, item, items_of  # noqa: F401  (``fake`` is a fixture)

pytestmark = pytest.mark.usefixtures("scripted_pool")

SEEDS = Path(__file__).resolve().parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json"
ROLES = ("backend", "frontend", "test")


def _seed(key: str = "team-delivery") -> dict:
    return next(item for item in json.loads(SEEDS.read_text(encoding="utf-8")) if item["key"] == key)


def _forward_reachable(definition: dict) -> set[str]:
    forward: dict[str, list[str]] = {}
    for edge in definition["edges"]:
        if edge.get("kind") != "loop":
            forward.setdefault(edge["source_node_id"], []).append(edge["target_node_id"])
    seen, todo = set(), ["start"]
    while todo:
        node = todo.pop()
        if node not in seen:
            seen.add(node)
            todo.extend(forward.get(node, []))
    return seen


def test_v2_publishes_and_runs_plan_then_parallel_work_then_the_pipeline():
    definition = _seed()["definition"]
    assert validate_flow_definition(definition)["valid"] is True
    graph = parse_phased_definition(definition)
    routes = {(edge["source_node_id"], edge.get("when")): edge["target_node_id"] for edge in definition["edges"]}
    path, node = [], "start"
    for when in (None, "succeeded", "succeeded", None, "confirmed", "done", "succeeded", None, "confirmed",
                 "succeeded", "succeeded"):
        path.append(node)
        node = routes[(node, when)]
    assert [*path, node] == ["start", "branch", "prepare", "plan", "ready", "work", "pipeline", "independent_review",
                             "decisions", "push", "pr", "done"]
    assert [key for key, value in graph.nodes.items() if value.kind == "phase"] == ["plan"]
    plan = graph.nodes["plan"].config
    assert (plan["model_class"], plan["session"], plan["output"]) == ("plan", "epic", "work_plan")
    assert plan["workflow_contract"]["path_rules"] == {"write": ["docs/stories/**"]}
    assert "submit_work_plan" in plan["tool_policy"]["allowlist"]
    assert graph.nodes["ready"].config == {"decider": "requester", "subject": "readiness", "auto_accept": "epic_story"}
    assert graph.nodes["decisions"].config == {"decider": "requester", "subject": "decisions", "shows": "review_verdict",
                                              "auto_accept": "review_passed", "auto_revise": 2, "revise_on": "high"}
    review = graph.nodes["independent_review"].config
    assert (review["phase"], review["screens"], review["screens_node"]) == ("work", True, "pipeline")


def test_the_parallel_box_has_three_role_class_roles_and_the_pipeline_is_their_gate():
    graph = parse_phased_definition(_seed()["definition"])
    work = graph.nodes["work"]
    assert work.kind == "parallel_work" and work.config["plan"] == "plan"
    roles = work.config["roles"]
    assert tuple(roles) == ROLES
    for name in ROLES:
        role = roles[name]
        assert role["model_class"] == "role" and "model" not in role
        assert "run_test_suite" in role["tool_policy"]["allowlist"]
        assert all(check.get("blocking") is False for check in role["workflow_contract"]["checks"])
        assert "path_rules" not in role["workflow_contract"]


def test_the_instructions_split_sensibly_and_hand_each_role_only_the_contract():
    graph = parse_phased_definition(_seed()["definition"])
    coordinator = graph.nodes["plan"].config["workflow_contract"]["when_to_use"]
    for phrase in ("docs/stories/<KEY>.md", "submit_work_plan", "not one item per role by default",
                   "a story without backend work has no backend item", "never share a path", "run in parallel",
                   "proofs", "On a re-plan", "data-testid", "Look and feel"):
        assert phrase in coordinator, phrase
    text = {name: role["workflow_contract"]["when_to_use"] for name, role in graph.nodes["work"].config["roles"].items()}
    for name in ROLES:
        assert "docs/stories/<KEY>.md" in text[name] and "only the specification sections" in text[name]
        assert "post on the agent board" in text[name] and "never edit that path" in text[name]
        assert "submit_phase_result value \"blocked\"" in text[name]
    assert "own the product's design system" in text["frontend"] and "earlier stories" in text["frontend"]
    assert "visual anchors" in text["frontend"] and "Look and feel list" in text["frontend"]
    assert "never from what the implementation happens to do" in text["test"]
    assert "'<screen>-<state>.png'" in text["test"] and "acceptance criteria" in text["test"]


def test_a_red_pipeline_and_review_findings_go_to_fix_items_and_a_replan_to_the_coordinator():
    definition = _seed()["definition"]
    loops = {(edge["source_node_id"], edge["when"]): (edge["target_node_id"], edge["max_iterations"])
             for edge in definition["edges"] if edge.get("kind") == "loop"}
    assert loops == {("work", "replan"): ("plan", 3), ("pipeline", "failed"): ("work", 3),
                     ("decisions", "changed"): ("work", 3)}
    assert definition["layout"] == {"direction": "tb"}
    assert _forward_reachable(definition) == {node["id"] for node in definition["nodes"]}


def test_spec_writing_splits_the_epic_and_the_server_creates_the_stories():
    definition = _seed("spec-writing")["definition"]
    assert validate_phased_definition(definition)["errors"] == []
    assert validate_flow_definition(definition)["valid"] is True
    graph = parse_phased_definition(definition)
    assert [key for key, node in graph.nodes.items() if node.kind == "phase"] == ["interview", "draft", "split"]
    assert "tickets" not in graph.nodes
    split = graph.nodes["split"].config
    assert (split["model_class"], split["output"]) == ("plan", "story_plan")
    assert split["workflow_contract"]["capability_class"] == "read_only"
    assert "work_item_create" not in split["tool_policy"]["allowlist"]
    assert "submit_story_plan" in split["tool_policy"]["allowlist"]
    text = split["workflow_contract"]["when_to_use"]
    assert "S1 always builds the design system and the app shell" in text and "build order" in text
    assert graph.nodes["stories"].config == {"action": "work.create_stories",
                                             "params": {"issue_type": "Story", "story_workflow": "epic-delivery"}}
    routes = {(edge["source_node_id"], edge.get("when")): edge["target_node_id"] for edge in definition["edges"]}
    assert routes[("answers", "confirmed")] == routes[("answers", "changed")] == "draft"
    assert (routes[("decisions", "confirmed")], routes[("split", None)]) == ("split", "stories")
    assert (routes[("stories", "succeeded")], routes[("stories", "failed")]) == ("push", "action_failed")
    assert _forward_reachable(definition) == {node["id"] for node in definition["nodes"]}


@pytest.fixture
def actions(monkeypatch):
    from app.services.workflow_runs import platform_actions
    from app.services.workflow_runs.platform.dispatch import ToolOutcome

    entered: list[str] = []

    async def typed(db, run, key, params, node=None):
        entered.append(key)
        if key == "pipeline.run":
            return ToolOutcome("succeeded", {}), platform_actions.WAIT
        return ToolOutcome("succeeded", {}), "succeeded"

    monkeypatch.setattr(platform_actions, "_typed", typed)
    return entered




async def _story_at_work(db, fake):  # noqa: F811
    from app.services.workflow_runs.binding import run_turn_resolution
    from app.services.workflow_runs.phase_outputs import submit_output
    from app.services.workflow_runs.records import start_run
    from app.services.workflow_runs.run_sessions import new_bound_session

    admin = await admin_user(db)
    project = await make_project(db)
    story = WorkItem(source_type="platform", source_instance="octryx", source_key="CHEF-2", title="Kitchen helper S1: shell",
                     epic_key="CHEF-1", project_id=project.id, work_state="intake")
    db.add(story)
    await db.flush()
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _seed()["definition"]),
                          project_id=project.id, work_item_id=story.id)
    run.context = {**run.context, "local_path": str(fake.copy),
                   "device_change": {"patch": "diff --git a/docs/stories/CHEF-2.md b/docs/stories/CHEF-2.md\n+x\n"}}
    session = await new_bound_session(db, run, admin)
    resolution = await run_turn_resolution(db, session, user_message="Plan the story.")
    plan = [item("api", paths=["server/**"]), item("ui", role="frontend", paths=["web/**"])]
    recorded = await submit_output(db, run, "submit_work_plan", {"contract": "GET /api/x", "items": plan},
                                   session_id=session.id)
    assert recorded["state"] == "recorded", recorded
    await phase_turn(db, session.id, resolution, ["read_workspace_file", "edit_workspace_file", "submit_work_plan"])
    assert run.current_node_id == "work"
    return run, session, plan


@pytest.mark.asyncio
async def test_a_first_pass_item_is_new_work_and_a_reopened_one_gets_the_rework_facts(db, fake, actions):  # noqa: F811
    from app.services.workflow_runs.graph import graph_for_run
    from app.services.workflow_runs.phase_marker import RUN_PHASE_CONTRACT_KEY
    from app.services.workflow_runs.teamwork.item_definition import item_definition

    run, _session, _plan = await _story_at_work(db, fake)
    assert [answer.get("auto_accepted") for answer in run.context["po_answers"]] == [
        "story of epic CHEF-1: the product owner answered for the epic"]
    work_node = (await graph_for_run(db, run)).nodes["work"]
    fresh = items_of(run)["api"]

    def facts(entry: dict) -> dict:
        return item_definition(run, work_node, entry)["workflow_contract"][RUN_PHASE_CONTRACT_KEY]

    first = facts(fresh)
    assert first["iteration"] == 1
    assert "product_owner_answers" not in first and "previous_change" not in first
    again = facts({**fresh, "iteration": 2, "reason": "reopened"})
    assert again["iteration"] == 2 and again["product_owner_answers"] and again["previous_change"]["files"] == [
        "docs/stories/CHEF-2.md"]
    roles = work_node.config["roles"]
    for name in ("backend", "frontend"):
        assert "work_item.iteration above 1" in roles[name]["workflow_contract"]["when_to_use"]


@pytest.mark.asyncio
async def test_the_epic_story_answer_is_recorded_once_per_run(db, fake, actions):  # noqa: F811
    from app.services.workflow_runs.auto_accept import accept_on_entry
    from app.services.workflow_runs.graph import graph_for_run

    run, _session, _plan = await _story_at_work(db, fake)
    ready = (await graph_for_run(db, run)).nodes["ready"]
    assert await accept_on_entry(db, run, ready) and await accept_on_entry(db, run, ready)
    assert len(run.context["po_answers"]) == 1




def test_the_spec_is_written_on_sonnet_where_the_work_item_names_it():
    graph = parse_phased_definition(_seed("spec-writing")["definition"])
    assert {name: graph.nodes[name].config.get("model_class") for name in ("interview", "draft", "split")} == {
        "interview": "plan", "draft": "plan", "split": "plan"}
    assert {role["model_class"] for role in parse_phased_definition(_seed()["definition"]).nodes["work"].config[
        "roles"].values()} == {"role"}
    draft = graph.nodes["draft"].config["workflow_contract"]["when_to_use"]
    assert "at the path the work item names for it" in draft and "when it names none" in draft


def test_the_coordinator_names_an_owner_for_every_shared_file():
    text = parse_phased_definition(_seed()["definition"]).nodes["plan"].config["workflow_contract"]["when_to_use"]
    for phrase in ("always a file under the item's own paths", "__init__.py", "conftest.py", "pyproject.toml",
                   "the router", "the navigation", "the translation strings", "exactly one owner item",
                   "depends on its owner and names the file in appends_to", "a folder as folder/**"):
        assert phrase in text, phrase


def test_the_seeds_name_only_tools_that_exist_and_list_the_board():
    from app.services.workflow_runs.octryx.device_tools import device_tool_names

    dead = {"analyze_workspace_repository", "get_git_diff", "todo_read", "todo_write"}
    for key in ("spec-writing", "team-delivery"):
        policies = [node["config"]["tool_policy"] for node in _seed(key)["definition"]["nodes"]
                    if "tool_policy" in node.get("config", {})]
        policies += [role["tool_policy"] for node in _seed(key)["definition"]["nodes"]
                     for role in (node.get("config", {}).get("roles") or {}).values()]
        assert policies and not any(dead & set(policy["allowlist"]) for policy in policies), key
    graph = parse_phased_definition(_seed()["definition"])
    for policy in [graph.nodes["plan"].config["tool_policy"],
                   *(role["tool_policy"] for role in graph.nodes["work"].config["roles"].values())]:
        on_device = device_tool_names(policy["allowlist"])
        assert {f"mcp__octryx-knowledge__{name}" for name in ("board_post", "board_read", "board_ack")} <= set(
            on_device)
