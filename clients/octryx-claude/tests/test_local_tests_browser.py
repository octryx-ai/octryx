"""The device's Chrome and Playwright plugin, the pipeline's one re-run, and a story session's browser and hooks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from octryx_claude import browser, device_job_run, pipeline_commands

FAKE_PLAYWRIGHT = '''
class BrowserType:
    name = "chromium"
    def launch(self, *, channel=None, executable_path=None, headless=True):
        return {"channel": channel, "executable_path": executable_path}
    def launch_persistent_context(self, user_data_dir, *, channel=None, executable_path=None):
        return {"channel": channel}
'''


def _fake_playwright(root: Path) -> None:
    for api in ("sync_api", "async_api"):
        (root / "playwright" / api).mkdir(parents=True)
        (root / "playwright" / api / "__init__.py").write_text(FAKE_PLAYWRIGHT)
    (root / "playwright" / "__init__.py").write_text("")


def _pytest(folder: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=folder,
                          env=env, capture_output=True, text=True, timeout=120, check=False)


def test_the_device_chrome_is_the_default_and_the_bundled_one_when_the_repository_asks(tmp_path):
    env = browser.apply({"PYTHONPATH": "src"}, None, installed=True, root=tmp_path)
    assert env[browser.CHANNEL_ENV] == "chrome" and env["PYTEST_PLUGINS"] == "octryx_pytest"
    plugin = Path(env["PYTHONPATH"].split(":")[0])
    assert (plugin / "octryx_pytest.py").is_file() and env["PYTHONPATH"].endswith(":src")
    assert browser.CHANNEL_ENV not in browser.apply({}, {"browser": "chromium"}, installed=True, root=tmp_path)
    missing = browser.apply({}, None, installed=False, root=tmp_path)
    assert missing[browser.MISSING_ENV] == "chrome" and browser.CHANNEL_ENV not in missing
    assert browser.apply({browser.CHANNEL_ENV: "msedge"}, None, installed=True, root=tmp_path)[
        browser.CHANNEL_ENV] == "msedge"  # a person's own choice wins
    assert browser.skips_setup(".venv/bin/python -m playwright install chromium", {browser.CHANNEL_ENV: "chrome"})
    assert not browser.skips_setup("playwright install chromium", {})
    assert not browser.skips_setup(".venv/bin/pip install playwright", {browser.CHANNEL_ENV: "chrome"})


def test_the_plugin_gives_a_chromium_launch_the_device_chrome_unless_it_names_its_own(tmp_path):
    _fake_playwright(tmp_path / "lib")
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "test_browser.py").write_text(
        "from playwright.sync_api import BrowserType\n"
        "def test_default():\n    assert BrowserType().launch()['channel'] == 'chrome'\n"
        "def test_own():\n    assert BrowserType().launch(channel='msedge')['channel'] == 'msedge'\n"
        "def test_path():\n    assert BrowserType().launch(executable_path='/x')['channel'] is None\n")
    env = browser.apply({"PATH": "/usr/bin:/bin", "PYTHONPATH": str(tmp_path / "lib")}, None, installed=True,
                        root=tmp_path / "cache")
    done = _pytest(tmp_path / "repo", env)
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_pipeline_reruns_failed_tests_once_and_names_the_flaky_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(browser, "cache_root", lambda: tmp_path / "cache")
    (tmp_path / "test_suite.py").write_text(
        "from pathlib import Path\n"
        "def test_stable():\n    assert True\n"
        "def test_port_in_use_exits_3():\n"
        "    mark = Path(__file__).with_name('ran-once')\n"
        "    first = not mark.exists()\n    mark.write_text('x')\n    assert not first\n"
        "def test_broken():\n    assert 1 == 2\n")
    command = f"{sys.executable} -m pytest -q -p no:cacheprovider"
    result = pipeline_commands.run_command(command, 1, tmp_path, pipeline_commands._env(tmp_path, []))
    assert result["exit_code"] == 1 and result["rerun"]["exit_code"] == 1
    assert result["rerun"]["tests"] == ["test_suite.py::test_port_in_use_exits_3", "test_suite.py::test_broken"]
    assert result["flaky"] == ["test_suite.py::test_port_in_use_exits_3"]  # red, then green with no change
    assert "1 passed, 1 failed" in result["rerun"]["output_tail"] or "1 failed, 1 passed" in result["rerun"][
        "output_tail"]
    green = pipeline_commands.run_command(f"{command} -k stable", 2, tmp_path, pipeline_commands._env(tmp_path, []))
    assert green["exit_code"] == 0 and "rerun" not in green


def test_a_story_session_gets_a_pinned_isolated_browser_installed_once_in_the_launchers_folder(tmp_path, monkeypatch):
    from octryx_claude import browser_mcp

    monkeypatch.setattr(browser, "cache_root", lambda: tmp_path / "cache")
    calls: list[list[str]] = []

    def npm(argv, **_kwargs):
        calls.append(argv)
        package = Path(argv[argv.index("--prefix") + 1]) / "node_modules" / "@playwright" / "mcp"
        package.mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"version": browser_mcp.VERSION}))
        (package / "cli.js").write_text("")
        return subprocess.CompletedProcess(argv, 0)

    node = tmp_path / "bin" / "node"
    node.parent.mkdir()
    node.write_text("")
    (node.parent / "npm").write_text("")
    cli = browser_mcp.ensure_installed(tmp_path / "state", node=str(node), run=npm)
    assert cli == tmp_path / "state" / "browser-mcp" / browser_mcp.VERSION / "node_modules/@playwright/mcp/cli.js"
    assert calls[0][1:3] == ["install", "--prefix"] and calls[0][-1] == f"@playwright/mcp@{browser_mcp.VERSION}"
    assert "-g" not in calls[0] and "--global" not in calls[0]
    assert browser_mcp.ensure_installed(tmp_path / "state", node=str(node), run=npm) == cli and len(calls) == 1

    key = "00000000-0000-4000-8000-0000000000b1"
    spec = browser_mcp.server_spec(tmp_path / "state", key, node=str(node), chrome=True,
                                   install=lambda _root, node: cli, platform_url="https://platform.example")
    args = spec["args"]
    assert spec["command"] == str(node) and args[0] == str(cli)
    assert "--headless" in args and args[args.index("--browser") + 1] == "chrome"
    origins = args[args.index("--allowed-origins") + 1].split(";")
    assert origins and all(origin.split("://")[1].split(":")[0] in ("127.0.0.1", "localhost") for origin in origins)
    assert "--extension" not in args and "--cdp-endpoint" not in args and "--allow-unrestricted-file-access" not in args
    assert "--isolated" not in args  # 0.0.84 refuses it together with a user-data dir
    session = tmp_path / "state" / "sessions" / key
    profile = Path(args[args.index("--user-data-dir") + 1])
    assert profile == session / "browser-profile" and profile.is_dir()  # this session's own profile, nobody else's
    config = json.loads(Path(args[args.index("--config") + 1]).read_text())
    assert config == {"browser": {"contextOptions": {"acceptDownloads": False}}}  # no downloads
    assert "--blocked-origins" not in args  # the platform is not on this machine
    assert args[args.index("--output-dir") + 1] == str(tmp_path / "cache" / "browser" / key)
    assert browser_mcp.server_spec(tmp_path / "state", key, node=str(node), chrome=True,
                                   install=lambda _root, node: None) is None  # no install: the turn has no browser
    assert browser_mcp.server_spec(tmp_path / "state", "../x", node=str(node), chrome=True,
                                   install=lambda _root, node: cli) is None  # no session folder: no browser

    # A local stack: the platform on 127.0.0.1:24600 is no page of the app.
    local = browser_mcp.server_spec(tmp_path / "state", key, node=str(node), chrome=True,
                                    install=lambda _root, node: cli, platform_url="http://127.0.0.1:24600")["args"]
    blocked = local[local.index("--blocked-origins") + 1].split(";")
    assert "http://127.0.0.1:24600" in blocked and "http://localhost:24600" in blocked
    assert all(origin.endswith(":24600") for origin in blocked)
    # B13: a browser that reads external pages has no loopback-only allowlist; the platform's
    # public host stays blocked.
    external = browser_mcp.server_spec(tmp_path / "state", key, node=str(node), chrome=True,
                                       install=lambda _root, node: cli, platform_url="https://platform.example",
                                       external=True)["args"]
    assert "--allowed-origins" not in external
    assert external[external.index("--blocked-origins") + 1] == "http://platform.example;https://platform.example"

    session_mcp = tmp_path / "mcp.json"
    session_mcp.write_text(json.dumps({"mcpServers": {"octryx-knowledge": {"type": "http", "url": "u"}}}))
    written = json.loads(browser_mcp.browser_config(session_mcp, spec).read_text())["mcpServers"]
    assert set(written) == {"octryx-knowledge", "playwright"}
    assert "playwright" not in json.loads(session_mcp.read_text())["mcpServers"]  # every other turn: no browser


def test_a_device_run_from_a_checkout_gives_its_sessions_its_own_hooks(tmp_path, monkeypatch):
    # Settings and hooks of a checkout's session come from the same launcher.
    from octryx_claude import device_service, install_layout

    checkout = tmp_path / "bin" / "octryx-claude"
    monkeypatch.setattr(install_layout, "CHECKOUT_SHIM", checkout)
    monkeypatch.setattr(device_service, "service_shim", lambda: Path("/home/u/.local/bin/octryx-claude"))
    # An installation in its own home calls its own launcher, never the person's main installation behind
    # ~/.local/bin, and by the unresolved venvs/current path.
    own = tmp_path / "c3" / "venvs" / "current" / "bin"
    own.mkdir(parents=True)
    (own / "octryx-claude").write_text("#!/bin/sh\n")
    version = tmp_path / "c3" / "venvs" / "0.3.4+c01eaaea9aed" / "bin"  # what the venv's python resolves to
    version.mkdir(parents=True)
    (version / "octryx-claude").write_text("#!/bin/sh\n")
    assert device_job_run.session_shim(str(version / "python")) == own / "octryx-claude"
    assert device_job_run.session_shim(str(own / "python")) == own / "octryx-claude"
    assert device_job_run.session_shim(str(tmp_path / "bare" / "python")) == Path("/home/u/.local/bin/octryx-claude")
    checkout.parent.mkdir(parents=True)
    checkout.write_text("#!/bin/sh\n")
    assert device_job_run.session_shim(str(own / "python")) == checkout


def test_a_server_runner_uses_the_browser_its_image_carries_and_opens_its_folders_to_the_agent(tmp_path, monkeypatch):
    import stat

    from octryx_claude import browser_mcp, state

    prebuilt = tmp_path / "image" / "browser-mcp"
    monkeypatch.setenv(browser_mcp.PREBUILT_ENV, str(prebuilt))
    monkeypatch.setenv(state.SHARED_STATE_ENV, "1")
    installs: list = []
    node = tmp_path / "bin" / "node"
    node.parent.mkdir()
    node.write_text("")
    (node.parent / "npm").write_text("")
    assert browser_mcp.ensure_installed(tmp_path / "state", node=str(node), run=installs.append) is None
    assert installs == []  # no internet on a runner: never an install at run time

    package = prebuilt / "node_modules" / "@playwright" / "mcp"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"version": browser_mcp.VERSION}))
    (package / "cli.js").write_text("")
    (prebuilt / "browsers" / "chromium-1").mkdir(parents=True)
    cli = browser_mcp.ensure_installed(tmp_path / "state", node=str(node))
    assert cli == package / "cli.js"
    key = "00000000-0000-4000-8000-0000000000b2"
    spec = browser_mcp.server_spec(tmp_path / "state", key, node=str(node), chrome=False)
    args = spec["args"]
    assert spec["env"] == {"PLAYWRIGHT_BROWSERS_PATH": str(prebuilt / "browsers")}
    session = tmp_path / "state" / "sessions" / key
    out, profile = Path(args[args.index("--output-dir") + 1]), Path(args[args.index("--user-data-dir") + 1])
    assert out == session / "browser-output"  # wiped with the session's state when the runner changes hands
    assert stat.S_IMODE(out.stat().st_mode) == stat.S_IMODE(profile.stat().st_mode) == 0o2770
    assert stat.S_IMODE(Path(args[args.index("--config") + 1]).stat().st_mode) == 0o640
