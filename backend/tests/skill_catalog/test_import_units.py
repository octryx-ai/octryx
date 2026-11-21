"""Import units: the real git fetcher (local repository, no network), licences, layout, MCP launch specs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.services.skill_catalog.errors import SkillCatalogError
from app.services.skill_catalog.git_source import SubprocessGitFetcher, normalize_repository_url
from app.services.skill_catalog.layout import find_layout, resolve_marketplace_entry
from app.services.skill_catalog.licence import detect_licence, identify_licence_text
from app.services.skill_catalog.mcp_entry import delivered_server, launch_spec, normalize_launch_spec
from tests.skill_catalog.fake_git import APACHE, MIT, MPL


def _git(repo: Path, *args: str) -> str:
    env = {"PATH": os.environ["PATH"], "HOME": str(repo.parent), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def local_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "origin"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "uploadpack.allowFilter", "true")
    _git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")
    skill = repo / "skills" / "demo"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\ndescription: Demo.\n---\n\n# Demo\n")
    (skill / "scripts" / "run.sh").write_text("#!/bin/sh\necho demo\n")
    (skill / "scripts" / "run.sh").chmod(0o755)
    (repo / "LICENSE").write_text(MIT)
    (repo / "big.bin").write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1\n")
    os.symlink("/etc/hosts", repo / "skills" / "demo" / "hosts")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "tag", "v1")
    return repo


@pytest.mark.asyncio
async def test_the_real_fetcher_reads_a_shallow_sparse_snapshot_and_refuses_links_and_lfs(local_repo: Path):
    fetcher = SubprocessGitFetcher(protocols=("file",), check_outbound=False)
    url = f"file://{local_repo}"
    head = _git(local_repo, "rev-parse", "HEAD").strip()
    assert await fetcher.resolve(url, "main", token=None) == head
    assert await fetcher.resolve(url, "v1", token=None) == head
    assert await fetcher.resolve(url, head, token=None) == head
    with pytest.raises(SkillCatalogError) as missing_ref:
        await fetcher.resolve(url, "nope", token=None)
    assert missing_ref.value.code == "skill_source_ref_not_found"
    async with fetcher.open(url, head, token=None) as snapshot:
        assert snapshot.entries["skills/demo/scripts/run.sh"].mode == "100755"
        assert snapshot.entries["skills/demo/hosts"].mode == "120000"
        files = await snapshot.read_many(["skills/demo/SKILL.md", "skills/demo/scripts/run.sh", "LICENSE"])
        assert files["skills/demo/SKILL.md"].startswith(b"---\nname: demo")
        assert identify_licence_text(files["LICENSE"].decode()) == "MIT"
        for path, code in [("skills/demo/hosts", "skill_archive_symlink"), ("big.bin", "skill_source_lfs_pointer"),
                           ("absent.md", "skill_source_path_missing")]:
            with pytest.raises(SkillCatalogError) as refused:
                await snapshot.read_many([path])
            assert refused.value.code == code
    with pytest.raises(SkillCatalogError) as unknown:
        async with fetcher.open(url, "f" * 40, token=None):
            pass
    assert unknown.value.code == "skill_source_fetch_failed"


@pytest.mark.asyncio
async def test_the_default_fetcher_allows_only_https(local_repo: Path):
    fetcher = SubprocessGitFetcher(check_outbound=False)
    with pytest.raises(SkillCatalogError) as refused:
        await fetcher.resolve(f"file://{local_repo}", "main", token=None)
    assert refused.value.code == "skill_source_fetch_failed"


def test_the_token_travels_in_the_environment_not_in_argv():
    env = SubprocessGitFetcher()._env("/tmp/h", "secret-token")
    values = [value for key, value in env.items() if key.startswith("GIT_CONFIG_VALUE_")]
    assert any(value.startswith("Authorization: Basic ") for value in values)
    assert "secret-token" not in " ".join(values)  # base64-encoded, and never on a command line
    assert env["GIT_ALLOW_PROTOCOL"] == "https" and env["GIT_TERMINAL_PROMPT"] == "0"
    keys = {env[f"GIT_CONFIG_KEY_{index}"]: env[f"GIT_CONFIG_VALUE_{index}"]
            for index in range(int(env["GIT_CONFIG_COUNT"]))}
    assert keys["core.hooksPath"] == "/dev/null" and keys["http.followRedirects"] == "false"
    assert keys["protocol.allow"] == "never" and keys["protocol.https.allow"] == "always"


def test_repository_urls_are_normalized():
    assert normalize_repository_url("https://GitHub.com/a/b/", ("github.com",)) == "https://github.com/a/b"


@pytest.mark.parametrize(("text", "spdx"), [
    (MPL, "MPL-2.0"), (APACHE, "Apache-2.0"), (MIT, "MIT"),
    ("Copyright\n\nRedistribution and use in source and binary forms, with or without\nmodification ...\n"
     "3. Neither the name of the copyright holder nor the names", "BSD-3-Clause"),
    ("Copyright\n\nRedistribution and use in source and binary forms, with or without modification", "BSD-2-Clause"),
    ("ISC License\n\nCopyright", "ISC"),
    ("GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3, 19 November 2007", "AGPL-3.0"),
    ("GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007", "GPL-3.0"),
    ("All rights reserved. Permit license only by contract.", None),
])
def test_licence_texts_are_identified_by_their_title_lines(text, spdx):
    assert identify_licence_text(text) == spdx


def test_licence_precedence_frontmatter_then_plugin_then_repository():
    files = {"LICENSE": MIT}
    assert detect_licence(frontmatter_licence="Apache-2.0", plugin_licence="MPL-2.0", repository_files=files).spdx \
        == "Apache-2.0"
    assert detect_licence(frontmatter_licence=None, plugin_licence="MPL-2.0", repository_files=files).source == "plugin"
    found = detect_licence(frontmatter_licence="not spdx!", plugin_licence=None, repository_files=files)
    assert (found.spdx, found.source, found.text_path) == ("MIT", "repository", "LICENSE")
    assert detect_licence(frontmatter_licence=None, plugin_licence=None, repository_files={}).spdx is None


def test_layout_finds_skills_plugins_and_ignored_components():
    paths = ["p/.claude-plugin/plugin.json", "p/.mcp.json", "p/skills/a/SKILL.md", "p/skills/a/references/x.md",
             "p/skills/a/inner/SKILL.md", "p/skills/b/SKILL.md", "p/commands/c.md", "p/.lsp.json",
             "p/.codex-plugin/plugin.json", "other/skills/z/SKILL.md"]
    layout = find_layout(paths, "p")
    assert [(item.path, item.files) for item in layout.skills] == [
        ("p/skills/a", ("SKILL.md", "inner/SKILL.md", "references/x.md")), ("p/skills/b", ("SKILL.md",))]
    assert [(item.path, item.files) for item in layout.plugins] == [("p", (".claude-plugin/plugin.json", ".mcp.json"))]
    assert {item["path"] for item in layout.ignored} == {"p/skills/a/inner/SKILL.md", "p/commands", "p/.lsp.json",
                                                         "p/.codex-plugin"}
    assert {item.path for item in find_layout(paths, "").skills} == {"p/skills/a", "p/skills/b", "other/skills/z"}


def test_marketplace_sources_resolve_to_a_folder_or_another_repository():
    paths = {"plugins/fmt/.mcp.json", "external_plugins/terraform/.mcp.json"}
    document = ('{"metadata": {"pluginRoot": "./plugins"}, "plugins": ['
                '{"name": "fmt", "source": "fmt"}, {"name": "tf", "source": "./external_plugins/terraform"},'
                '{"name": "gh", "source": {"source": "github", "repo": "acme/tools", "sha": "' + "a" * 40 + '"}},'
                '{"name": "sub", "source": {"source": "git-subdir", "url": "https://github.com/acme/mono.git", '
                '"path": "tools/x", "ref": "main"}},'
                '{"name": "npm", "source": {"source": "npm", "package": "x"}}]}')
    assert resolve_marketplace_entry(document, "fmt", paths).path == "plugins/fmt"
    assert resolve_marketplace_entry(document, "tf", paths).path == "external_plugins/terraform"
    github = resolve_marketplace_entry(document, "gh", paths)
    assert (github.url, github.ref, github.path) == ("https://github.com/acme/tools", "a" * 40, "")
    sub = resolve_marketplace_entry(document, "sub", paths)
    assert (sub.url, sub.ref, sub.path) == ("https://github.com/acme/mono", "main", "tools/x")
    for name, code in [("npm", "plugin_source_unsupported"), ("missing", "marketplace_plugin_not_found")]:
        with pytest.raises(SkillCatalogError) as refused:
            resolve_marketplace_entry(document, name, paths)
        assert refused.value.code == code
    with pytest.raises(SkillCatalogError) as escape:
        resolve_marketplace_entry('{"plugins": [{"name": "x", "source": "../../etc"}]}', "x", paths)
    assert escape.value.code == "plugin_source_invalid"


def test_the_launch_spec_never_passes_shell_variables_through():
    raw = {"command": "docker", "args": ["run", "-i", "--rm", "-e", "TFE_TOKEN=${TFE_TOKEN}", "--network", "host",
                                         "hashicorp/terraform-mcp-server:0.4.0", "--toolsets", "registry"],
           "env": {"LOG_LEVEL": "info", "API_KEY": "${API_KEY}"}}
    spec = launch_spec("terraform", raw)
    assert spec["image"] == "hashicorp/terraform-mcp-server:0.4.0"
    assert spec["passthrough"] == ["API_KEY", "TFE_TOKEN"] and spec["env_values"] == {"LOG_LEVEL": "info"}
    reviewed = normalize_launch_spec({**spec, "image_digest": "sha256:" + "b" * 64,
                                      "env_connections": {"TFE_TOKEN": "conn-1"}}, upstream=spec)
    server = delivered_server(reviewed, {"TFE_TOKEN": "from-connection"})
    assert server["args"] == ["run", "-i", "--rm", "-e", "TFE_TOKEN", "--network", "host",
                              "hashicorp/terraform-mcp-server@sha256:" + "b" * 64, "--toolsets", "registry"]
    assert server["env"] == {"LOG_LEVEL": "info", "TFE_TOKEN": "from-connection"}
    for change, code in [({"image_digest": "latest"}, "skill_mcp_image_digest_invalid"),
                         ({"env_connections": {"HOME": "c"}}, "skill_mcp_env_unknown")]:
        with pytest.raises(SkillCatalogError) as refused:
            normalize_launch_spec({**spec, **change}, upstream=spec)
        assert refused.value.code == code
    # The command and args always come from the upstream files, never from the request.
    tampered = normalize_launch_spec({**spec, "command": "bash", "args": ["-c", "x"]}, upstream=spec)
    assert tampered["command"] == "docker" and tampered["args"] == spec["args"]
    with pytest.raises(SkillCatalogError) as remote:
        launch_spec("remote", {"type": "http", "url": "https://mcp.example.com"})
    assert remote.value.code == "skill_mcp_remote_not_supported"
