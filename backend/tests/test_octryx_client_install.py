"""octryx-claude installer endpoints and package builder.

Public, unauthenticated routes: the scripts carry the platform URL (the OAuth issuer origin) and an
optional validated Workspace, never a secret; the package is a deterministic wheel whose sha256 the
version answer publishes.
"""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import zipfile
from pathlib import Path

import pytest

from app.config import get_settings
from app.services.octryx_client import artifact, installers

ORIGIN = "http://test"
REPO = Path(__file__).resolve().parents[2]
CLIENT_DIR = REPO / "clients" / "octryx-claude"
SCRIPTS_DIR = REPO / "backend" / "scripts"


@pytest.mark.parametrize("marker", ["@@OCTRYX_UNKNOWN@@", "@@OCTRYX_WORKSPCE@@"])
def test_renderer_refuses_unresolved_current_placeholders(marker):
    template = f"{installers.BASE_URL_PLACEHOLDER} {installers.WORKSPACE_PLACEHOLDER} {marker}"
    with pytest.raises(installers.InstallerRenderError) as refused:
        installers.render(template, base_url="https://octryx.example.com")
    assert refused.value.code == "installer_template_invalid"


def _client_version() -> str:
    init = (CLIENT_DIR / "octryx_claude" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', init).group(1)


@pytest.fixture
def client_copy(tmp_path) -> Path:
    copy = tmp_path / "client"
    shutil.copytree(CLIENT_DIR / "octryx_claude", copy / "octryx_claude",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(CLIENT_DIR / "pyproject.toml", copy / "pyproject.toml")
    return copy


# --- routes ---------------------------------------------------------------------------------


async def test_install_sh_is_public_and_filled_with_the_platform_url(client):
    client.cookies.clear()
    response = await client.get("/octryx-claude/install.sh", headers={"Authorization": ""})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["cache-control"] == "no-cache"
    body = response.text
    assert body.startswith("#!/usr/bin/env bash\n")
    assert f"OCTRYX_BASE_URL='{ORIGIN}'\n" in body
    assert "OCTRYX_WORKSPACE=''\n" in body
    assert "OCTRYX_OS_JUNK='.DS_Store ._* Thumbs.db desktop.ini'\n" in body
    assert "@@OCTRYX_" not in body and "\r\n" not in body


async def test_install_ps1_carries_the_workspace_preselect(client):
    response = await client.get("/octryx-claude/install.ps1", params={"workspace": "3f2c-ws"})
    assert response.status_code == 200
    assert f"$OctryxBaseUrl = '{ORIGIN}'" in response.text
    assert "$OctryxWorkspace = '3f2c-ws'" in response.text


@pytest.mark.parametrize("workspace", ["x';rm -rf ~;'", "a b", "$(id)", "ws\nOCTRYX_BASE_URL=evil", "ws\n", "-ws", "x" * 121])
async def test_unsafe_workspace_is_refused_explicitly(client, workspace):
    for path in ("/octryx-claude/install.sh", "/octryx-claude/install.ps1", "/octryx-claude/version"):
        response = await client.get(path, params={"workspace": workspace})
        assert response.status_code == 422
        assert response.json() == {"state": "denied", "reason": "workspace_invalid"}


async def test_version_publishes_checksum_package_url_and_one_liners(client):
    response = await client.get("/octryx-claude/version", params={"workspace": "ws-1"})
    assert response.status_code == 200
    payload = response.json()
    version = payload["version"]
    assert version.split("+")[0] == _client_version() and len(version.split("+")[1]) == artifact.SOURCE_HASH_CHARS
    assert payload["filename"] == f"octryx_claude-{version}-py3-none-any.whl"
    assert payload["package_url"] == f"{ORIGIN}/octryx-claude/package/{version}"
    assert payload["requires_python"] == ">=3.11"
    assert payload["install"] == {
        "macos": f"curl -fsSL '{ORIGIN}/octryx-claude/install.sh?workspace=ws-1' | bash",
        "windows": f"irm '{ORIGIN}/octryx-claude/install.ps1?workspace=ws-1' | iex",
    }

    package = await client.get(f"/octryx-claude/package/{version}")
    assert package.status_code == 200
    assert hashlib.sha256(package.content).hexdigest() == payload["sha256"]
    assert package.headers["x-checksum-sha256"] == payload["sha256"]
    assert "immutable" in package.headers["cache-control"]
    assert payload["filename"] in package.headers["content-disposition"]


async def test_only_the_served_version_is_downloadable(client):
    response = await client.get("/octryx-claude/package/0.1.0+000000000000")
    assert response.status_code == 404
    assert response.json() == {"state": "denied", "reason": "package_version_not_served"}


async def test_configured_public_origin_is_the_served_base_url(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "platform_public_origin", "https://octryx.example.com/")
    script = (await client.get("/octryx-claude/install.sh")).text
    assert "OCTRYX_BASE_URL='https://octryx.example.com'\n" in script
    payload = (await client.get("/octryx-claude/version")).json()
    assert payload["package_url"].startswith("https://octryx.example.com/octryx-claude/package/")


async def test_forwarded_proto_counts_only_from_a_configured_proxy(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "platform_public_origin", None)
    headers = {"X-Forwarded-Proto": "https"}
    untrusted = (await client.get("/octryx-claude/install.sh", headers=headers)).text
    assert f"OCTRYX_BASE_URL='{ORIGIN}'\n" in untrusted
    monkeypatch.setattr(get_settings(), "trusted_proxy_ips", "127.0.0.1")
    trusted = (await client.get("/octryx-claude/install.sh", headers=headers)).text
    assert "OCTRYX_BASE_URL='https://test'\n" in trusted


async def test_missing_client_sources_are_an_explicit_needs_configuration(client, monkeypatch, tmp_path):
    monkeypatch.setenv(artifact.CLIENT_DIR_ENV, str(tmp_path / "absent"))
    for path in ("/octryx-claude/version", "/octryx-claude/install.sh", "/octryx-claude/package/0.2.0"):
        response = await client.get(path)
        assert response.status_code == 503
        assert response.json() == {"state": "needs_configuration", "reason": "octryx_client_source_missing"}


# --- renderer -------------------------------------------------------------------------------


@pytest.mark.parametrize("base_url", [
    "https://octryx.example.com", "http://localhost:8090", "https://octryx.example.com/platform", "http://[::1]:8090",
])
def test_render_accepts_platform_urls(base_url):
    script = installers.render("A='@@OCTRYX_BASE_URL@@' W='@@OCTRYX_WORKSPACE@@'", base_url=base_url + "/")
    assert script == f"A='{base_url}' W=''"


@pytest.mark.parametrize("base_url", [
    "ftp://octryx.example.com", "https://octryx.example.com/'x", "https://octryx.example.com/a b", "https://octryx.example.com?q=1",
    "https://", "javascript:alert(1)",
])
def test_render_refuses_unusable_urls(base_url):
    with pytest.raises(installers.InstallerRenderError) as refused:
        installers.render("@@OCTRYX_BASE_URL@@ @@OCTRYX_WORKSPACE@@", base_url=base_url)
    assert refused.value.code == "base_url_unusable"


def test_render_refuses_a_template_without_placeholders():
    with pytest.raises(installers.InstallerRenderError) as refused:
        installers.render("echo hi", base_url="https://octryx.example.com")
    assert refused.value.code == "installer_template_invalid"


def test_os_junk_names_that_could_leave_the_quoted_literal_are_refused(tmp_path):
    (tmp_path / "octryx_claude").mkdir()
    (tmp_path / "octryx_claude" / "os_junk.json").write_text('{"files": [".DS_Store", "x\'; rm -rf ~"]}')
    with pytest.raises(installers.InstallerRenderError) as refused:
        installers.os_junk_files(tmp_path)
    assert refused.value.code == "installer_template_invalid"


def test_served_templates_contain_no_secret_material():
    for name in installers.SCRIPTS:
        text = installers.installer_template(name)
        assert installers.BASE_URL_PLACEHOLDER in text and installers.WORKSPACE_PLACEHOLDER in text
        lowered = text.lower()
        assert "client_secret" not in lowered and "bearer " not in lowered and "password" not in lowered


# --- package builder ------------------------------------------------------------------------


def test_build_is_deterministic_and_content_addressed(client_copy):
    first = artifact.build_artifact(client_copy, SCRIPTS_DIR)
    second = artifact.build_artifact(client_copy, SCRIPTS_DIR)
    assert first.content == second.content and first.sha256 == second.sha256
    (client_copy / "octryx_claude" / "state.py").write_text("# changed\n", encoding="utf-8")
    changed = artifact.build_artifact(client_copy, SCRIPTS_DIR)
    assert changed.version != first.version and changed.sha256 != first.sha256


def test_wheel_layout_metadata_and_record(client_copy):
    built = artifact.build_artifact(client_copy, SCRIPTS_DIR)
    with zipfile.ZipFile(io.BytesIO(built.content)) as wheel:
        names = wheel.namelist()
        dist_info = f"octryx_claude-{built.version}.dist-info"
        metadata = wheel.read(f"{dist_info}/METADATA").decode()
        entry_points = wheel.read(f"{dist_info}/entry_points.txt").decode()
        record = wheel.read(f"{dist_info}/RECORD").decode().splitlines()
        assert "octryx_claude/cli.py" in names and "octryx_claude/entry.py" in names
        assert "octryx_claude/os_junk.json" in names  # data the launcher reads at run time
        assert "octryx_claude/_platform_scripts/ingest_claude_session.py" in names
        assert "octryx_claude/_platform_scripts/mcp_session_ingest_common.py" in names
        assert "octryx_claude/_platform_scripts/transcript_secrets.py" in names  # full transcripts' secret rules
        assert "octryx_claude/_platform_scripts/secret_patterns.py" in names  # the one list of known secret forms
        assert not [name for name in names if "tests/" in name or "__pycache__" in name]
        assert f"Version: {built.version}" in metadata
        assert "Requires-Python: >=3.11" in metadata
        assert "Requires-Dist: httpx==0.28.1" in metadata
        # the pet extra resolves from the served wheel (octryx-claude[pet])
        assert "Provides-Extra: pet" in metadata
        assert 'Requires-Dist: pystray==0.19.5 ; extra == "pet"' in metadata
        assert "octryx-claude = octryx_claude.entry:main" in entry_points
        assert "octryx = octryx_claude.entry:main" in entry_points  # the short name
        assert f"{dist_info}/RECORD,," in record
        for line in record:
            name, digest, size = line.rsplit(",", 2)
            if name.endswith("RECORD"):
                continue
            content = wheel.read(name)
            assert digest == artifact._record_hash(content) and int(size) == len(content)
        assert {info.date_time for info in wheel.infolist()} == {(1980, 1, 1, 0, 0, 0)}


def test_version_comes_from_the_package(client_copy):
    init = client_copy / "octryx_claude" / "__init__.py"
    init.write_text('__version__ = "1.4.2"\n', encoding="utf-8")
    assert artifact.build_artifact(client_copy, SCRIPTS_DIR).version.startswith("1.4.2+")
    init.write_text("no version here\n", encoding="utf-8")
    with pytest.raises(artifact.ClientArtifactError) as refused:
        artifact.build_artifact(client_copy, SCRIPTS_DIR)
    assert refused.value.code == "octryx_client_version_missing"


def test_missing_platform_script_is_refused(client_copy, tmp_path):
    with pytest.raises(artifact.ClientArtifactError) as refused:
        artifact.build_artifact(client_copy, tmp_path)
    assert refused.value.code == "octryx_client_platform_script_missing"


def test_cache_rebuilds_only_on_source_change(client_copy, monkeypatch):
    builds = []
    real = artifact.build_artifact
    monkeypatch.setattr(artifact, "build_artifact", lambda *a: builds.append(1) or real(*a))
    first = artifact.current_artifact(client_copy, SCRIPTS_DIR)
    assert artifact.current_artifact(client_copy, SCRIPTS_DIR) is first
    (client_copy / "octryx_claude" / "state.py").write_text("# changed, longer than before?\n" * 400)
    assert artifact.current_artifact(client_copy, SCRIPTS_DIR).version != first.version
    assert len(builds) == 2
