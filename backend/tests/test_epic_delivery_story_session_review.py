"""Story session heredocs, subagent messages and temp-folder writes are classified safely, and the review reads every reported change."""

from __future__ import annotations

import copy

import pytest


def test_a_heredoc_that_writes_a_file_is_data_and_one_a_shell_reads_is_commands():
    """``cat > conftest.py <<'EOF'`` with ``server.shutdown()`` in the file is not refused as destructive, and a 7K
    JavaScript module and a 34K Python data script written by heredocs are not refused as unparseable; each refusal
    would cost the session a retry."""
    from app.services.agent_gateway.capability import _destructive
    from app.services.agent_gateway.command_match import command_segments
    from app.services.exec_policy.policy_config import DEFAULT_EXEC_POLICY_CONFIG

    patterns = DEFAULT_EXEC_POLICY_CONFIG["always_deny_patterns"]

    conftest = "cd tests && cat > conftest.py <<'EOF'\nimport x\n\ndef stop(server):\n    server.shutdown()\nEOF"
    assert not _destructive(conftest, list(patterns))
    module = "cat > search.js <<'EOF'\n" + "export const a = 'it''s'; // don't\n" * 400 + "EOF"
    assert command_segments(module) == [("cat",)]
    script = "python3 - <<'EOF'\n" + "print({'a': [1, 2]}); x = \"(\" ; y = 'z' ; w = 1 | 2\n" * 900 + "EOF"
    assert command_segments(script) == [("python3", "-")]
    assert _destructive("sudo shutdown -h now", list(patterns)) and _destructive("cd / && reboot", list(patterns))
    assert _destructive("shutdown -h now", list(patterns))
    assert not _destructive('python -c "s = make_server(0); s.shutdown()"', list(patterns))
    assert _destructive("bash <<'EOF'\nshutdown -h now\nEOF", list(patterns))  # a shell reads it: commands
    assert _destructive("cat <<'EOF' | sh\nreboot\nEOF", list(patterns))
    assert ("rm", "-rf", "x") in command_segments("bash <<EOF\nrm -rf x\nEOF")


@pytest.mark.asyncio
async def test_the_story_session_may_message_its_subagents_and_write_in_claudes_temp_folder(db, monkeypatch):
    """SendMessage (continuing a subagent) is not refused as unclassified, nor are Writes into Claude Code's own temp
    folder as outside the repository; the free shell writes there anyway."""
    from tests.server_build_lock import lift_server_build_lock
    from tests.workflow_run_octryx_support import _bound_run, _decide, _fix_definition, _hook

    lift_server_build_lock(monkeypatch)
    free = copy.deepcopy(_fix_definition(protect=False))
    next(node for node in free["nodes"] if node["id"] == "fix")["config"].update(shell="free", subagents=True)
    _run, gateway, key, workspace_id = await _bound_run(db, free)

    async def decided(tool, **tool_input):
        return (await _decide(db, gateway, key, workspace_id, _hook(tool, **tool_input)))["decision"]

    assert await decided("SendMessage", to="a589", message="fix the empty state") == "allow"
    assert await decided("Write", file_path="/tmp/claude-502/oe29-contract.md", content="x") == "allow"
    assert await decided("Write", file_path="/private/tmp/claude-502/corpus/a.json", content="x") == "allow"
    assert await decided("Write", file_path="/tmp/claude-502/../../etc/x", content="x") == "deny"
    assert await decided("Write", file_path="/tmp/other/x", content="x") == "deny"
    _run, gateway, key, workspace_id = await _bound_run(db, _fix_definition(protect=False))
    strict = await _decide(db, gateway, key, workspace_id, _hook("Write", file_path="/tmp/claude-502/x", content="x"))
    assert strict["decision"] == "deny"  # a phase without the free shell keeps the repository boundary


def test_the_review_takes_every_change_the_device_may_report():
    """A story of several hundred thousand characters does not pause at review_no_decision; the review reads a large
    change in parts, so its bound is the device patch's runaway guard, not a cut of a real story."""
    from app.services.workflow_runs.octryx.facts import MAX_PATCH
    from app.services.workflow_runs.review.evidence import MAX_DIFF
    from app.services.workflow_runs.review.reading import change_parts

    assert MAX_DIFF >= MAX_PATCH
    change = "".join(f"diff --git a/f{i} b/f{i}\n" + "+x\n" * 20_000 for i in range(7))
    assert len(change) > 400_000 and "".join(change_parts(change, 100_000)) == change


def test_a_file_a_heredoc_writes_is_no_credential_read():
    """``cat > paths.py <<'EOF' ... return Path(env) ... EOF`` is not refused as an environment dump. A shell's own
    heredoc and a plain ``env`` are still refused."""
    from app.services.workflow_runs.octryx.hard_deny import hard_denied

    module = "mkdir -p src && cat > src/paths.py <<'EOF'\ndef home():\n    env = os.environ.get('X')\n" \
             "    return Path(env) if env else Path.home() / '.netrc'\nEOF"
    assert hard_denied(module) is None
    assert hard_denied("env | grep -i proxy") is not None
    assert hard_denied("bash <<'EOF'\nenv\nEOF") is not None
    assert hard_denied("cat ~/.netrc") is not None


@pytest.mark.asyncio
async def test_the_review_reads_text_in_full_and_binaries_and_lockfiles_as_one_line(tmp_path):
    """``--text`` would put hundreds of PNG baselines into the reviewed diff (tens of MB) and the review would refuse
    the change as too large though its text part is small. The tree stays the whole change."""
    import subprocess
    from types import SimpleNamespace

    from app.services.workflow_runs import safe_git
    from app.services.workflow_runs.review.evidence import change_under_review

    def git(*args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=tmp_path,
                              check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    (tmp_path / "README.md").write_text("old\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD")
    (tmp_path / "README.md").write_text("new line\n")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 400)
    (tmp_path / "app" / "package-lock.json").write_text('{"lockfileVersion": 3}\n' * 50)
    (tmp_path / "app" / "main.js").write_text("console.log('hi');\n")
    diff, tree = await change_under_review(SimpleNamespace(context={"base_sha": base}), tmp_path)
    assert "+new line" in diff and "console.log('hi')" in diff
    assert "binary file changed: app/shot.png" in diff and "PNG" not in diff.split("# Files shown")[0]
    assert "lockfile changed: app/package-lock.json (+50 -0 lines)" in diff and "lockfileVersion" not in diff
    assert tree == await safe_git.staged_tree(tmp_path)  # the pushed tree is the whole change
