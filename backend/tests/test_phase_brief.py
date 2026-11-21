"""The phase brief tells the agent what the enforcement points decide before its first call, so it does not spend
its turns on refused test runs, refused reads of the contract and refused test edits."""

from app.services.prompt_catalog.seeds.run import SPECS
from app.services.workflow_runs.octryx.phase_brief import phase_brief


def _contract(phase: dict, environment: dict | None = None) -> dict:
    base = {"title": "Minimal fix", "node_id": "fix", "capability_class": "code_change", "checks": [],
            "path_rules": {"write": [], "create": [], "protect_confirmed_tests": False, "write_tests": False},
            "protected_files": [], "contract_file": "", "allow_contract_change": False, "output": None,
            "how_to_run_tests": "x"}
    return {"phase": {**base, **phase}, "preparation": {"environment": environment} if environment else {}}


def test_a_merged_small_bug_fix_learns_its_command_folder_paths_and_what_the_platform_does_up_front():
    environment = {"source": "environment_file", "test": "npm test", "lint": "npm run lint", "app_folder": "e2e/node"}
    brief = phase_brief(None, _contract({
        "path_rules": {"write": [], "create": ["src/**"], "protect_confirmed_tests": True, "write_tests": True},
        "contract_file": "e2e/node/.octryx/environment.json", "output": "reproduction",
        "pipeline_after": "note", "checks": ["The confirmed tests pass", "No other test fails"]}, environment))
    lines = brief.splitlines()
    assert lines[0] == "Phase 'Minimal fix', in short (the platform enforces exactly this):"
    assert "- Tests: `npm test` in `e2e/node` (also as `cd e2e/node && npm test`, piped into tail or grep)." in lines
    assert "- Lint: `npm run lint` in `e2e/node`." in lines
    assert any(line.startswith("- Shell: test and read-only commands only") for line in lines)
    assert "- New files only under: `src/**`." in lines
    assert any(line.startswith("- Write the failing test yourself") for line in lines)
    assert any("`e2e/node/.octryx/environment.json` is the run's contract" in line for line in lines)
    assert any(line.startswith("- The platform confirms your failing test itself") for line in lines)
    assert any(line.startswith("- After this phase the CI pipeline") for line in lines)
    assert "- At the end the platform checks: The confirmed tests pass; No other test fails." in lines
    assert lines[-1] == "Everything else is in workflow_run_status (detail=true)."


def test_without_a_declared_command_the_brief_names_the_stacks_runners_and_a_read_only_phase_changes_nothing():
    undeclared = phase_brief(None, _contract({}, {"app_folder": "app"}))
    assert "- Tests: this repository declares no test command; run its own runner in `app`:" in undeclared
    assert "- You may change any file of the repository" in undeclared and "Shell:" not in undeclared
    read_only = phase_brief(None, _contract({"capability_class": "read_only", "how_to_run_tests": ""}))
    assert "- Files: this phase changes nothing" in read_only and "pushes" not in read_only


def test_every_brief_text_is_a_catalog_key():
    keys = {spec.key for spec in SPECS}
    assert {f"run.brief.{name}" for name in ("head", "tests_declared", "lint_declared", "tests_undeclared",
                                             "shell_strict", "read_only", "write_paths", "write_any", "create_paths",
                                             "tests_locked", "tests_writable", "contract_file", "platform_confirms",
                                             "platform_pipeline", "platform_push", "checks", "tail")} <= keys


def test_the_system_test_is_named_as_its_own_call_before_the_agent_starts():
    """A system test inside a longer command must not run in the sandbox, where it hangs."""
    environment = {"source": "environment_file", "test": "flutter test", "app_folder": "app",
                   "system_test": "python3 system_test/run_system_test.py"}
    brief = phase_brief(None, _contract({}, environment))
    assert "- System test: run `python3 system_test/run_system_test.py 2>&1 | tail -15` in `app` as its own call." \
        in brief
