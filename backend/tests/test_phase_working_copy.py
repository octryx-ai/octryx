"""A server phase turn works in the run's prepared working copy.

Without it, ``analyze_workspace_repository`` runs in the chat session's own, empty workspace and the agent reads a
stale Knowledge snapshot instead of the run's base. A change phase (tests_first, implement, reproduce, fix) would
write — and run its tests — in that empty folder, while ``workspace.prepare``, the reviewed tree and the push use
the run's working copy.

Every server phase turn of the run's main session has one root, the working copy: reads, writes,
``run_test_suite`` and the phase path rules (write patterns, confirmed-test protection) all resolve against it. A
change phase without a prepared copy is held ``needs_configuration``. Slice children, device runs and chat outside
a run are unchanged.
"""

from __future__ import annotations

import copy
import subprocess

import pytest

import app.tools.runtime_impl._runtime_test_suite_tool as quality_tools
from app.agent.core.context.run_context_config import assemble_turn_project_config
from app.models import Session
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.phase_workspace import LOST_WORKING_COPY_REASON, NO_WORKING_COPY_REASON
from app.services.workflow_runs.records import new_chat_session, start_run
from app.tools.context import ToolContext
from app.tools.registry import TOOL_REGISTRY
from app.tools.runtime_impl._runtime_code import CodeSearchRepositoryTool
from app.tools.runtime_impl._runtime_repo_analysis_overview import AnalyzeWorkspaceRepositoryTool
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased, run_workspace
from tests.test_read_only_security_integration import _state

BASE = "3215a0be86e6eb0c0aaf704de60d4b815e822bf3"
CONFIRMED = "tests/test_textkit.py"
CHANGE_PATH_RULES = {"write": ["src/**", "tests/**"], "protect_confirmed_tests": True, "create": ["src/**"]}
TESTS_FIRST_PATH_RULES = {"write": ["tests/**"]}  # Workflow B's tests_first: new tests only


def _definition(capability_class: str, path_rules: dict | None = None) -> dict:
    definition = copy.deepcopy(phased_definition())
    config = definition["nodes"][1]["config"]
    config["workflow_contract"]["capability_class"] = capability_class
    if capability_class != "read_only":
        config["workflow_contract"]["path_rules"] = dict(path_rules or CHANGE_PATH_RULES)
        config["tool_policy"]["allowlist"] = ["read_workspace_file", "write_workspace_file", "edit_workspace_file",
                                              "run_test_suite", "code_search", "knowledge_search"]
    return definition


async def _run(db, tmp_path, *, capability_class: str, local_path: bool = True, device: bool = False,
               gone: bool = False, path_rules: dict | None = None):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, session=session,
                          workflow_key=await publish_phased(db, _definition(capability_class, path_rules)),
                          project_id=workspace_id)
    working_copy = tmp_path / "run-copy"
    (working_copy / "tests").mkdir(parents=True)
    (working_copy / "src").mkdir()
    (working_copy / CONFIRMED).write_text("def test_slugify_lowercases():\n    pass\n")
    _commit_all(working_copy)  # the run's copy is a git working copy (a plain folder is never taken for it)
    context = dict(run.context or {})
    if local_path:
        context.update(local_path=str(working_copy / "gone" if gone else working_copy), base_sha=BASE)
    context["confirmed_test_files"] = {"t1": {"file": CONFIRMED}}
    if device:
        context["runtime_target"] = {"kind": "device", "device_id": "dev_x", "folder": "/tmp/x"}
    run.context = context
    await db.flush()
    resolution = await run_turn_resolution(db, await db.get(Session, session.id), user_message="Work.")
    return admin, session, run, resolution, working_copy.resolve()


def _commit_all(root) -> None:
    for argv in (["git", "init", "-q"], ["git", "add", "."],
                 ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"]):
        subprocess.run(argv, cwd=root, check=True, capture_output=True)


def _phase_rule_reasons(result: dict) -> list[str]:
    """The phase path rule's reasons in a refused write's decision (never another source)."""
    decision = result.get("coding_policy_decision") or {}
    return [str(item.get("reason") or "") for item in decision.get("outcomes") or []
            if item.get("policy_type") == "workflow_phase_path_rule" and item.get("blocking")]


async def _turn(db, tmp_path, **kwargs):
    admin, session, run, resolution, working_copy = await _run(db, tmp_path, **kwargs)
    session_root = tmp_path / "session"
    session_root.mkdir()
    config = await assemble_turn_project_config(
        db=db, user_id=admin.id, project_id=None, user_roles=["admin"], workspace_root=str(session_root),
        session_metadata={ROUTING_RESOLUTION_KEY: resolution},
        engineering_runtime_metadata={})
    context = ToolContext(user_id=admin.id, project_ids=[], roles=["admin"], session_id=session.id,
                          project_config=config.project_config, db=db,
                          workspace_root=str(config.tool_workspace_root), capability_type="change",
                          run_capability=await _state(db, resolution))
    return config, context, working_copy, session_root.resolve(), resolution


# --- read-only phases (finding 2) -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_read_only_phase_reads_the_runs_working_copy_with_its_base(db, tmp_path):
    config, context, working_copy, _session_root, _resolution = await _turn(db, tmp_path, capability_class="read_only")

    assert config.tool_workspace_root == working_copy
    assert config.project_config["run_working_copy"] == str(working_copy)
    assert config.project_config["run_base_sha"] == BASE
    analysis = await AnalyzeWorkspaceRepositoryTool().execute({"path": "."}, context)
    assert "tests" in analysis["top_level_directories"], analysis
    found = await CodeSearchRepositoryTool().execute({"query": "test_slugify_lowercases"}, context)
    assert found["total_text_matches"] >= 1, found


@pytest.mark.asyncio
async def test_a_read_only_phase_without_a_copy_keeps_the_session_workspace(db, tmp_path):
    config, _context, _copy, session_root, resolution = await _turn(db, tmp_path, capability_class="read_only",
                                                                    local_path=False)

    assert resolution["status"] == "matched"
    assert config.tool_workspace_root == session_root
    assert "run_working_copy" not in config.project_config


# --- change phases ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_change_phase_writes_in_the_runs_working_copy(db, tmp_path):
    config, context, working_copy, session_root, _resolution = await _turn(db, tmp_path, capability_class="change")

    assert config.tool_workspace_root == working_copy
    written = await TOOL_REGISTRY["write_workspace_file"].execute(
        {"path": "src/textkit/words.py", "content": "def truncate_words(text, n):\n    return text\n"}, context)
    assert not written.get("error"), written
    assert (working_copy / "src/textkit/words.py").exists()
    assert not (session_root / "src").exists()
    edited = await TOOL_REGISTRY["edit_workspace_file"].execute(
        {"path": "src/textkit/words.py", "old_string": "return text", "new_string": "return text[:n]"}, context)
    assert not edited.get("error"), edited
    assert "text[:n]" in (working_copy / "src/textkit/words.py").read_text()


@pytest.mark.asyncio
async def test_a_write_to_a_confirmed_test_is_still_refused_in_the_working_copy(db, tmp_path):
    _config, context, working_copy, _session_root, _resolution = await _turn(db, tmp_path, capability_class="change")
    before = (working_copy / CONFIRMED).read_text()

    refused = await TOOL_REGISTRY["write_workspace_file"].execute(
        {"path": CONFIRMED, "content": "def test_slugify_lowercases():\n    assert True\n"}, context)

    assert any("a person confirmed" in reason for reason in _phase_rule_reasons(refused)), refused
    assert (working_copy / CONFIRMED).read_text() == before
    # A path outside the phase's write patterns is refused as well (path rules resolve against the same copy).
    outside = await TOOL_REGISTRY["write_workspace_file"].execute({"path": "setup.cfg", "content": "x"}, context)
    assert _phase_rule_reasons(outside), outside
    assert not (working_copy / "setup.cfg").exists()


@pytest.mark.asyncio
async def test_run_test_suite_runs_in_the_working_copy(db, tmp_path, monkeypatch):
    _config, context, working_copy, _session_root, _resolution = await _turn(db, tmp_path, capability_class="change")
    seen: dict = {}

    async def suite(**kwargs):
        seen["cwd"] = kwargs["cwd"]
        return {"exit_code": 0, "all_green": True, "command": "pytest", "repo_root": str(kwargs["cwd"])}

    monkeypatch.setattr(quality_tools, "_resolve_test_suite_service", lambda: suite)
    await TOOL_REGISTRY["run_test_suite"].execute({}, context)

    assert seen["cwd"] == working_copy


@pytest.mark.asyncio
async def test_a_change_phase_without_a_prepared_copy_is_held_needs_configuration(db, tmp_path):
    _admin, _session, _run_row, resolution, _copy = await _run(db, tmp_path, capability_class="change",
                                                               local_path=False)

    assert resolution["status"] == "held"
    assert resolution["profile_status"] == "needs_configuration"
    assert resolution["unmatched_reason"] == NO_WORKING_COPY_REASON
    assert resolution["workflow_contract"] is None  # nothing runs, nowhere


@pytest.mark.parametrize("capability_class", ["read_only", "change"])
@pytest.mark.asyncio
async def test_a_declared_copy_that_is_gone_holds_every_phase(db, tmp_path, capability_class):
    # A run that declares a working copy never falls back to the empty session folder.
    _admin, _session, _run_row, resolution, _copy = await _run(db, tmp_path, capability_class=capability_class,
                                                               gone=True)

    assert (resolution["status"], resolution["profile_status"]) == ("held", "needs_configuration")
    assert resolution["unmatched_reason"] == LOST_WORKING_COPY_REASON


@pytest.mark.asyncio
async def test_a_device_run_is_unchanged(db, tmp_path):
    config, _context, _copy, session_root, resolution = await _turn(db, tmp_path, capability_class="change",
                                                                    device=True)

    assert resolution["status"] == "matched"  # the device prepares and works in its own folder
    assert config.tool_workspace_root == session_root
    assert "run_working_copy" not in config.project_config


@pytest.mark.asyncio
async def test_code_search_with_a_repository_id_reads_the_working_copy_not_a_stored_index(db, tmp_path):
    _config, context, _copy, _session_root, _resolution = await _turn(db, tmp_path, capability_class="change")

    found = await CodeSearchRepositoryTool().execute(
        {"query": "test_slugify_lowercases", "repository_id": "registered-repo-with-a-stale-index"}, context)

    assert not found.get("error"), found
    assert found["total_text_matches"] >= 1, found


@pytest.mark.asyncio
async def test_a_turn_outside_a_run_is_unchanged(db, tmp_path):
    admin = await admin_user(db)
    session_root = tmp_path / "session"
    session_root.mkdir()
    config = await assemble_turn_project_config(
        db=db, user_id=admin.id, project_id=None, user_roles=["admin"], workspace_root=str(session_root),
        session_metadata={}, engineering_runtime_metadata={})

    assert config.tool_workspace_root == session_root.resolve()
    assert "run_working_copy" not in config.project_config


# --- declared working copies ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_missing_declared_run_copy_does_not_silently_become_the_empty_session_root(db, tmp_path):
    # Regression: the turn is held, and even the turn's config assembly —
    # which runs before the execution gate stops the held turn — never hands out the session folder or a base.
    config, _context, _copy, session_root, resolution = await _turn(db, tmp_path, capability_class="read_only",
                                                                    gone=True)

    assert (resolution["status"], resolution["profile_status"]) == ("held", "needs_configuration")
    assert config.tool_workspace_root != session_root, config.tool_workspace_root
    assert config.project_config.get("run_base_sha") is None  # a gone copy is never reported as verified


@pytest.mark.asyncio
async def test_tests_first_writes_and_runs_a_new_test_in_the_copy_and_never_touches_source(db, tmp_path, monkeypatch):
    _config, context, working_copy, session_root, _resolution = await _turn(
        db, tmp_path, capability_class="change", path_rules=TESTS_FIRST_PATH_RULES)
    seen: dict = {}

    async def suite(**kwargs):
        seen["cwd"] = kwargs["cwd"]
        return {"exit_code": 1, "all_green": False, "command": "pytest", "repo_root": str(kwargs["cwd"])}

    monkeypatch.setattr(quality_tools, "_resolve_test_suite_service", lambda: suite)
    new_test = "tests/test_truncate_words.py"
    written = await TOOL_REGISTRY["write_workspace_file"].execute(
        {"path": new_test, "content": "def test_truncate_words():\n    assert False\n"}, context)
    assert not written.get("error"), written
    assert (working_copy / new_test).exists() and not (session_root / new_test).exists()
    await TOOL_REGISTRY["run_test_suite"].execute({"path": new_test}, context)
    assert seen["cwd"] == working_copy
    refused = await TOOL_REGISTRY["write_workspace_file"].execute({"path": "src/x.py", "content": "x"}, context)
    assert _phase_rule_reasons(refused), refused
    assert not (working_copy / "src/x.py").exists()


@pytest.mark.asyncio
async def test_git_reads_the_working_copy(db, tmp_path):
    _config, context, working_copy, _session_root, _resolution = await _turn(db, tmp_path, capability_class="change")
    (working_copy / "src" / "words.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "src/words.py"], cwd=working_copy, check=True)

    diff = await TOOL_REGISTRY["get_git_diff"].execute({"staged": True}, context)

    assert "src/words.py" in str(diff), diff


def test_outside_a_run_a_repository_id_still_reads_its_index():
    from app.services.workflow_runs.phase_workspace import code_index_repository_id

    assert code_index_repository_id({"repository_id": "repo-1"}, {}) == "repo-1"
    assert code_index_repository_id({"repository_id": "repo-1"}, {"run_working_copy": "/x"}) is None


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)
