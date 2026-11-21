from pathlib import Path

from app.services.repo_microagent import discover_repo_microagents, select_relevant_repo_microagents


def test_discover_repo_microagents_from_workspace_and_allowed_repositories(tmp_path: Path):
    workspace_agent_root = tmp_path / ".agents"
    workspace_agent_root.mkdir(parents=True)
    (workspace_agent_root / "payments.md").write_text(
        "---\nname: Payment Triage\ndescription: Focus on payment incidents\ntriggers: [payment, checkout]\ncapabilities: [diagnosis]\nalways_include: true\n---\nInspect payment failures before unrelated systems.\n",
        encoding="utf-8",
    )

    repo_agent_root = tmp_path / "var" / "repos" / "bitbucket" / "RIVER" / "service-config" / ".agents"
    repo_agent_root.mkdir(parents=True)
    (repo_agent_root / "gitops.md").write_text(
        "---\nname: GitOps Deploy Agent\ntriggers: [deploy, release]\ncapabilities: [change, diagnosis]\npriority: 40\n---\nTreat release/prod branches as deployment truth.\n",
        encoding="utf-8",
    )

    entries = discover_repo_microagents(
        workspace_root=str(tmp_path),
        project_config={
            "managed_repo_root": "var/repos/bitbucket",
            "bitbucket_allowed_repos": [{"project_key": "RIVER", "repo_slug": "service-config", "enabled": True}],
        },
    )

    assert {entry["name"] for entry in entries} == {"Payment Triage", "GitOps Deploy Agent"}
    gitops = next(entry for entry in entries if entry["name"] == "GitOps Deploy Agent")
    assert gitops["repo_label"] == "RIVER/service-config"
    assert gitops["source_kind"] == "repository"


def test_select_relevant_repo_microagents_activates_explicitly_never_by_prompt_words():
    entries = [
        {
            "name": "Global Incident Agent",
            "description": "",
            "instructions": "Always collect core evidence first.",
            "capabilities": ["diagnosis"],
            "triggers": ["incident"],
            "repo_scope": [],
            "always_include": True,
            "priority": 5,
            "source_kind": "workspace",
            "repo_label": None,
            "source_path": "/tmp/.agents/global.md",
            "relative_path": ".agents/global.md",
        },
        {
            "name": "GitOps Deploy Agent",
            "description": "",
            "instructions": "Release branches define live state.",
            "capabilities": ["diagnosis"],
            "triggers": ["deploy", "release"],
            "repo_scope": [],
            "always_include": False,
            "priority": 40,
            "source_kind": "repository",
            "repo_label": "RIVER/service-config",
            "source_path": "/tmp/var/repos/bitbucket/RIVER/service-config/.agents/gitops.md",
            "relative_path": "var/repos/bitbucket/RIVER/service-config/.agents/gitops.md",
        },
    ]

    # Triggers and repository mentions activate nothing; always_include does.
    selected = select_relevant_repo_microagents(microagents=entries, capability_type="diagnosis")
    assert [entry["name"] for entry in selected] == ["Global Incident Agent"]
    # The capability filter still applies to an always_include entry.
    assert select_relevant_repo_microagents(microagents=entries, capability_type="change") == []
