"""The repository environment file's commands reach the phase's shell rules (otherwise the fix phase refuses
`flutter test` because the server never sees the file's declared test command)."""

from app.services.workflow_runs.octryx.declared_commands import declared_command, declared_commands
from app.services.workflow_runs.workspace.gateway import _clean
from app.services.workflow_runs.workspace.preparation import file_commands

SPEC = {"source": "environment_file", "environment_file": "coffee/flutter/claude/.octryx/environment.json",
        "app_folder": "coffee/flutter/claude", "test": "", "lint": "", "setup": [], "path": []}


def _report(commands: dict) -> dict:
    return _clean({"environment": {"state": "environment_file", "environment_file": {
        "file": "coffee/flutter/claude/.octryx/environment.json", "state": "ok", "commands": commands}}})


def test_the_files_declared_commands_are_the_phases_declared_commands():
    environment = file_commands(SPEC, _report({"test": "flutter test", "lint": "flutter analyze --no-pub"}))
    assert environment["test"] == "flutter test" and environment["lint"] == "flutter analyze --no-pub"
    declared = declared_commands(environment)
    assert declared_command("flutter test", declared) and declared_command("flutter analyze --no-pub", declared)
    assert not declared_command("flutter pub get", declared)


def test_without_a_report_or_for_another_source_nothing_changes():
    assert file_commands(SPEC, {}) == SPEC
    other = {**SPEC, "source": "declared", "test": "pytest"}
    assert file_commands(other, _report({"test": "flutter test"})) == other


def test_a_refused_command_in_the_file_drops_every_command():
    environment = file_commands(SPEC, _report({"test": "sudo flutter test", "lint": "flutter analyze"}))
    assert environment == SPEC and declared_commands(environment) == ()
