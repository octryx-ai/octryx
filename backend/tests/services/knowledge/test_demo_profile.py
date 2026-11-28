"""The demo (docker-compose.demo.yml, deployment/demo): the fake GitHub, the seed's inputs and the compose wiring."""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
DEMO = ROOT / "deployment" / "demo"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"demo_{name}", DEMO / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seed():
    return _load("seed_demo")


@pytest.fixture(scope="module")
def fake():
    return _load("fake_github")


def test_the_demo_repository_and_bot_carry_the_neutral_demo_names(seed, fake):
    assert seed.REPOSITORY == "demo/demo-shop"
    assert seed.WORKSPACE == "Demo Shop"
    assert fake.BOT["login"] == "demo-bot"


def test_the_knowledge_is_the_demo_shops_readme_and_docs(seed):
    knowledge = seed.knowledge_files()
    assert sorted(knowledge) == [
        "README.md", "docs/incident-runbook.md", "docs/onboarding.md", "docs/release-process.md",
    ]
    assert set(knowledge) <= set(seed.files())
    assert all("__pycache__" not in name for name in seed.files())


def test_every_knowledge_file_has_a_valid_source_key(seed):
    from app.services.knowledge.ingestion.spans import normalize_source_key

    keys = [seed.source_key(name) for name in seed.knowledge_files()]
    assert [normalize_source_key(key) for key in keys] == keys
    assert len(set(keys)) == len(keys)


def test_the_seed_changes_nothing_without_the_demo_switch(seed, monkeypatch):
    monkeypatch.delenv("OCTRYX_DEMO", raising=False)

    def refuse(*_args, **_kwargs):
        raise AssertionError("no network call without OCTRYX_DEMO=1")

    monkeypatch.setattr(seed.urllib.request, "urlopen", refuse)
    assert seed.main() == 0


def test_the_demo_shop_tests_fail_on_its_known_bug_only():
    done = subprocess.run(
        ["python3", "-m", "unittest", "discover", "-s", "tests"], cwd=DEMO / "demo-shop",
        capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr
    probe = subprocess.run(
        ["python3", "-c", "from shop.pricing import Line, order_total; print(order_total([Line('mug', 50.0)], 10))"],
        cwd=DEMO / "demo-shop", capture_output=True, text=True, check=True,
    )
    assert probe.stdout.strip() == "40.0"  # the bug: expected 45.0


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_the_fake_github_serves_a_seeded_repository_and_a_pull_request(fake, tmp_path):
    store = fake.Store(tmp_path / "remotes", "http://127.0.0.1:8434/api/v3")
    status, created = fake.handle_api(store, "POST", "/_fake/repos", {}, {
        "owner": "demo", "repo": "demo-shop", "files": {"README.md": "# Demo Shop\n"}})
    assert (status, created["created"]) == (201, True)
    assert fake.handle_api(store, "POST", "/_fake/repos", {}, {"owner": "demo", "repo": "demo-shop"})[1]["created"] is False

    status, repo = fake.handle_api(store, "GET", "/api/v3/repos/demo/demo-shop", {}, {})
    assert (status, repo["full_name"], repo["default_branch"]) == (200, "demo/demo-shop", "main")
    assert repo["clone_url"] == "http://127.0.0.1:8434/demo/demo-shop.git"

    sha = fake.handle_api(store, "GET", "/repos/demo/demo-shop/git/ref/heads/main", {}, {})[1]["object"]["sha"]
    assert fake.handle_api(store, "POST", "/repos/demo/demo-shop/git/refs", {},
                           {"ref": "refs/heads/fix/discount", "sha": sha})[0] == 201
    status, pull = fake.handle_api(store, "POST", "/repos/demo/demo-shop/pulls", {},
                                   {"title": "Fix the discount", "head": "fix/discount", "base": "main"})
    assert (status, pull["number"], pull["user"]["login"]) == (201, 1, "demo-bot")
    assert fake.handle_api(store, "GET", "/user", {}, {})[1]["login"] == "demo-bot"


def _yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def test_the_main_compose_file_alone_carries_nothing_of_the_demo():
    base = _yaml("docker-compose.yml")
    assert not {"demo", "demo-git"} & set(base["services"])
    assert "demo_git_remotes" not in (base.get("volumes") or {})
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "OCTRYX_SOURCE_SYNC_ALLOW_LOOPBACK_HOSTS" not in text
    assert "OCTRYX_DEMO" not in text
    assert [str(port) for port in base["services"]["pod"]["ports"]] == ["127.0.0.1:${OCTRYX_PORT:-8000}:8000"]


def test_the_demo_file_holds_the_exemption_the_port_and_the_switch():
    demo = _yaml("docker-compose.demo.yml")["services"]
    assert demo["api"]["environment"] == {
        "OCTRYX_SOURCE_SYNC_ALLOW_LOOPBACK_HOSTS": "127.0.0.1:${OCTRYX_DEMO_GIT_PORT:-8434}",
        "OCTRYX_DEMO_NOTICE": "1"}
    assert demo["pod"]["ports"] == ["127.0.0.1:${OCTRYX_DEMO_GIT_PORT:-8434}:${OCTRYX_DEMO_GIT_PORT:-8434}"]
    assert "/demo/seed_demo.py" in demo["demo"]["command"]
    switched = [name for name, service in demo.items() if (service.get("environment") or {}).get("OCTRYX_DEMO") == "1"]
    assert switched == ["demo"]


def test_no_admin_token_is_signed_outside_the_demo(seed, monkeypatch):
    monkeypatch.delenv("OCTRYX_DEMO", raising=False)
    with pytest.raises(SystemExit, match="outside the demo"):
        asyncio.run(seed._admin_token())
    monkeypatch.setenv("OCTRYX_DEMO", "yes")
    with pytest.raises(SystemExit, match="outside the demo"):
        asyncio.run(seed._admin_token())


def test_the_demo_token_is_short_lived_and_never_printed(seed, monkeypatch, capsys):
    import jwt

    from app.config import get_settings
    from app.services.auth.tokens import JWT_ALGORITHM

    monkeypatch.setenv("OCTRYX_DEMO", "1")
    signed: list[str] = []

    class FakeResult:
        def scalar_one_or_none(self):
            return type("Admin", (), {"id": "admin-id"})()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def execute(self, _statement):
            return FakeResult()

    monkeypatch.setattr("app.db.async_session_factory", FakeSession)
    token = asyncio.run(seed._admin_token())
    claims = jwt.decode(token, get_settings().jwt_secret, algorithms=[JWT_ALGORITHM], options={"verify_aud": False})
    assert claims["sub"] == "admin-id"
    assert claims["exp"] - time.time() <= seed.TOKEN_MINUTES * 60 + 5

    async def admin_token():
        signed.append(token)
        return token

    async def knowledge(_ws):
        print("knowledge: stubbed")

    calls: list[tuple[str, str]] = []

    def call(self, method, path, body=None, ok=(200, 201, 204)):
        assert self.token == token
        calls.append((method, path))
        if path == "/api/v1/projects" and method == "GET":
            return [{"name": seed.WORKSPACE, "id": "ws-1"}]
        if path == "/api/v1/admin/connections" and method == "GET":
            return {"connections": [{"type": "github", "name": seed.CONNECTION, "id": "c-1"}]}
        if path.endswith("/repositories") and method == "POST":
            return {"id": "r-1"}
        return {}

    monkeypatch.setattr(seed, "_admin_token", admin_token)
    monkeypatch.setattr(seed, "_knowledge", knowledge)

    async def sample_run():
        print("sample run: stubbed")  # the bundle's import has its own tests (test_sample_runs.py)

    monkeypatch.setattr(seed, "seed_sample_run", sample_run)
    monkeypatch.setattr(seed, "seed_git", lambda: print("git: stubbed"))
    monkeypatch.setattr(seed.Api, "wait_healthy", lambda self, seconds=300: None)
    monkeypatch.setattr(seed.Api, "call", call)
    monkeypatch.delenv("OCTRYX_DEMO_DIR", raising=False)
    capsys.readouterr()
    assert seed.main() == 0
    output = capsys.readouterr()
    assert signed == [token] and calls
    assert "demo: ready" in output.out
    assert token not in output.out + output.err
    assert token.split(".")[1] not in output.out + output.err  # not even the claims part


def test_the_demo_ports_are_published_on_the_hosts_loopback_only():
    ports = [*_yaml("docker-compose.yml")["services"]["pod"]["ports"],
             *_yaml("docker-compose.demo.yml")["services"]["pod"]["ports"]]
    assert ports and all(str(port).startswith("127.0.0.1:") for port in ports)


def test_the_seed_imports_the_recorded_sample_run_when_there_is_one(seed, monkeypatch, tmp_path, capsys):
    bundle = tmp_path / "run.json"
    calls: list[dict] = []

    class Tool:
        @staticmethod
        async def import_bundle(data, **kwargs):
            calls.append({"data": data, **kwargs})

    monkeypatch.setattr(seed, "SAMPLE_RUN", bundle)
    monkeypatch.setattr(seed, "_bundle_tool", lambda: Tool)
    asyncio.run(seed.seed_sample_run())
    assert calls == [] and "none recorded yet" in capsys.readouterr().out
    bundle.write_text('{"format": "octryx-run-bundle"}')
    asyncio.run(seed.seed_sample_run())
    assert calls == [{"data": {"format": "octryx-run-bundle"}, "workspace": seed.WORKSPACE, "github": seed.GIT_BASE,
                      "app_base": seed.API_BASE}]


def test_a_recorded_sample_run_passes_the_bundle_checks(seed):
    if not seed.SAMPLE_RUN.exists():
        pytest.skip("no sample run recorded yet")
    tool = _load_backend_script("run_bundle")
    assert tool.check(seed.SAMPLE_RUN.read_text(encoding="utf-8")) == []


def _load_backend_script(name: str):
    spec = importlib.util.spec_from_file_location(f"demo_tool_{name}", ROOT / "backend" / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_seed_refuses_a_production_runtime(seed, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("OCTRYX_DEMO", "1")

    def refuse(*_args, **_kwargs):
        raise AssertionError("no network call in a production runtime")

    monkeypatch.setattr(seed.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(get_settings(), "runtime_profile", "production")
    with pytest.raises(SystemExit, match="runtime profile 'production'"):
        seed.main()
    monkeypatch.setattr(get_settings(), "runtime_profile", "staging")
    seed.refuse_production()  # the compose install's profile is a demo's


async def test_the_sign_in_and_setup_pages_say_local_demo_only_in_the_demo(client, monkeypatch):
    monkeypatch.delenv("OCTRYX_DEMO_NOTICE", raising=False)
    for path in ("/chat/login", "/chat/setup"):
        page = await client.get(path, follow_redirects=True)
        assert "Local demo, not for production" not in page.text
    monkeypatch.setenv("OCTRYX_DEMO_NOTICE", "1")
    pages = [await client.get(path, follow_redirects=True) for path in ("/chat/login", "/chat/setup")]
    assert all("Local demo, not for production" in page.text for page in pages)


def test_the_setup_page_names_the_log_command_that_finds_the_code(monkeypatch):
    import re

    from app.web._context import templates

    def hint() -> str:
        page = templates.get_template("login.html").render(
            request=None, setup=True, error=None, sso_providers=[], branding={}, csrf_token="")
        return re.search(r'data-testid="setup-code-hint">(.*?)</p>', page, re.S).group(1)

    monkeypatch.setenv("OCTRYX_DEMO_NOTICE", "1")
    assert "docker compose -f docker-compose.yml -f docker-compose.demo.yml logs api" in hint()
    monkeypatch.delenv("OCTRYX_DEMO_NOTICE")
    assert "add the same <code>-f</code> files you started with" in hint()
