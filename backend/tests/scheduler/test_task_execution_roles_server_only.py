"""The roles of a scheduled connector step are fixed on the server and never pass an admin tool check."""

from __future__ import annotations

from app.scheduler.execution._step_connector_execution import CONNECTOR_STEP_ROLES
from app.tools.admin_impl._admin_common import _require_admin
from app.tools.context import ToolContext


def test_connector_steps_run_as_operator_and_never_pass_an_admin_tool_check():
    roles = list(CONNECTOR_STEP_ROLES)

    assert roles == ["operator"]
    assert _require_admin(ToolContext(user_id="u1", project_ids=[], roles=roles, session_id="s1", project_config={})) is not None
