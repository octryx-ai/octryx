"""A plain shell read counts as read evidence (Claude Code and Codex)."""

from __future__ import annotations

import pytest

from app.models import Session
from app.services.agent_gateway.read_evidence import native_read_use, read_target
from app.services.agent_gateway.shell_read import shell_read
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import admin_user
from tests.workflow_run_runtime_evidence_support import ROOT, _device_session, _native


@pytest.mark.parametrize(("command", "tool", "path"), [
    ("cat src/app.py", "read_workspace_file", "src/app.py"),
    ("/bin/zsh -lc 'cat src/app.py'", "read_workspace_file", "src/app.py"),  # how Codex runs a command
    ("sed -n '1,80p' README.md", "read_workspace_file", "README.md"),
    ("head -n 20 src/app.py | wc -l", "read_workspace_file", "src/app.py"),
    ("rg -n 'def wrap' src", "grep_workspace", "src"),
    ("grep -rn wrap .", "grep_workspace", "."),
    ("ls -la", "list_workspace_directory", "."),
    ("find src -name '*.py'", "glob_workspace_files", "src"),
    ("cat README.md && ls tests", "read_workspace_file", "README.md"),
    ("ls -la src && cat README.md", "read_workspace_file", "README.md"),
    ("find . -name '*.py' && rg -n wrap src", "grep_workspace", "src"),
])
def test_plain_reads_inside_the_repository(command, tool, path):
    found = shell_read(command, ROOT, ROOT)
    assert found == {"read_tool": tool, "in_root": True, "path": path}


@pytest.mark.parametrize("command", [
    "cat x > y",
    "cat x >> y",
    "cat x | tee y",
    "sed -i 's/a/b/' x",
    "sed -n '1p;w out' x",
    "find . -delete",
    r"find . -exec rm {} \;",
    "cat $(echo x)",
    "cat $HOME/x",
    "cd src && cat app.py",            # cd changes what the paths mean
    "FOO=1 cat x",
    "env cat x",
    "python -c 'print(open(\"x\").read())'",
    "pytest -q",
    "cat 'unbalanced",
])
def test_anything_else_is_no_read(command):
    assert shell_read(command, ROOT, ROOT) is None


@pytest.mark.parametrize("command", ["cat /etc/hosts", "cat ../other/secret.py", "ls /", f"cat {ROOT}-evil/x.py",
                                     "cat src/app.py /etc/hosts"])
def test_a_read_outside_the_repository_is_no_evidence(command):
    assert shell_read(command, ROOT, ROOT)["in_root"] is False


def test_the_hook_target_of_a_shell_read():
    session = Session(metadata_={"repository_binding": {"root": ROOT}})
    target = read_target(session, {"tool_name": "Bash", "tool_input": {"command": "cat src/app.py"}, "cwd": ROOT})
    assert target == {"tool": "Bash", "read_tool": "read_workspace_file", "in_root": True, "path": "src/app.py"}
    assert read_target(Session(metadata_={}), {"tool_name": "Bash", "tool_input": {"command": "cat a.py"},
                                               "cwd": ROOT})["in_root"] is False


@pytest.mark.asyncio
async def test_a_shell_read_counts_only_with_the_hook_the_transcript_and_a_path_in_the_repository(db):
    admin = await admin_user(db)
    gateway, _key = await _device_session(db, admin, await seed_workspace(db))
    read = await _native(db, gateway, "Bash", {"command": "cat textkit/core.py"})
    use = native_read_use(read[0])
    assert use.succeeded is True and use.name == "read_workspace_file"
    assert native_read_use((await _native(db, gateway, "Bash", {"command": "rg -n wrap textkit"}))[0]).name == (
        "grep_workspace")

    not_in_transcript = await _native(db, gateway, "Bash", {"command": "cat textkit/core.py"}, transcript=False)
    claimed = await _native(db, gateway, "Bash", {"command": "cat textkit/core.py"}, hook=None)
    outside = await _native(db, gateway, "Bash", {"command": "cat /etc/hosts"})
    failed = await _native(db, gateway, "Bash", {"command": "cat missing.py"}, hook="PostToolUseFailure")
    for rows in (not_in_transcript, claimed, outside, failed):
        use = native_read_use(rows[0])
        assert use is None or use.succeeded is False
    for command in ("cat x > y", "cat textkit/core.py | tee copy.py", "pytest -q"):
        assert native_read_use((await _native(db, gateway, "Bash", {"command": command}))[0]) is None
