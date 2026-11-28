"""An in-memory Git fetcher for the skill catalog tests: no network, deterministic commits."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from app.services.skill_catalog.errors import SkillCatalogError
from app.services.skill_catalog.git_source import RepoSnapshot, TreeEntry, set_git_fetcher

HASHICORP = "https://github.com/hashicorp/agent-skills"
OFFICIAL = "https://github.com/anthropics/claude-plugins-official"
COMMUNITY = "https://github.com/wshobson/agents"

OLD = "0374056f" + "0" * 32
NEW = "4451ceca" + "0" * 32
MARKET = "ba3a4e07" + "0" * 32
MARKET_LATER = "054417d0" + "0" * 32
HELM = "be57c0b2" + "0" * 32

MPL = "Mozilla Public License Version 2.0\n==================================\n\n1. Definitions\n"
APACHE = "\n                                 Apache License\n                           Version 2.0, January 2004\n"
MIT = "MIT License\n\nCopyright (c) 2024 Example Author\n\nPermission is hereby granted, free of charge, ...\n"

STYLE_OLD = """---
name: terraform-style-guide
description: Generate Terraform HCL code following HashiCorp's style conventions. Use when writing Terraform.
---

# Terraform Style Guide

## Code Review Checklist

- [ ] Code formatted with `terraform fmt`
- [ ] Variables have type and description

## Security Best Practices

- Enable encryption at rest by default
- Never hardcode credentials
- Use least-privilege IAM policies

## Version Pinning

```hcl
terraform {
  required_version = ">= 1.7"
}
```
"""

STYLE_NEW = """---
name: terraform-style-guide
description: Generate Terraform HCL code following HashiCorp's style conventions. Use when writing Terraform.
metadata:
  lifecycle-status: active
---

# Terraform Style Guide

## Code Review Checklist

- [ ] Code formatted with `terraform fmt`
- [ ] Variables have type and description

## Security Best Practices

Refer to SECURITY.md for the security checklist.

## Version Pinning

```hcl
terraform {
  required_version = ">= 1.14"
}
```
"""

SECURITY = """---
name: terraform-style-guide-security
description: Security checklist for Terraform code.
---

# Security

## Security Best Practices

- Enable encryption at rest by default
- Never hardcode credentials
- Use least-privilege IAM policies
"""

HELM_SKILL = """---
name: helm-chart-scaffolding
description: Design, organize, and manage Helm charts. Use when creating Helm charts.
---

# Helm Chart Scaffolding

Run `scripts/validate-chart.sh` to lint the chart.
"""

MARKETPLACE = """{
  "name": "claude-plugins-official",
  "owner": {"name": "Anthropic"},
  "plugins": [
    {"name": "terraform", "author": {"name": "HashiCorp"}, "category": "development",
     "source": "./external_plugins/terraform", "description": "The Terraform MCP Server."},
    {"name": "early", "source": "./external_plugins/early", "description": "Folder not there yet."}
  ]
}
"""
PLUGIN_JSON = '{"name": "terraform", "description": "The Terraform MCP Server.", "author": {"name": "HashiCorp"}}'
MCP_JSON = ('{"terraform": {"command": "docker", "args": ["run", "-i", "--rm", "-e", "TFE_TOKEN=${TFE_TOKEN}", '
            '"hashicorp/terraform-mcp-server:0.4.0"]}}')

_OLD_ROOT = "terraform/code-generation"
_NEW_ROOT = "plugins/terraform"

REPOS: dict[str, dict[str, dict[str, tuple[str, str]]]] = {
    HASHICORP: {
        OLD: {
            "LICENSE": (MPL, "100644"),
            f"{_OLD_ROOT}/.claude-plugin/plugin.json": ('{"name": "terraform-code-generation", "license": "MPL-2.0"}',
                                                        "100644"),
            f"{_OLD_ROOT}/skills/terraform-style-guide/SKILL.md": (STYLE_OLD, "100644"),
            f"{_OLD_ROOT}/skills/terraform-test/SKILL.md": (
                "---\nname: terraform-test\ndescription: Write Terraform tests.\n---\n\n# Tests\n", "100644"),
            "README.md": ("# Agent skills\n", "100644"),
        },
        NEW: {
            "LICENSE": (MPL, "100644"),
            f"{_NEW_ROOT}/.claude-plugin/plugin.json": ('{"name": "terraform", "license": "MPL-2.0"}', "100644"),
            f"{_NEW_ROOT}/skills/terraform-style-guide/SKILL.md": (STYLE_NEW, "100644"),
            f"{_NEW_ROOT}/skills/terraform-style-guide/SECURITY.md": (SECURITY, "100644"),
            f"{_NEW_ROOT}/skills/terraform-test/SKILL.md": (
                "---\nname: terraform-test\ndescription: Write Terraform tests.\n---\n\n# Tests\n", "100644"),
            "README.md": ("# Agent skills (consolidated)\n", "100644"),
        },
    },
    OFFICIAL: {
        commit: {
            "LICENSE": (APACHE, "100644"),
            ".claude-plugin/marketplace.json": (MARKETPLACE, "100644"),
            "external_plugins/terraform/.claude-plugin/plugin.json": (PLUGIN_JSON, "100644"),
            "external_plugins/terraform/.mcp.json": (MCP_JSON, "100644"),
            "README.md": ("# Official plugins\n" + ("later\n" if commit == MARKET_LATER else ""), "100644"),
        } for commit in (MARKET, MARKET_LATER)
    },
    COMMUNITY: {
        HELM: {
            "LICENSE": (MIT, "100644"),
            "plugins/kubernetes-operations/.claude-plugin/plugin.json": ('{"name": "kubernetes-operations"}', "100644"),
            "plugins/kubernetes-operations/skills/helm-chart-scaffolding/SKILL.md": (HELM_SKILL, "100644"),
            "plugins/kubernetes-operations/skills/helm-chart-scaffolding/references/chart-structure.md": (
                "# Chart structure\n", "100644"),
            "plugins/kubernetes-operations/skills/helm-chart-scaffolding/assets/values.yaml.template": (
                "replicaCount: 1\n", "100644"),
            "plugins/kubernetes-operations/skills/helm-chart-scaffolding/scripts/validate-chart.sh": (
                "#!/usr/bin/env bash\nhelm lint \"$1\"\nhelm install test \"$1\" --dry-run --debug\n", "100755"),
            "plugins/kubernetes-operations/agents/k8s-architect.md": ("# Agent\n", "100644"),
            "plugins/kubernetes-operations/hooks/hooks.json": ("{}", "100644"),
        },
    },
}
REFS: dict[str, dict[str, str]] = {
    HASHICORP: {"main": NEW, "HEAD": NEW},
    OFFICIAL: {"main": MARKET_LATER, "HEAD": MARKET_LATER},
    COMMUNITY: {"main": HELM, "HEAD": HELM},
}


class FakeGit:
    def __init__(self) -> None:
        self.repos = {url: {commit: dict(files) for commit, files in commits.items()} for url, commits in REPOS.items()}
        self.refs = {url: dict(refs) for url, refs in REFS.items()}
        self.calls: list[tuple[str, str, str, str | None]] = []

    async def resolve(self, url: str, ref: str, *, token: str | None) -> str:
        self.calls.append(("resolve", url, ref, token))
        if len(ref) == 40:
            return ref
        commit = self.refs.get(url, {}).get(ref)
        if commit is None:
            raise SkillCatalogError("skill_source_ref_not_found", 422, ref=ref)
        return commit

    @asynccontextmanager
    async def open(self, url: str, commit: str, *, token: str | None) -> AsyncIterator[RepoSnapshot]:
        self.calls.append(("open", url, commit, token))
        files = self.repos.get(url, {}).get(commit)
        if files is None:
            raise SkillCatalogError("skill_source_fetch_failed", 502)
        entries = {path: TreeEntry(path, mode) for path, (_, mode) in files.items()}

        class Reader:
            async def read(self, paths: list[str]) -> dict[str, bytes]:
                return {path: files[path][0].encode() for path in paths if path in files}

        yield RepoSnapshot(url=url, commit=commit, entries=entries, reader=Reader())


@pytest.fixture
def fake_git():
    fake = FakeGit()
    set_git_fetcher(fake)
    try:
        yield fake
    finally:
        set_git_fetcher(None)
