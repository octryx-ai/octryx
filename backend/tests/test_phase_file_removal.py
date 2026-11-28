"""A changing phase may delete single files of its repository (if rm, git rm and unlink were all refused, a module
split would leave the old file behind). Each path follows the phase's path rules like an edit."""

from __future__ import annotations

import pytest

from app.services.workflow_runs.octryx.removal_rules import removal_paths
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_support import CONFIRMED, ROOT, _bound_run, _decide, _fix_definition, _hook

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


def test_only_a_plain_single_rm_or_git_rm_of_named_files_counts_as_a_removal():
    assert removal_paths("rm src/packmate/api.py") == ["src/packmate/api.py"]
    assert removal_paths("git rm -q src/a.py src/b.py") == ["src/a.py", "src/b.py"]
    assert removal_paths("rm -f src/a.py") == ["src/a.py"]
    # Undoing a change in the wrong app is restoring named files.
    assert removal_paths("git restore src/packmate/models.py src/packmate/router.py") == [
        "src/packmate/models.py", "src/packmate/router.py"]
    assert removal_paths("git checkout -- src/packmate/models.py") == ["src/packmate/models.py"]
    for command in ("rm -rf src", "rm -r src", "rm src/*.py", "rm", "rm a.py && ls", "rm $X", "unlink a.py",
                    "git rm -r src", "find . -delete", "git restore .", "git restore src/*.py", "git checkout main",
                    "git checkout -b x", "git restore --source=HEAD~3 a.py", "git checkout -- ."):
        assert removal_paths(command) is None, command


@pytest.mark.asyncio
async def test_a_changing_phase_removes_repository_files_but_never_a_protected_one(db):
    _run, gateway, key, workspace_id = await _bound_run(db)

    async def bash(command: str) -> dict:
        return await _decide(db, gateway, key, workspace_id, _hook("Bash", command=command))

    assert (await bash("rm pay/old_totals.py"))["decision"] == "allow"
    assert (await bash("git rm -q pay/old_totals.py"))["decision"] == "allow"
    # The default shell removes a confirmed test: the evidence catches it
    # (test_workflow_run_octryx_hardening::...rewrote_fails_the_evidence_checks); the hard core stays refused.
    assert (await bash(f"rm {CONFIRMED}"))["reason"] == "allowed_by_default"
    assert (await bash("rm .git/config"))["reason"] == "protected_path"
    assert (await bash("rm .venv/bin/python"))["reason"] == "protected_path"
    assert (await bash("rm /etc/hosts"))["decision"] == "deny"
    assert (await bash("rm -rf pay"))["reason"] == "outside_phase_tools"  # recursion stays refused
    assert (await bash("git restore pay/old_totals.py"))["decision"] == "allow"
    assert (await bash("git checkout -- pay/old_totals.py"))["decision"] == "allow"
    assert (await bash("git restore .git/config"))["reason"] == "protected_path"


@pytest.mark.asyncio
async def test_a_phase_without_write_tools_removes_nothing(db):
    _run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(tools=["read_workspace_file",
                                                                                   "run_test_suite"]))
    answer = await _decide(db, gateway, key, workspace_id, _hook("Bash", command="rm pay/old_totals.py"))
    assert answer["decision"] == "deny" and answer["reason"] == "outside_phase_tools"
    assert ROOT  # the bound repository root of the helpers


def test_a_recursive_removal_names_folders_only_in_a_plain_single_command():
    from app.services.workflow_runs.octryx.removal_rules import generated_dir, recursive_removal_paths

    assert recursive_removal_paths("rm -rf src/kitchen-helper.egg-info") == ["src/kitchen-helper.egg-info"]
    assert recursive_removal_paths("git rm -r -q src/kitchen-helper.egg-info/") == ["src/kitchen-helper.egg-info"]
    for command in ("rm src/a.py", "rm -rf .", "rm -rf ../x", "rm -rf /tmp/x", "rm -rf src/*", "rm -rf .git/hooks",
                    "rm -rf a && ls", "rm -rf"):
        assert recursive_removal_paths(command) is None, command
    assert generated_dir("src/kitchen-helper.egg-info") and generated_dir("web/__pycache__") and not generated_dir("src")


@pytest.mark.asyncio
async def test_a_changing_phase_removes_a_generated_folder_but_no_other_folder_outside_its_paths(db):
    _run, gateway, key, workspace_id = await _bound_run(db)

    async def bash(command: str) -> dict:
        return await _decide(db, gateway, key, workspace_id, _hook("Bash", command=command))

    assert (await bash("rm -rf src/kitchen-helper.egg-info"))["decision"] == "allow"
    assert (await bash("git rm -r -q build"))["decision"] == "allow"
    assert (await bash("rm -rf pay"))["reason"] == "outside_phase_tools"  # a source folder, no path rule covers it
    assert (await bash("rm -rf /etc/x.egg-info"))["decision"] == "deny"


def test_an_item_removes_a_folder_wholly_inside_its_own_paths():
    from app.services.workflow_runs.octryx.removal_rules import _folder_decision

    phase = {"title": "Work · ui", "tools": {"allow": ["edit_workspace_file"]},
             "path_rules": {"write": ["web/**", "src/kitchen-helper/*.py"]}}
    root = "/repo/.octryx-items/ui"
    assert _folder_decision(phase, ["web/old"], root, root) is None
    assert _folder_decision(phase, ["src/kitchen-helper/old"], root, root).reason == "outside_phase_tools"  # *.py only
    assert _folder_decision(phase, ["src/kitchen-helper.egg-info"], root, root) is None  # generated
