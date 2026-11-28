"""The seat model by the phase's model class: node > run start > phase default >
workflow > Workspace > installation > device default; the shipped seeds name classes, not models."""

from __future__ import annotations

import json

import pytest

from app.services.devices.device_runs_keys import DeviceRunsPolicyError, normalize_device_runs
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.octryx.seat_models import (
    Levels,
    choose,
    installation_models,
    node_class,
    shipped_defaults,
)
from tests.phase_seat_models_support import seat_admitted  # noqa: F401 - fixture
from tests.phase_sessions_models_support import _events, _seat_run, _with_phase  # noqa: F401 - fixtures
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_continuation_support import DEFINITION, _confirm, _hub, _jobs  # noqa: F401 - fixtures

pytestmark = pytest.mark.usefixtures("scripted_pool")

HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
LEVELS = Levels(workflow={"plan": "wf-plan"}, workspace={"implement": "ws-implement", "plan": "ws-plan"},
                installation={"implement": "inst-implement", "plan": "inst-plan", "role": "inst-role"})


def test_the_order_is_node_run_start_thread_workflow_workspace_installation_device():
    plan = {"model_class": "plan"}
    assert choose(LEVELS, {**plan, "model": OPUS}, run_model=SONNET).source == "node"
    assert choose(LEVELS, plan, run_model=SONNET).source == "run_start"
    assert (choose(LEVELS, plan, thread_model=OPUS).model, choose(LEVELS, plan, thread_model=OPUS).source) == (
        OPUS, "thread")
    assert (choose(LEVELS, plan).model, choose(LEVELS, plan).source) == ("wf-plan", "workflow")
    assert (choose(LEVELS, {"model_class": "implement"}).model,
            choose(LEVELS, {"model_class": "implement"}).source) == ("ws-implement", "workspace")
    assert (choose(LEVELS, {"model_class": "role"}).model,
            choose(LEVELS, {"model_class": "role"}).source) == ("inst-role", "installation")
    assert (choose(Levels(), {"model_class": "role"}).model, choose(Levels(), {}).source) == ("", "device")


def test_a_phase_without_a_class_takes_its_capabilitys_class():
    assert node_class({}, "read_only") == "plan"
    assert node_class({}, "change") == node_class({}, "deliver") == "implement"
    assert node_class({"model_class": "review"}, "change") == "review"


def test_a_class_default_of_the_other_engine_is_skipped_an_explicit_model_never():
    levels = Levels(installation={"implement": HAIKU})
    assert choose(levels, {"model_class": "implement"}, engine="codex").source == "device"
    assert choose(levels, {"model_class": "implement"}, engine="claude_code").model == HAIKU
    assert choose(levels, {"model": HAIKU}, engine="codex").model == HAIKU


def test_the_event_text_comes_from_the_catalog_and_the_source_labels():
    choice = choose(LEVELS, {"model_class": "implement"})
    assert choice.message() == "Model ws-implement from Workspace default 'implement'."


@pytest.mark.asyncio
async def test_the_installation_defaults_ship_as_data_and_system_config_overrides_them(db):
    from app.services.system_config.values import set_system_config_value

    assert await installation_models(db) == shipped_defaults() == {
        "plan": SONNET, "implement": HAIKU, "review": SONNET, "role": HAIKU}
    await set_system_config_value(db, key="seat_models", value=json.dumps({"implement": SONNET, "bogus": "x"}))
    assert (await installation_models(db))["implement"] == SONNET
    assert "bogus" not in await installation_models(db)


def test_the_workspace_and_the_workflow_levels_validate():
    assert normalize_device_runs({"seat_models": {"implement": SONNET}}, "p")["seat_models"] == {"implement": SONNET}
    for bad in ({"bogus": SONNET}, {"implement": ""}, {"implement": 3}, ["implement"]):
        with pytest.raises(DeviceRunsPolicyError):
            normalize_device_runs({"seat_models": bad}, "p")
    definition = _with_phase(DEFINITION, "work", model_class="bogus")
    assert "phase_model_class" in [item["code"] for item in validate_phased_definition(definition)["errors"]]
    assert "models" in [item["code"] for item in validate_phased_definition(
        {**DEFINITION, "models": {"implement": 5}})["errors"]]
    assert validate_phased_definition({**DEFINITION, "models": {"implement": SONNET}})["valid"] is \
        validate_phased_definition(DEFINITION)["valid"]


def test_the_shipped_seeds_name_model_classes_not_models():
    from tests.phased_seed_definitions import seed_definitions

    seeds = {seed["key"]: seed for seed in seed_definitions()}
    classes = {}
    for key in ("spec-writing", "team-delivery", "epic-delivery"):
        for node in seeds[key]["definition"]["nodes"]:
            config = node.get("config") or {}
            assert "model" not in config, (key, node["id"])
            for role, template in dict(config.get("roles") or {}).items():
                assert "model" not in template
                classes[(key, f"{node['id']}.{role}")] = template["model_class"]
            if "model_class" in config:
                classes[(key, node["id"])] = config["model_class"]
    assert classes == {
        ("spec-writing", "interview"): "plan", ("spec-writing", "draft"): "plan", ("spec-writing", "split"): "plan",
        ("team-delivery", "plan"): "plan", ("team-delivery", "work.backend"): "role",
        ("team-delivery", "work.frontend"): "role", ("team-delivery", "work.test"): "role",
        ("epic-delivery", "implement"): "implement"}


@pytest.mark.asyncio
async def test_a_seat_turn_without_a_chosen_model_runs_the_class_default_and_says_where_from(db, seat_admitted):  # noqa: F811
    seat_admitted["models"] |= {SONNET}
    admin, thread, run = await _seat_run(db, _with_phase(DEFINITION, "work", model_class="plan"))
    thread.metadata_ = {**thread.metadata_, "execution_target": {**thread.metadata_["execution_target"],
                                                                 "model": ""}}
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    assert (job.profile, job.turn_model) == ("seat", SONNET)
    [event] = await _events(db, run, "run_turn_model")
    assert event.detail == {"model": SONNET, "source": "installation", "class": "plan",
                            "message": "Model claude-sonnet-5-5 from installation default 'plan'."}


@pytest.mark.asyncio
async def test_the_model_chosen_for_the_run_wins_over_the_class_default(db, seat_admitted):  # noqa: F811
    admin, thread, run = await _seat_run(db, _with_phase(DEFINITION, "work", model_class="implement"))
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    assert job.turn_model == OPUS
    [event] = await _events(db, run, "run_turn_model")
    assert (event.detail["source"], event.detail["model"]) == ("thread", OPUS)


@pytest.mark.asyncio
async def test_the_model_chosen_at_run_start_wins_over_the_thread_and_the_class_default(db, seat_admitted):  # noqa: F811
    from app.services.workflow_runs.runtime_target.target import stored_target, with_target

    seat_admitted["models"] |= {SONNET}
    admin, thread, run = await _seat_run(db, _with_phase(DEFINITION, "work", model_class="implement"))
    run.context = with_target(run.context, {**(stored_target(run) or {}), **thread.metadata_["execution_target"],
                                            "model": SONNET}, actor_id=None)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    assert job.turn_model == SONNET
    [event] = await _events(db, run, "run_turn_model")
    assert (event.detail["source"], event.detail["message"]) == (
        "run_start", "Model claude-sonnet-5-5 from the model chosen at run start.")


@pytest.mark.asyncio
async def test_a_class_default_an_earlier_phase_wrote_onto_the_thread_is_no_ones_choice(db, seat_admitted):  # noqa: F811
    seat_admitted["models"] |= {SONNET, HAIKU}
    admin, thread, run = await _seat_run(db, _with_phase(DEFINITION, "work", model_class="implement"))
    thread.metadata_ = {**thread.metadata_, "execution_target": {**thread.metadata_["execution_target"],
                                                                 "model": SONNET}}
    run.context = {**dict(run.context or {}), "seat_model": {"earlier": [SONNET, "installation", "plan"]}}
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    assert job.turn_model == HAIKU
    [event] = await _events(db, run, "run_turn_model")
    assert (event.detail["source"], event.detail["model"]) == ("installation", HAIKU)
