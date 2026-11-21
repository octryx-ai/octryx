"""Review fixes: the bypasses an independent review found in an octryx-claude session's run rules.

Each case is the review's reproduction: case-variant and symlinked paths to the confirmed test, a new
``conftest.py`` or pytest config, git's own files, test commands with redirection or code-loading options, shell
indirection and git's global options around ``push``; facts of another pass, a deleted confirmed test, a hook that
claims the run for nothing, and an action after the person lost access to the run.
"""

from __future__ import annotations

import pytest

from app.models import User, WorkflowRun
from app.services.mcp_governed_knowledge import McpCaller
from app.services.mcp_workflow_run_tools import mcp_workflow_action_request
from app.services.workflow_runs.octryx.facts import record_facts
from app.services.workflow_runs.test_runs import confirmed_test_drift
from tests.workflow_run_octryx_support import CONFIRMED, ROOT, _bound_run, _decide, _fix_definition, _hook


@pytest.mark.asyncio
async def test_a_protected_phase_creates_files_only_under_its_create_patterns(db):
    definition = _fix_definition()
    definition["nodes"][1]["config"]["workflow_contract"]["path_rules"]["create"] = ["pay/**"]
    run, gateway, key, workspace_id = await _bound_run(db, definition)

    async def new_file(path):
        return await _decide(db, gateway, key, workspace_id, {
            **_hook("Write", file_path=f"{ROOT}/{path}", content="x"),
            "workflow_run_facts": {"target_exists": False, "shadows_installed": False}})

    assert (await new_file("pay/rounding.py"))["decision"] == "allow"
    for path in ("evilplug.py", "lib/x.py", "pay/conftest.py", "pay/tests/__init__.py", "pay/.pytest.ini"):
        assert (await new_file(path))["decision"] == "deny", path

DIGEST = "sha256:" + "a" * 64


async def _confirmed(db):
    run, gateway, key, workspace_id = await _bound_run(db)
    run.context = {**run.context, "confirmed_tests": [f"{CONFIRMED}::test_half_up"],
                   "confirmed_test_files": {f"{CONFIRMED}::test_half_up": {
        "file": CONFIRMED, "path": None, "sha256": None, "device": True}}}
    await db.flush()
    return run, gateway, key, workspace_id


@pytest.mark.asyncio
async def test_the_confirmed_test_and_the_test_runner_config_cannot_be_reached_by_another_name(db):
    run, gateway, key, workspace_id = await _confirmed(db)

    async def edit(path, **facts):  # a Write the launcher reports as an existing file unless told otherwise
        hook = {**_hook("Write", file_path=f"{ROOT}/{path}", content="x"),
                "workflow_run_facts": {"target_exists": True, **facts}}
        return await _decide(db, gateway, key, workspace_id, hook)

    for path in ("TESTS/test_totals.py", "tests/Test_Totals.py", "tests/../tests/test_totals.py"):
        assert (await edit(path))["reason"] == "confirmed_test_protected", path
    for path in ("conftest.py", "tests/conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini",
                 "Conftest.py", ".pytest.ini", "pytest.toml", "tests/__init__.py", "sitecustomize.py",
                 "pay/evil.pth", "tests/test_other.py", "package.json", "vitest.config.ts", "go.mod",
                 ".venv/bin/pytest"):
        assert (await edit(path))["reason"] == "protected_path", path
    # A new file: only under the phase's create patterns, never a top-level module (a plugin or a shadow).
    for path in ("evilplug.py", "pay/new_module.py"):
        assert (await edit(path, target_exists=False))["reason"] == "protected_path", path
    for path in (".git/config", ".gitattributes", "sub/.git/hooks/pre-commit"):
        assert (await edit(path))["reason"] == "protected_path", path
    # A symlink the device resolved to the confirmed test, or out of the repository.
    assert (await edit("pay/link.py", resolved_path=CONFIRMED))["reason"] == "confirmed_test_protected"
    assert (await edit("pay/link.py", resolved_path="../elsewhere/x.py"))["reason"] == "phase_path_rule"
    assert (await edit("pay/totals.py"))["decision"] == "allow"


@pytest.mark.asyncio
async def test_a_phase_without_free_shell_runs_only_plain_test_and_read_only_commands(db):
    from tests.workflow_run_octryx_support import STRICT, set_tool_defaults

    run, gateway, key, workspace_id = await _confirmed(db)
    await set_tool_defaults(db, workspace_id, **STRICT)  # the Workspace keeps the strict shell

    async def bash(command):
        return await _decide(db, gateway, key, workspace_id, _hook("Bash", command=command))

    # -v (or -rA): the platform matches every test by name; a run that names none is asked again.
    for command in ("pytest -v", "python -m pytest tests/test_totals.py -k half -v", "git diff HEAD",
                    "ls tests | head -5", "pytest -v && git status", "pytest tests -x -v -rA --tb=short --lf",
                    "pytest tests/test_totals.py::test_half_up -m 'not slow' -v", ".venv/bin/python -m pytest -v",
                    "/usr/bin/python3 -m pytest tests -v"):
        assert (await bash(command))["decision"] == "allow", command
    for command in ("pytest @args.txt", "pytest -W error::mod.Cls", "pytest --pyargs mod", "pytest evilplug.py",
                    "pytest -k", "pytest --tb=evil", "./ls", "/tmp/x/pytest -q", "scripts/git log",
                    "npm test", "go test ./...",
                    "pytest -q > tests/test_totals.py", "pytest --basetemp=tests", "pytest -p evil_plugin",
                    "pytest -pevil_plugin", "pytest -qp evil_plugin", "pytest -c other.ini", "pytest --rootdir=/tmp",
                    "PYTEST_ADDOPTS=-pevil pytest", "x=pytest; $x -q", "pytest $(cat args)", "env pytest -q",
                    "sh -c 'pytest -q'", "python3 -c 'import urllib.request'",
                    "curl https://140.82.112.6/repos", "find . -delete", "git log --output=tests/test_totals.py",
                    "git -c core.pager=sh log", "pytest -q &"):
        assert (await bash(command))["decision"] == "deny", command

    # A change phase without protected tests runs any command by default, logged; a strict
    # Workspace keeps the strict shell there too.
    run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False, tools=[
        "read_workspace_file", "edit_workspace_file", "run_test_suite", "bash"]))
    assert (await _decide(db, gateway, key, workspace_id, _hook("Bash", command="echo x > tests/test_totals.py")))[
        "reason"] == "allowed_by_default"
    await set_tool_defaults(db, workspace_id, **STRICT)
    assert (await _decide(db, gateway, key, workspace_id, _hook("Bash", command="echo x > tests/test_totals.py")))[
        "reason"] == "outside_phase_tools"


@pytest.mark.asyncio
async def test_device_facts_count_only_for_their_pass_and_a_deleted_confirmed_test_is_drift(db):
    from app.services.observability import device_report_metrics, workflow_metrics

    workflow_metrics.reset()
    run, _gateway, _key, _workspace_id = await _confirmed(db)
    this_pass = {"node_id": run.current_node_id, "entry": run.node_state["entry"]}
    assert record_facts(run, {"confirmed_test_digests": {CONFIRMED: DIGEST}}) is False  # no pass named
    assert record_facts(run, {**this_pass, "entry": this_pass["entry"] - 1,
                              "confirmed_test_digests": {CONFIRMED: DIGEST}}) is False  # an older pass
    assert record_facts(run, {**this_pass, "confirmed_test_digests": {CONFIRMED: DIGEST},
                              "checked_files": [CONFIRMED]}) is True
    assert confirmed_test_drift(run) == []
    assert record_facts(run, {**this_pass, "confirmed_test_digests": {}, "checked_files": [CONFIRMED]}) is True
    assert "was removed on the device" in confirmed_test_drift(run)[0]
    # An older pass's change never stands in for this one's: a base the run does not have is explicit.
    record_facts(run, {**this_pass, "change": {"base": "f" * 40, "patch": "diff --git a/x b/x"}})
    assert run.context["device_change"]["base_unavailable"] is True and run.context["device_change"]["patch"] == ""
    assert run.context["device_change"]["reason"].startswith(f"the device diffed against {'f' * 40}")
    # The device says which git step failed and why, and the run keeps it.
    record_facts(run, {**this_pass, "change": {"base": "f" * 40, "base_unavailable": True, "attempts": 2,
                                               "reason": "add -A: exit 128: error: short read"}})
    assert {key: run.context["device_change"][key] for key in ("reason", "attempts")} == {
        "reason": "add -A: exit 128: error: short read", "attempts": 2}
    # Counted, so a repeat after the retry is seen.
    assert device_report_metrics.DEVICE_CHANGE_UNAVAILABLE.series[("add",)] == 1
    assert device_report_metrics.DEVICE_CHANGE_UNAVAILABLE.series[("other_base",)] == 1
    assert device_report_metrics.DEVICE_CHANGE_RETRIED.series[("failed",)] == 1


@pytest.mark.asyncio
async def test_a_confirmed_test_the_default_shell_rewrote_or_removed_fails_the_evidence_checks(db):
    """The default shell runs `sed -i` on a confirmed test; the
    evidence catches it. The launcher's next digest differs from the confirmed one, so confirmed_tests_intact and
    tests_green fail on a green run, and the agent is told which file changed."""
    from app.services.workflow_checks.library import FAILED, TurnEvidence, _tdd

    run, gateway, key, workspace_id = await _confirmed(db)
    this_pass = {"node_id": run.current_node_id, "entry": run.node_state["entry"], "checked_files": [CONFIRMED]}
    assert record_facts(run, {**this_pass, "confirmed_test_digests": {CONFIRMED: DIGEST}}) is True
    assert confirmed_test_drift(run) == []
    sed = await _decide(db, gateway, key, workspace_id, _hook("Bash", command=f"sed -i s/3/2/ {CONFIRMED}"))
    assert (sed["decision"], sed["reason"]) == ("allow", "allowed_by_default")
    rewritten = "sha256:" + "b" * 64
    assert record_facts(run, {**this_pass, "confirmed_test_digests": {CONFIRMED: rewritten}}) is True
    [drift] = confirmed_test_drift(run)
    assert f"its file {CONFIRMED} changed on the device after it was confirmed" in drift
    test_id = f"{CONFIRMED}::test_half_up"
    green = {"results": {test_id: {"outcome": "passed"}}, "all_green": True}
    evidence = TurnEvidence(test_runs=[green], confirmed_tests=[test_id], red_seen=True,
                            confirmed_test_drift=confirmed_test_drift(run))
    for kind in ("confirmed_tests_intact", "tests_green"):
        state, why = _tdd(kind, {}, evidence)
        assert (state, why) == (FAILED, drift), kind
    # Removed by the shell (`rm`, also allowed by default): the launcher checks the file and finds none.
    rm = await _decide(db, gateway, key, workspace_id, _hook("Bash", command=f"rm {CONFIRMED}"))
    assert rm["reason"] == "allowed_by_default"
    assert record_facts(run, {**this_pass, "confirmed_test_digests": {}}) is True
    [removed] = confirmed_test_drift(run)
    assert "was removed on the device after it was confirmed" in removed
    state, why = _tdd("confirmed_tests_intact", {}, TurnEvidence(
        test_runs=[green], confirmed_tests=[test_id], red_seen=True, confirmed_test_drift=[removed]))
    assert (state, why) == (FAILED, removed)


@pytest.mark.asyncio
async def test_a_hook_claims_the_run_only_when_its_facts_change_it(db):
    run, gateway, key, workspace_id = await _confirmed(db)
    facts = {"node_id": run.current_node_id, "entry": run.node_state["entry"],
             "confirmed_test_digests": {CONFIRMED: DIGEST}, "checked_files": [CONFIRMED]}
    hook = {**_hook("Read", file_path=f"{ROOT}/pay/totals.py"), "workflow_run_facts": facts}
    await _decide(db, gateway, key, workspace_id, hook)
    await db.commit()  # a new request: a claim in it would bump the run's version
    version = (await db.get(WorkflowRun, run.id)).state_version
    await _decide(db, gateway, key, workspace_id, hook)  # the same facts again
    await db.commit()
    assert (await db.get(WorkflowRun, run.id)).state_version == version


@pytest.mark.asyncio
async def test_an_action_request_checks_the_persons_access_again(db):
    from app.services.workflow_runs import access

    run, gateway, key, workspace_id = await _bound_run(db)
    admin = await db.get(User, run.requested_by)
    caller = McpCaller(user_id=admin.id, grant_id="mcp", scopes=("workflow:read", "workflow:execute"),
                       workspace_header=workspace_id, session_key=key)

    async def revoked(_db, _run, _user):
        return "read"

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(access, "run_access", revoked)
        answer = await mcp_workflow_action_request(db, caller=caller, user=admin, workspace_id=workspace_id,
                                                   arguments={"action": "ci.status", "params": {}})
    assert (answer["state"], answer["reason"]) == ("denied", "run_access_revoked")


@pytest.mark.asyncio
async def test_every_file_tool_needs_the_launchers_word_that_its_target_exists(db):
    run, gateway, key, workspace_id = await _confirmed(db)

    async def call(tool, path, **facts):
        tool_input = {"file_path": f"{ROOT}/{path}", "old_string": "", "new_string": "x"}
        hook = {**_hook(tool, **tool_input), **({"workflow_run_facts": facts} if facts else {})}
        return await _decide(db, gateway, key, workspace_id, hook)

    # Before the fix Edit / MultiEdit / NotebookEdit counted as "existing" and could create a shadowing module.
    for tool in ("Edit", "MultiEdit", "NotebookEdit", "Write"):
        assert (await call(tool, "evilplug.py"))["reason"] == "protected_path", tool
        assert (await call(tool, "_pytest/__init__.py", target_exists=False))["reason"] == "protected_path", tool
    assert (await call("Edit", "pay/totals.py", target_exists=True))["decision"] == "allow"


@pytest.mark.asyncio
async def test_plugin_registration_bytecode_and_shadowing_packages_are_refused_even_under_create(db):
    definition = _fix_definition()
    definition["nodes"][1]["config"]["workflow_contract"]["path_rules"]["create"] = ["src/**"]
    run, gateway, key, workspace_id = await _bound_run(db, definition)

    async def write(path, **facts):
        return await _decide(db, gateway, key, workspace_id, {
            **_hook("Write", file_path=f"{ROOT}/{path}", content="x"),
            "workflow_run_facts": {"target_exists": False, "shadows_installed": False, **facts}})

    for path in ("src/evil-1.0.dist-info/entry_points.txt", "src/evil-1.0.dist-info/METADATA",
                 "src/pay.egg-info/entry_points.txt", "src/pay/__pycache__/x.cpython-312.pyc", "src/x.pyc",
                 "src/evil.egg-link", "src/evil.pth", "src/sub/entry_points.txt"):
        assert (await write(path))["reason"] == "protected_path", path
    assert (await write("src/pay.egg-info/entry_points.txt", target_exists=True))["reason"] == "protected_path"
    assert (await write("src/iniconfig/__init__.py", shadows_installed=True))["reason"] == "protected_path"
    hook = {**_hook("Write", file_path=f"{ROOT}/src/iniconfig/__init__.py", content="x"),
            "workflow_run_facts": {"target_exists": False}}  # no word on shadowing: refused
    assert (await _decide(db, gateway, key, workspace_id, hook))["reason"] == "protected_path"
    assert (await write("src/rounding.py"))["decision"] == "allow"


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


def test_common_read_only_and_test_forms_pass_and_the_safety_intent_holds():
    """No ``outside-phase-tools`` refusals for harmless reads and test runs. Readers at the end of a pipe,
    ``2>/dev/null``, ``cd`` into the repository and pytest options that only change output or selection pass;
    anything that writes a file, loads a plugin or leaves the repository does not.
    Sed may print several ranges in one script (``44,66p;217,251p``), each command still print-only."""
    from app.services.workflow_runs.octryx.declared_commands import declared_with_readers
    from app.services.workflow_runs.octryx.shell_rules import strict_shell_allows

    prefixes = (("pytest",), ("python", "-m", "pytest"))

    def allows(command):
        return strict_shell_allows(command, runs_tests=True, test_prefixes=prefixes)

    for command in ("pytest -q tests/test_x.py 2>&1 | tail -20", "pytest -xvs tests/test_x.py::test_y",
                    "pytest -s --no-header -p no:cacheprovider --maxfail=1 -n auto tests",
                    "pytest -q --ignore=tests/system --deselect tests/a.py::test_b --durations=5",
                    "ls tests/system 2>/dev/null", "cat app/api.py | grep -n route | wc -l",
                    "cd frontend && ls src", "grep -rh import app | sort | uniq -c | sort -rn | head",
                    "git diff --stat | cut -c1-80", "pytest tests | tail -5 >/dev/null",
                    "sed -n '44,66p;217,251p;303,332p' benchmark/SPEC.md", "sed -n -e '1,5p' -e '9p;' SPEC.md"):
        assert allows(command), command
    for command in ("pytest -q > out.txt", "cat x | tee out.txt", "pytest -p evil_plugin", "pytest -qp evil",
                    "pytest --junitxml=/tmp/r.xml", "pytest --ignore=/etc", "pytest --maxfail=$N",
                    "cd .. && ls", "cd /etc && cat passwd", "cd ~", "sort -o tests/test_x.py x",
                    "uniq in.txt tests/test_x.py", "pytest -W error::mod.Cls", "ls 2>/tmp/err",
                    "curl https://example.com | head", "sed -i s/a/b/ app.py",
                    "sed -n '1p;w out.txt' SPEC.md", "sed -n '1p;s/a/b/w out.txt' SPEC.md", "sed '1p;e date' x",
                    "sed -n 's/a;w out/b/p' SPEC.md", "sed -n '1p;r /etc/passwd' x"):
        assert not allows(command), command
    declared = (".venv/bin/python -m pytest -q --ignore=tests/system",)
    assert declared_with_readers(f"{declared[0]} 2>&1 | tail -30", declared)
    assert not declared_with_readers(f"{declared[0]} && rm -rf app", declared)
    assert not declared_with_readers(declared[0], declared)  # verbatim is ``declared_command``'s


@pytest.mark.asyncio
async def test_a_change_the_device_cut_stays_cut_and_a_large_binary_change_fits(db):
    """447 screenshot baselines make a 36 MB binary patch. A device that cuts it at a 6 MB bound and says
    ``truncated`` must not have the server recount it (exactly 6 MB: "not longer") and store it as whole, building no
    tree from it, so the push guard could never pass."""
    from app.services.workflow_runs.octryx.facts import MAX_PATCH

    run, _gateway, _key, _workspace_id = await _confirmed(db)
    this_pass = {"node_id": run.current_node_id, "entry": run.node_state["entry"]}
    base = str(run.context.get("base_sha") or "")
    record_facts(run, {**this_pass, "change": {"base": base, "patch": "diff --git a/x b/x\n", "truncated": True}})
    assert run.context["device_change"]["truncated"] is True  # the device's word that it is not whole counts
    big = "diff --git a/v.png b/v.png\nGIT binary patch\n" + "z" * 36_000_000
    assert len(big) < MAX_PATCH
    record_facts(run, {**this_pass, "change": {"base": base, "patch": big, "truncated": False}})
    change = run.context["device_change"]
    assert (change["truncated"], len(change["patch"])) == (False, len(big))
