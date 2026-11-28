"""The offer of a run's writing phase carries what the launcher needs for the context pack; a read-only one does not."""

from __future__ import annotations

import copy
import uuid

import pytest

from app.models.runtime.secure_work import WorkItem
from app.services.devices.job_offer import offer_body
from tests.teamwork_device_support import admitted, scheduler  # noqa: F401 - fixtures
from tests.workflow_run_octryx_continuation_support import DEFINITION, _confirm, _device_run, _jobs


def _writing() -> dict:
    definition = copy.deepcopy(DEFINITION)
    work = next(node for node in definition["nodes"] if node["id"] == "work")
    work["config"]["workflow_contract"]["capability_class"] = "change"
    return definition


async def _offer(db, definition: dict, *, item: bool = True, pin: dict | None = None) -> dict:
    from app.services.devices.jobs_channel import _thread_run

    admin, _device, thread, run = await _device_run(db, definition=definition)
    if item:
        found = WorkItem(source_type="platform", source_instance="octryx", source_key=f"SHOP-{uuid.uuid4().hex[:4]}",
                         title="Cancelled orders are refunded", description="`cancel_order` must refund.",
                         project_id=run.project_id, work_state="intake")
        db.add(found)
        await db.flush()
        run.work_item_id = found.id
    if pin is not None:
        run.context = {**dict(run.context or {}), "contract_pin": pin}
    await _confirm(db, run, admin)
    assert run.current_node_id == "work"
    [job] = await _jobs(db, thread)
    return offer_body(job, limits={}, **await _thread_run(db, job))


@pytest.mark.asyncio
async def test_a_writing_phase_offers_its_work_item_and_app_folder_for_the_context_pack(db):
    offer = await _offer(db, _writing(), pin={"sha256": "a" * 64, "file": "shop/.octryx/environment.json",
                                              "environment": {"app_folder": "shop"}})
    request = offer["context_pack"]
    assert (request["phase"], request["app_folder"]) == ("work", "shop")
    assert request["item"]["title"] == "Cancelled orders are refunded"
    assert request["item"]["description"] == "`cancel_order` must refund."
    assert request["item"]["key"].startswith("SHOP-")


@pytest.mark.asyncio
async def test_a_read_only_phase_or_a_run_without_a_work_item_offers_no_pack(db):
    assert "context_pack" not in await _offer(db, copy.deepcopy(DEFINITION))
    without = await _offer(db, _writing(), item=False)
    assert "context_pack" not in without


@pytest.mark.asyncio
async def test_without_a_pinned_environment_the_pack_reads_the_whole_checkout(db):
    assert (await _offer(db, _writing()))["context_pack"]["app_folder"] == "."


@pytest.mark.asyncio
async def test_a_teamwork_items_turn_offers_the_items_own_text_and_paths(db, scheduler, admitted):  # noqa: F811
    from app.services.devices.jobs_channel import _thread_run
    from tests.teamwork_device_support import _item_running
    from tests.teamwork_device_support import _run as teamwork_run

    _admin, _device, _thread, run = await teamwork_run(db)
    _started, job = await _item_running(db, run)
    request = (await _thread_run(db, job))["context_pack"]
    assert request["phase"] == "work:api" and request["item"]["title"] == "Search API"
    assert (request["item"]["description"], request["item"]["paths"]) == ("Build GET /search", ["server/**"])


def test_a_red_pipeline_or_a_review_names_its_files_for_the_pack():
    from app.services.workflow_runs.octryx.context_pack import _named_paths

    contract = {"workflow_run_phase": {
        "pipeline_failure": {"failed": [{"failed_tests": ["tests/system/test_p.py::test_form"]}],
                             "code_style_errors": ["python: E501 --> shop/cart.py:183:89 [linter]"]},
        "review_findings": ["High: shop/cart.py:12 rounds before it sums"]}}
    assert _named_paths(contract) == ["tests/system/test_p.py", "shop/cart.py"]
    assert _named_paths({}) == []
