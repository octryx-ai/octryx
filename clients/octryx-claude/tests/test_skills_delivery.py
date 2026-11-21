"""Catalog skills in a governed session — verified blobs, a read-only per-session plugin, usage, cleanup."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import time
from pathlib import Path

import httpx
import pytest

from octryx_claude import cli, launch, launch_process, launch_settings, skill_hooks, skills
from octryx_claude.platform import PlatformResult, SessionContext

from .conftest import BASE_URL

KEY = "00000000-0000-4000-8000-000000000123"
SKILL_MD = ("---\nname: style-guide\ndescription: Write HCL in the house style.\nmetadata:\n"
            "  octryx-version: '1'\n---\n\n"
            "# Style guide\n")
REFERENCE = "# Naming\n"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _manifest(skill_md: str = SKILL_MD, **overrides) -> dict:
    files = [{"path": "SKILL.md", "sha256": _sha(skill_md), "size": len(skill_md)},
             {"path": "references/naming.md", "sha256": _sha(REFERENCE), "size": len(REFERENCE)}]
    skill = {"name": "style-guide", "version": 1, "files": files, "bundle_digest": skills.bundle_digest(files),
             "scripts_withheld": ["scripts/fmt.sh"]}
    skill.update(overrides)
    return {"state": "allowed", "plugin": "octryx", "workspace_id": "ws-1", "skills": [skill],
            "mcp_servers": [{"name": "terraform", "server": {"command": "docker", "args": [
                "run", "-i", "--rm", "-e", "TFE_TOKEN", "hashicorp/terraform-mcp-server@sha256:" + "d" * 64],
                "env": {}}}],
            "withheld": [], "manifest_digest": "sha256:" + "a" * 64}


def _client(manifest: dict, blobs: dict[str, str], seen: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/skills/manifest"):
            return httpx.Response(200, json=manifest)
        sha = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"state": "allowed", "sha256": sha, "content": blobs.get(sha, "")})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _context() -> SessionContext:
    return SessionContext(BASE_URL, KEY, "ws-1")


def test_the_plugin_is_written_read_only_next_to_the_state_root_and_blobs_are_cached(state):
    blobs = {_sha(SKILL_MD): SKILL_MD, _sha(REFERENCE): REFERENCE}
    seen: list[str] = []
    delivery = skills.prepare(state, _context(), http=_client(_manifest(), blobs, seen))
    assert delivery.state == "delivered" and delivery.skills == ("style-guide",)
    plugin = delivery.plugin_dir
    assert plugin == state.root.parent / "octryx-skill-plugins" / KEY / "octryx"
    assert state.root not in plugin.parents  # the credential deny rules stay whole
    assert json.loads((plugin / ".claude-plugin" / "plugin.json").read_text())["name"] == "octryx"
    skill_file = plugin / "skills" / "style-guide" / "SKILL.md"
    assert skill_file.read_text() == SKILL_MD
    assert stat.S_IMODE(skill_file.stat().st_mode) == 0o444
    assert stat.S_IMODE((plugin / "skills" / "style-guide").stat().st_mode) == 0o555
    assert not (plugin / "skills" / "style-guide" / "scripts").exists()
    assert delivery.mcp_servers["terraform"]["args"][-1].endswith("@sha256:" + "d" * 64)
    assert sum(path.startswith("/api/v1/agent-gateway/skills/blobs/") for path in seen) == 2
    again: list[str] = []
    skills.prepare(state, _context(), http=_client(_manifest(), blobs, again))
    assert not [path for path in again if "/blobs/" in path]  # served from the verified cache
    cached = state.root / skills.CACHE_DIR / _sha(SKILL_MD)
    os.chmod(cached, 0o600)
    cached.write_text("corrupted")
    refetched: list[str] = []
    skills.prepare(state, _context(), http=_client(_manifest(), blobs, refetched))
    assert [path for path in refetched if "/blobs/" in path] == [f"/api/v1/agent-gateway/skills/blobs/{_sha(SKILL_MD)}"]
    assert (skills.session_plugin_dir(state, KEY) / "skills" / "style-guide" / "SKILL.md").read_text() == SKILL_MD
    skills.remove_plugin(state, KEY)
    assert not (state.root.parent / "octryx-skill-plugins" / KEY).exists()


@pytest.mark.parametrize(("manifest", "blobs", "code"), [
    (_manifest(), {_sha(SKILL_MD): SKILL_MD + "tampered", _sha(REFERENCE): REFERENCE}, "skill_bundle_digest_mismatch"),
    (_manifest(bundle_digest="sha256:" + "0" * 64), {_sha(SKILL_MD): SKILL_MD, _sha(REFERENCE): REFERENCE},
     "skill_bundle_digest_mismatch"),
    (_manifest(SKILL_MD.replace("description:", "allowed-tools: Bash(*)\ndescription:")), None,
     "skill_frontmatter_not_allowed"),
])
def test_a_failed_verification_refuses_the_session(state, manifest, blobs, code):
    if blobs is None:
        text = SKILL_MD.replace("description:", "allowed-tools: Bash(*)\ndescription:")
        blobs = {_sha(text): text, _sha(REFERENCE): REFERENCE}
    with pytest.raises(skills.SkillDeliveryRefusedError) as refused:
        skills.prepare(state, _context(), http=_client(manifest, blobs, []))
    assert refused.value.code == code


@pytest.mark.parametrize("path", ["../escape.md", "/etc/passwd", "a//b.md", "a/./b.md"])
def test_unsafe_paths_or_names_make_the_manifest_unusable(state, path):
    manifest = _manifest()
    manifest["skills"][0]["files"][1]["path"] = path
    delivery = skills.prepare(state, _context(), http=_client(manifest, {}, []))
    assert (delivery.state, delivery.reason, delivery.plugin_dir) == ("unavailable", "manifest_invalid", None)
    bad_name = _manifest()
    bad_name["skills"][0]["name"] = "Bad Name"
    assert skills.prepare(state, _context(), http=_client(bad_name, {}, [])).reason == "manifest_invalid"


def test_an_unreachable_platform_starts_without_catalog_skills(state):
    def handler(_request):
        raise httpx.ConnectError("down")

    delivery = skills.prepare(state, _context(), http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert delivery.state == "unavailable" and delivery.summary() == "skills_unavailable (platform_unreachable)"


def test_the_sweep_removes_old_session_plugins_only(state):
    root = skills.plugin_root(state)
    for name in ("old-session", "recent-session", KEY):
        folder = root / name / "octryx"
        folder.mkdir(parents=True)
        (folder / "f").write_text("x")
        os.chmod(folder / "f", 0o444)
        os.chmod(folder, 0o555)
    old = time.time() - skills.SWEEP_AFTER_SECONDS - 10
    os.utime(root / "old-session", (old, old))
    os.utime(root / KEY, (old, old))
    assert skills.sweep(state, keep=KEY) == ["old-session"]
    assert sorted(entry.name for entry in root.iterdir()) == sorted(["recent-session", KEY])


def test_settings_argv_and_mcp_config_carry_the_plugin(state, tmp_path):
    plugin = tmp_path / "octryx-skill-plugins" / KEY / "octryx"
    settings = launch_settings.build_settings(shim=Path("/opt/octryx"), state_root=state.root, env={}, policy={},
                                     base_url=BASE_URL, plugin_dir=plugin)
    assert settings["disableSkillShellExecution"] is True
    protected = f"//{str(plugin).lstrip('/')}/**"
    # Edit covers every file-writing tool; Claude Code reports a Write(...) rule as one that never matches.
    assert f"Edit({protected})" in settings["permissions"]["deny"]
    assert not any(rule.startswith("Write(") for rule in settings["permissions"]["deny"])
    assert f"Read({protected})" not in settings["permissions"]["deny"]
    assert "UserPromptExpansion" in settings["hooks"]
    argv = launch_process.build_claude_argv("claude", settings_path=Path("s.json"), mcp_path=Path("m.json"),
                                            session_key=KEY, user_args=[], plugin_dir=plugin)
    assert argv[argv.index("--plugin-dir") + 1] == str(plugin)
    with pytest.raises(launch.LaunchRefusedError) as refused:
        launch_process.build_claude_argv("claude", settings_path=Path("s.json"), mcp_path=Path("m.json"),
                                         session_key=KEY, user_args=["--plugin-dir", "/tmp/foreign"])
    assert (refused.value.code, refused.value.detail) == ("flag_not_allowed", "--plugin-dir")
    mcp = launch_settings.build_mcp_config(shim=Path("/opt/octryx"), base_url=BASE_URL, catalog_servers={
        "terraform": {"type": "stdio", "command": "docker", "args": []},
        launch_settings.MCP_SERVER_NAME: {"type": "stdio", "command": "evil"}})
    assert set(mcp["mcpServers"]) == {launch_settings.MCP_SERVER_NAME, "terraform"}
    assert mcp["mcpServers"][launch_settings.MCP_SERVER_NAME]["type"] == "http"


def test_a_typed_skill_command_is_reported_by_name_only(state, monkeypatch):
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    hook_input = {"hook_event_name": "UserPromptExpansion", "command_name": "octryx:style-guide",
                  "command_args": "a secret argument", "command_source": "plugin", "prompt": "/x secret"}
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"state": "recorded"})

    assert skill_hooks.run_user_prompt_expansion(state, httpx.Client(transport=httpx.MockTransport(handler))) == 0
    assert json.loads(seen[0].content) == {"command_name": "octryx:style-guide", "command_source": "plugin"}
    assert seen[0].url.path.endswith("/sessions/skill-used")
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"not json")))
    assert skill_hooks.run_user_prompt_expansion(state, httpx.Client(transport=httpx.MockTransport(handler))) == 0


def test_the_launch_passes_the_plugin_and_a_mismatch_refuses_it(launch_env, capsys):
    blobs = {_sha(SKILL_MD): SKILL_MD, _sha(REFERENCE): REFERENCE}
    manifest = PlatformResult("ok", body=_manifest(), status_code=200, state="allowed")
    launch_env["responses"] = {"/skills/manifest": manifest}
    launch_env["responses"].update({f"/skills/blobs/{sha}": PlatformResult(
        "ok", body={"sha256": sha, "content": text}, status_code=200) for sha, text in blobs.items()})
    assert cli.main(["--", "-p", "hi"]) == 0
    argv = json.loads(launch_env["record"].read_text())["argv"]
    plugin = Path(argv[argv.index("--plugin-dir") + 1])
    assert (plugin / "skills" / "style-guide" / "SKILL.md").read_text() == SKILL_MD
    assert "1 catalog skill(s), 1 MCP server(s)" in capsys.readouterr().err
    session_key = launch_env["code_intelligence"][0].session_key
    mcp = json.loads((launch_env["state"].session_dir(session_key) / "mcp.json").read_text())
    assert "terraform" in mcp["mcpServers"]

    tampered = {sha: text + "x" for sha, text in blobs.items()}
    launch_env["responses"].update({f"/skills/blobs/{sha}": PlatformResult(
        "ok", body={"sha256": sha, "content": text}, status_code=200) for sha, text in tampered.items()})
    for cached in (launch_env["state"].root / "skill-cache").glob("*"):
        os.chmod(cached, 0o600)
        cached.unlink()
    launch_env["record"].unlink()
    assert cli.main(["--", "-p", "hi"]) == 2
    assert "denied: skill_bundle_digest_mismatch" in capsys.readouterr().err and not launch_env["record"].exists()
