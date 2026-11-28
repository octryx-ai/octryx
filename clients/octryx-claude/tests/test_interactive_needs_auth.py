"""An interactive session drops the platform server's "needs authentication" mark too."""

from __future__ import annotations

import json

from octryx_claude import cli, launch, launch_settings

OTHER = {"plugin:cloudflare:cloudflare-api": {"timestamp": 1795164655664}}


def test_an_interactive_session_removes_the_mark_of_the_platform_server_only(launch_env):
    config_dir = launch_env["state"].claude_config_dir_for(launch.PROFILE_GOVERNED)
    config_dir.mkdir(parents=True, exist_ok=True)
    cache = config_dir / "mcp-needs-auth-cache.json"
    cached = {launch_settings.MCP_SERVER_NAME: {"timestamp": 1795164655664}, **OTHER}
    cache.write_text(json.dumps(cached), encoding="utf-8")

    assert cli.main(["--", "-p", "hi"]) == 0

    assert json.loads(cache.read_text(encoding="utf-8")) == OTHER  # another server's mark stays
    assert launch_env["bodies"]["/sessions/register"]["mcp_auth_cache_cleared"] is True


def test_without_a_mark_the_platform_is_not_told_anything(launch_env):
    assert cli.main(["--", "-p", "hi"]) == 0

    assert "mcp_auth_cache_cleared" not in launch_env["bodies"]["/sessions/register"]
