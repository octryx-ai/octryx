"""Team delivery v2: the coordinator writes the story's shared contract and splits the work into items at run
time; ``parallel_work`` builds them side by side with small
models; the CI pipeline, the reviewer and the product owner (only on a high finding) close it; every way back goes to
the coordinator. The epic workflow (``spec-writing``) splits the epic into stories (``story_plan``) and the server
creates them (``work.create_stories``) instead of an agent creating tickets one by one.

The seed is what ``parallel_work``, ``work_plan``, the device items and the sessions, models and stories consume:
the config keys asserted here are their interface.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.runtime.secure_work import WorkItem
from app.services.flow_definitions import validate_flow_definition
from app.services.workflow_runs import teamwork
from app.services.workflow_runs.graph import parse_phased_definition
from app.services.workflow_runs.graph_validation import validate_phased_definition
from tests.agent_definition_revision_fixtures import make_project
from tests.phased_workflow_fixtures import admin_user, phase_turn, publish_phased
from tests.teamwork_engine_support import fake, finish_item, item, items_of  # noqa: F401  (``fake`` is a fixture)

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
    assert validate_flow_definition(definition)["valid"] is True  # incl. the parallel_work node and its roles
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
        assert role["model_class"] == "role" and "model" not in role  # the seat_models default (Haiku)
        assert "run_test_suite" in role["tool_policy"]["allowlist"]
        # The pipeline after the work is the gate: a builder's own test run never holds its Stop.
        assert all(check.get("blocking") is False for check in role["workflow_contract"]["checks"])
        # The item's own paths are its write rule at run time; a template rule would only be overwritten.
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
    """A red pipeline and the review's findings go back to the team itself (``teamwork.fixes``: only the items that
    own what failed run again, instead of re-planning and re-running every item for one CSS split); what no item
    owns, a blocked fix and a person's own answers go on to the coordinator (``replan``). The designer draws a node
    reached only through a way back as a second root, so every node is reachable from Start with forward arrows."""
    definition = _seed()["definition"]
    loops = {(edge["source_node_id"], edge["when"]): (edge["target_node_id"], edge["max_iterations"])
             for edge in definition["edges"] if edge.get("kind") == "loop"}
    assert loops == {("work", "replan"): ("plan", 3), ("pipeline", "failed"): ("work", 3),
                     ("decisions", "changed"): ("work", 3)}
    assert definition["layout"] == {"direction": "tb"}
    assert _forward_reachable(definition) == {node["id"] for node in definition["nodes"]}


def test_spec_writing_splits_the_epic_and_the_server_creates_the_stories():
    """One PO round per epic (interview, answers), then the coordinator's story plan and the server step that creates
    the stories (adopting an epic's existing ones) and names epic-delivery as their workflow."""
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


# --- integration: the seed itself, from start to the pipeline -------------------------------------------------------


@pytest.fixture
def actions(monkeypatch):
    """The SCM and workspace steps succeed at once; the pipeline is entered and waits (its runner is not under test)."""
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


@pytest.mark.asyncio
async def test_team_delivery_v2_runs_a_three_item_plan_with_a_dependent_item_to_the_pipeline(db, fake, actions):  # noqa: F811
    from app.services.workflow_runs.binding import run_turn_resolution
    from app.services.workflow_runs.graph import graph_for_run
    from app.services.workflow_runs.phase_outputs import submit_output
    from app.services.workflow_runs.records import start_run
    from app.services.workflow_runs.run_sessions import new_bound_session
    from app.services.workflow_runs.teamwork.item_definition import item_node

    admin = await admin_user(db)
    project = await make_project(db)
    story = WorkItem(source_type="platform", source_instance="octryx", source_key="OCX-91", title="Kitchen helper S2: search",
                     epic_key="OCX-90", project_id=project.id, work_state="intake")
    db.add(story)
    await db.flush()
    key = await publish_phased(db, _seed()["definition"])
    run = await start_run(db, user=admin, workflow_key=key, project_id=project.id, work_item_id=story.id)
    assert actions == ["scm.create_branch", "workspace.prepare"] and run.current_node_id == "plan"

    run.context = {**run.context, "local_path": str(fake.copy)}
    session = await new_bound_session(db, run, admin)
    resolution = await run_turn_resolution(db, session, user_message="Plan the story.")
    assert resolution["workflow_contract"]["path_rules"]["write"] == ["docs/stories/**"]
    plan = [item("api", paths=["server/**"]), item("ui", role="frontend", paths=["web/**"]),
            item("wire", role="frontend", depends_on=["api", "ui"], paths=["wire/**"])]
    recorded = await submit_output(db, run, "submit_work_plan", {"contract": "GET /api/search?q=", "items": plan},
                                   session_id=session.id)
    assert recorded["state"] == "recorded", recorded
    await phase_turn(db, session.id, resolution, ["read_workspace_file", "edit_workspace_file", "submit_work_plan"])

    # The readiness of an epic's story is accepted for the product owner; the two independent items start together.
    assert run.current_node_id == "work"
    assert [name for name, _ in fake.started] == ["api", "ui"]
    work_node = (await graph_for_run(db, run)).nodes["work"]
    for name, role in (("api", "backend"), ("ui", "frontend"), ("wire", "frontend")):
        node = item_node(run, work_node, items_of(run)[name])
        assert node.config["model_class"] == "role"
        assert node.config["workflow_contract"]["path_rules"]["write"] == dict(
            (entry["id"], entry["paths"]) for entry in plan)[name]
        assert node.config["workflow_contract"]["when_to_use"] == work_node.config["roles"][role][
            "workflow_contract"]["when_to_use"]

    await finish_item(db, run, "api")
    assert items_of(run)["wire"]["status"] == "pending" and run.current_node_id == "work"
    await finish_item(db, run, "ui")
    assert [name for name, _ in fake.started] == ["api", "ui", "wire"]  # the dependent item once both are merged
    await finish_item(db, run, "wire")

    assert {name: value["status"] for name, value in items_of(run).items()} == {
        "api": "merged", "ui": "merged", "wire": "merged"}
    assert teamwork.work_of(run)["route"] == "done" and fake.finished == 1
    assert [task["id"] for task in run.context["task_list"]] == ["api", "ui", "wire"]
    assert actions[-1] == "pipeline.run" and run.current_node_id == "pipeline"


# --- Kitchen helper preflight: item contracts, the auto-accept, a replan that must change something ----------


async def _story_at_work(db, fake):  # noqa: F811
    """team-delivery for a story of an epic, its plan recorded and the run at ``work``."""
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
    """Items on iteration 1 must not get the epic-story auto-accept as product_owner_answers and the story's change
    as previous_change ("do not read whole files"), which the role text reads as "reopened"."""
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
    """Every replan and "changed" loop enters ``ready`` again and must not append the same answer each time."""
    from app.services.workflow_runs.auto_accept import accept_on_entry
    from app.services.workflow_runs.graph import graph_for_run

    run, _session, _plan = await _story_at_work(db, fake)
    ready = (await graph_for_run(db, run)).nodes["ready"]
    assert await accept_on_entry(db, run, ready) and await accept_on_entry(db, run, ready)
    assert len(run.context["po_answers"]) == 1


@pytest.mark.asyncio
async def test_a_replan_after_a_red_pipeline_or_answers_must_change_the_plan(db, fake, actions):  # noqa: F811
    """A plan resubmitted unchanged after a red pipeline would keep every item merged, finish ``work`` at once and run
    the same red pipeline again, using a loop for nothing. A replan from the items' own failure is not held to it."""
    from app.services.workflow_runs.phase_outputs import submit_output

    run, session, plan = await _story_at_work(db, fake)
    for name in ("api", "ui"):
        await finish_item(db, run, name)
    assert run.current_node_id == "pipeline"
    for source, refused in (("pipeline", True), ("decisions", True), ("work", False)):
        run.status, run.current_node_id = "running", "plan"
        run.context = {**run.context, "carried": {"plan": {"from": source, "result": None}}}
        answer = await submit_output(db, run, "submit_work_plan", {"contract": "GET /api/x", "items": plan},
                                     session_id=session.id)
        assert (answer["state"] == "refused") is refused, (source, answer)
        if refused:
            assert "changes nothing" in answer["message"] and "Reopen the item" in answer["message"]
    run.context = {**run.context, "carried": {"plan": {"from": "pipeline", "result": None}}}
    reopened = [{**plan[0], "reopen": True}, plan[1]]
    answer = await submit_output(db, run, "submit_work_plan", {"contract": "GET /api/x", "items": reopened},
                                 session_id=session.id)
    assert answer["state"] == "recorded", answer


def test_the_spec_is_written_on_sonnet_where_the_work_item_names_it():
    """The interview and the draft run on Sonnet like the split; the items stay on Haiku. The path the work item
    names wins, else SPEC.md."""
    graph = parse_phased_definition(_seed("spec-writing")["definition"])
    # As model classes; the installation's seat_models put plan on Sonnet, roles on Haiku.
    assert {name: graph.nodes[name].config.get("model_class") for name in ("interview", "draft", "split")} == {
        "interview": "plan", "draft": "plan", "split": "plan"}
    assert {role["model_class"] for role in parse_phased_definition(_seed()["definition"]).nodes["work"].config[
        "roles"].values()} == {"role"}
    draft = graph.nodes["draft"].config["workflow_contract"]["when_to_use"]
    assert "at the path the work item names for it" in draft and "when it names none" in draft


def test_the_coordinator_names_an_owner_for_every_shared_file():
    """In the coordinator's instructions: proofs under the item's own paths; one owner per shared file, the
    others depend on it and append through appends_to."""
    text = parse_phased_definition(_seed()["definition"]).nodes["plan"].config["workflow_contract"]["when_to_use"]
    for phrase in ("always a file under the item's own paths", "__init__.py", "conftest.py", "pyproject.toml",
                   "the router", "the navigation", "the translation strings", "exactly one owner item",
                   "depends on its owner and names the file in appends_to", "a folder as folder/**"):
        assert phrase in text, phrase


def test_the_seeds_name_only_tools_that_exist_and_list_the_board():
    """Allowlists must not name analyze_workspace_repository, get_git_diff, todo_read and todo_write, which no
    device has; the board tools the coordinator and the items are told to use are in the allowlist."""
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
