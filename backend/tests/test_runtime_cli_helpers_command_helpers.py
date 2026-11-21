from pathlib import Path

from app.tools.runtime_impl import _runtime_cli_helpers as helpers


def test_contains_shell_control_operators_detects_operators_and_subshells():
    assert helpers._contains_shell_control_operators("echo hi && pwd")
    assert helpers._contains_shell_control_operators("pwd; git status")
    assert helpers._contains_shell_control_operators("echo $(pwd)")
    assert not helpers._contains_shell_control_operators("git status")


def test_command_likely_writes_workspace_matches_known_mutating_commands():
    assert helpers._command_likely_writes_workspace(["git", "commit"])
    assert helpers._command_likely_writes_workspace(["npm", "install"])
    assert helpers._command_likely_writes_workspace(["gradle", "spotlessApply"])
    assert not helpers._command_likely_writes_workspace(["git", "status"])
    assert not helpers._command_likely_writes_workspace(["rg", "needle"])


def test_command_resolution_error_reports_ambiguous_script_candidates():
    resolution = {
        "script": "build.sh",
        "candidate_count": 2,
        "candidates": ["repo-a/build.sh", "repo-b/build.sh"],
    }

    result = helpers._command_resolution_error(
        command="./build.sh",
        cwd=Path("/workspace"),
        resolution=resolution,
    )

    assert result == {
        "error": (
            "Referenced script `build.sh` is ambiguous across the allowed workspace context. "
            "Specify the repository or cwd explicitly. Candidates: repo-a/build.sh, repo-b/build.sh"
        ),
        "command": "./build.sh",
        "cwd": "/workspace",
        "script_resolution": resolution,
    }


def test_command_resolution_error_reports_ambiguous_repository_candidates():
    resolution = {
        "repo_resolution": {
            "candidate_count": 2,
            "repo_candidates": ["/workspace/repo-a", "/workspace/repo-b"],
        }
    }

    result = helpers._command_resolution_error(
        command="npm test",
        cwd=Path("/workspace"),
        resolution=resolution,
    )

    assert result == {
        "error": (
            "Command matches multiple allowed repositories. Specify the repository or cwd explicitly."
            " Candidates: /workspace/repo-a, /workspace/repo-b"
        ),
        "command": "npm test",
        "cwd": "/workspace",
        "script_resolution": resolution,
    }
