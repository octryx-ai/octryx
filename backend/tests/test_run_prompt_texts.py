"""The run prompts come from the prompt catalog; with the seeds they are the expected texts word for word, and a
workflow's own version wins over the global one while a Workspace's wins over the workflow's."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.workflow_runs.octryx import continuation_prompts
from app.services.workflow_runs.run_texts import run_text

RUN = SimpleNamespace(id="r-1", workflow_key="story-delivery", project_id=None, ticket_key="OCX-1", title="T")
READ = ("Read your run contract first: the launcher puts this phase's contract into your context with this prompt. "
        "Only if it is not there, or you need more, call workflow_run_status with no arguments (this session's run is "
        "r-1; detail=true adds the code style and the earlier change). Work only within it. Never select or start "
        "another workflow.")


def _node(kind="phase", title="Implement", config=None):
    return SimpleNamespace(kind=kind, title=title, id="implement", config=config or {})


def test_the_phase_prompts_are_todays_texts(monkeypatch):
    monkeypatch.setattr("app.services.workflow_runs.phase_contract.phase_definition",
                        lambda run, node: {"workflow_contract": {"capability_class": "code_change"}})
    assert continuation_prompts._prompt(RUN, _node()) == (
        f"Continue the story-delivery workflow run: phase 'Implement' (code_change). {READ}")
    assert continuation_prompts._prompt(RUN, _node(kind="platform_action", title="Prepare")) == (
        f"Continue the story-delivery workflow run: the platform prepared this folder (Prepare). {READ}")
    assert continuation_prompts._pipeline_red_prompt(RUN, _node()) == (
        "Phase 'Implement' of this run (r-1) continues in this session: the platform's CI pipeline ran "
        "the repository's declared test commands on your change and they are red. Your earlier work, plan and "
        "reading still stand: do not re-read the specification or files you already know. The failing commands, "
        "the failing tests and the end of their output follow below (the launcher adds them; "
        "phase.pipeline_failure in workflow_run_status has the same). Fix exactly that, run the declared commands "
        "verbatim, then end your "
        "turn with a short summary.")
    assert continuation_prompts._epic_prompt(RUN, _node()) == (
        "A new story of the same epic starts in this session: phase 'Implement' of the story-delivery "
        "run r-1. What you read for the previous story (the specification, the earlier story contracts, the "
        f"code) still stands: do not re-read it; read only what this story names and what changed since. {READ}")


def test_the_resume_prompts_are_todays_texts(monkeypatch):
    facts = {}
    monkeypatch.setattr(continuation_prompts, "_phase_facts", lambda run, node: facts)
    assert continuation_prompts._resumed_prompt(RUN, _node(), retry=True) == (
        "Your last turn in phase 'Implement' (run r-1) stopped on a temporary error of the model "
        "service. Continue exactly where you stopped; nothing else changed.")
    start = ("Phase 'Implement' of this run (r-1) continues in this session: the platform runs this phase again. "
             "Your earlier work, plan and reading still stand: do not re-read the specification or files you already "
             "know.")
    assert continuation_prompts._resumed_prompt(RUN, _node(), retry=False) == (
        f"{start} Call workflow_run_status once for the details, fix exactly that, then finish the phase.")
    facts.update({"pipeline_failure": {"x": 1}, "review_findings": ["F1"]})
    details = {"pipeline_failure": {"x": 1}, "review_findings": ["F1"]}
    assert continuation_prompts._resumed_prompt(RUN, _node(), retry=False) == (
        "Phase 'Implement' of this run (r-1) continues in this session: the pipeline failed on your change "
        "(phase.pipeline_failure names the failing commands); the review returned findings (phase.review_findings: "
        "fix each one). Your earlier work, plan and reading still stand: do not re-read the specification or files "
        "you already know. The details are below; fix exactly that, then finish the phase (workflow_run_status only "
        f"if you need more than this).\n\n{json.dumps(details, ensure_ascii=False, indent=1)}")


def test_the_team_prompts_are_todays_texts():
    from app.services.workflow_runs.teamwork.coordinator import _prompt as board
    from app.services.workflow_runs.teamwork.item_threads import _prompt as item_prompt

    item = {"id": "i1", "title": "API", "role": "backend", "iteration": 2}
    assert item_prompt(RUN, item, resumed=True, conflicts=["a.py"]) == (
        "Your work item 'API' (i1) of run r-1 continues in this session (iteration 2): the coordinator reopened it. "
        "The story's current work was merged into your branch and conflicts in a.py: resolve the conflict markers "
        "there (keep both sides' intent) before anything else. Your earlier work still stands; fix what changed, "
        f"then finish with submit_phase_result. {READ}")
    assert item_prompt(RUN, item, resumed=False) == (
        "Build work item 'API' (i1) of the story-delivery run r-1: your contract names its instructions, the paths "
        "you own and the team. Never wait for anyone: when blocked, ask the owner on the board and finish with "
        f"submit_phase_result \"blocked\". {READ}")
    run = SimpleNamespace(**vars(RUN), context={"teamwork": {"items": {}}})
    text = board(run, ["m1", "m2"])
    assert text.startswith("The team working on this story (run r-1) wrote to you on the board: message(s) m1, m2.")
    assert text.endswith("Do not change code yourself; end the turn once you answered.")


@pytest.mark.asyncio
async def test_a_workflows_own_text_wins_over_the_global_and_a_workspaces_over_the_workflows(db):
    from app.services.workflow_runs.run_texts import run_texts
    from tests.prompt_catalog_publish_support import publish_reviewed
    from tests.services.secure_work.test_platform_work_items import _admin_and_project

    _admin, project = await _admin_and_project(db)

    async def publish(scope_type, scope_id, body):
        await publish_reviewed(db, "run.read_contract", body, scope_type=scope_type, scope_id=scope_id)

    run = SimpleNamespace(id="r-1", workflow_key="team-delivery", project_id=project.id)
    await publish("workflow", "team-delivery", "WORKFLOW {run_id}")
    async with run_texts(db, run):
        assert run_text("read_contract", run_id="r-1") == "WORKFLOW r-1"
    await publish("workspace", project.id, "WORKSPACE {run_id}")
    async with run_texts(db, run):
        assert run_text("read_contract", run_id="r-1") == "WORKSPACE r-1"
    other = SimpleNamespace(id="r-2", workflow_key="ticket-delivery", project_id=None)
    async with run_texts(db, other):
        assert run_text("read_contract", run_id="r-2").startswith("Read your run contract first")


def test_the_builders_carry_no_prompt_prose():
    from pathlib import Path

    import app.services.workflow_runs.evidence_pause as evidence_pause
    import app.services.workflow_runs.teamwork.coordinator as coordinator
    import app.services.workflow_runs.teamwork.item_threads as item_threads

    phrases = {continuation_prompts: ("Your earlier work, plan and reading still stand", "call workflow_run_status with no",
                              "the platform prepared this folder", "A new story of the same epic starts"),
               item_threads: ("Never wait for anyone", "continues in this session (iteration"),
               coordinator: ("wrote to you on the board",),
               evidence_pause: ("ran several test files concurrently",)}
    for module, texts in phrases.items():
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert not [text for text in texts if text in source], module.__name__
    assert run_text("read_contract", run_id="x").startswith("Read your run contract first")


def test_the_launchers_fallbacks_are_the_catalogs_seeds():
    import importlib.util
    from pathlib import Path

    from app.services.prompt_catalog.registry import prompt_key_registry

    path = Path(__file__).parents[2] / "clients" / "octryx-claude" / "octryx_claude" / "pipeline_texts.py"
    source = path.read_text(encoding="utf-8")
    start = source.index("FALLBACK_TEXTS = {")
    namespace: dict = {}
    exec(source[start:source.index("}\n", start) + 2], namespace)  # noqa: S102 - the literal dict only
    registry = prompt_key_registry()
    assert namespace["FALLBACK_TEXTS"] and all(registry[key].seed == body
                                               for key, body in namespace["FALLBACK_TEXTS"].items())
    assert importlib.util.find_spec("app.services.workflow_runs.run_texts") is not None


@pytest.mark.asyncio
async def test_the_launcher_texts_are_the_runs_resolved_bodies(db):
    from app.services.workflow_runs.run_texts import launcher_texts

    texts = await launcher_texts(db, SimpleNamespace(project_id=None, workflow_key="story-delivery"))
    assert set(texts) == {"run.launcher.pipeline_red", "run.launcher.env_missing", "run.launcher.env_setup_failed",
                          "run.launcher.env_invalid",
                          "run.launcher.wrapper_denied", "run.launcher.plain_form", "run.launcher.fail_closed",
                          "run.launcher.proof_unavailable", "run.launcher.takeover_denied",
                          "run.launcher.patch_format", "run.launcher.sandbox_browser",
                          "run.launcher.code_map", "run.launcher.compound_test",
                          "run.launcher.compound_tool", "run.launcher.style_tools"}
    assert texts["run.launcher.pipeline_red"].endswith("{summary}")


def test_every_run_key_has_its_group_and_every_placeholder_its_meaning():
    from app.services.prompt_catalog.registry import prompt_key_registry
    from app.services.prompt_catalog.views import serialize_spec

    run_keys = {key: spec for key, spec in prompt_key_registry().items() if key.startswith("run.")}
    for key, spec in run_keys.items():
        item = serialize_spec(spec)
        assert item["group"] and isinstance(item["group_order"], int), key
        assert set(item["placeholder_descriptions"]) == set(spec.placeholders), key
    groups = {(spec.group, spec.group_order) for spec in run_keys.values()}
    assert groups == {("Continuation", 10), ("Pipeline and launcher", 20), ("Evidence", 30),
                      ("Team and coordinator", 40), ("Models", 60), ("Blocks and pauses", 70),
                      ("Phase brief", 15)}
    assert run_keys["run.launcher.pipeline_red"].group == "Pipeline and launcher"
    other = next(spec for key, spec in prompt_key_registry().items() if not key.startswith("run."))
    assert serialize_spec(other)["group"] is None and serialize_spec(other)["placeholder_descriptions"] == {}


def test_a_phase_sent_back_by_a_refusals_rule_reads_why_once(monkeypatch):
    monkeypatch.setattr("app.services.workflow_runs.phase_contract.phase_definition",
                        lambda run, node: {"workflow_contract": {"capability_class": "test_change"}})
    run = SimpleNamespace(**vars(RUN), context={"change_plan_reason": {
        "from": "fix", "intent": "Edit:test/grind_test.dart", "refusal": "'test/grind_test.dart' is a test file"}})
    node = _node(title="Reproduce")
    text = continuation_prompts._prompt(run, node)
    assert text.startswith(f"Continue the story-delivery workflow run: phase 'Reproduce' (test_change). {READ} The")
    assert "sent the run back here from phase 'fix', which was refused Edit:test/grind_test.dart" in text
    assert continuation_prompts._prompt(run, node) == (
        f"Continue the story-delivery workflow run: phase 'Reproduce' (test_change). {READ}")
    run.context = {"change_plan_reason": {"from": "fix", "intent": "Bash:flutter pub", "reason": "outside"}}
    monkeypatch.setattr(continuation_prompts, "_phase_facts", lambda run, node: {})
    resumed = continuation_prompts._resumed_prompt(run, node, retry=False)
    assert "continues in this session: the platform sent the run back here from phase 'fix'" in resumed


def test_the_shared_session_of_a_small_item_reads_why_a_refusals_rule_sent_it_back(monkeypatch):
    from app.services.workflow_runs.octryx.run_session import next_phase_prompt

    monkeypatch.setattr("app.services.workflow_runs.phase_contract.phase_definition",
                        lambda run, node: {"workflow_contract": {"capability_class": "change"}})
    run = SimpleNamespace(**vars(RUN), context={"change_plan_reason": {
        "from": "fix", "intent": "Edit:test/grind_test.dart", "refusal": "'test/grind_test.dart' is a test file"}})
    text = next_phase_prompt(run, _node(title="Reproduce"))
    assert text.startswith("The run moves on to its next phase in this session: phase 'Reproduce' (change).")
    assert "sent the run back here from phase 'fix', which was refused Edit:test/grind_test.dart" in text
    assert "sent the run back" not in next_phase_prompt(run, _node(title="Reproduce"))
