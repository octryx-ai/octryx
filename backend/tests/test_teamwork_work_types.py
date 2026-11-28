from __future__ import annotations

from typing import get_type_hints

import pytest

from app.services.workflow_runs.teamwork import SplitItem, WorkSplit
from app.services.workflow_runs.teamwork.team_block import team_block
from app.services.workflow_runs.teamwork.views import ITEM_VIEW_FIELDS, work_view
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.teamwork_engine_support import fake, item, planned_run  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
async def test_the_run_view_and_the_team_block_read_only_split_item_fields(db, fake):  # noqa: F811
    run, _session = await planned_run(db, [item("api")], copy_dir=fake.copy)
    assert set(ITEM_VIEW_FIELDS) <= get_type_hints(SplitItem).keys()
    view = work_view(run)
    assert view is not None and view.keys() - {"items"} <= get_type_hints(WorkSplit).keys()
    team = await team_block(db, run, item_key="api")
    assert {key for entry in team["items"] for key in entry} - {"you"} <= get_type_hints(SplitItem).keys()
